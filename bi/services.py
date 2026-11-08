"""Inteligencia de negocios: indicadores, predicción de demanda, tarifas inteligentes, mantenimiento predictivo
y alertas. Los procesos pesados corren de noche (Celery) y guardan resultados en `predicciones` y `alertas`."""

import logging
from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal

import numpy as np
import pandas as pd
from django.db import IntegrityError, transaction
from django.db.models import Count, Sum
from django.utils import timezone

from core import roles
from habitaciones.models import BloqueoHabitacion, Habitacion, TipoHabitacion

from . import feriados
from .models import Alerta, Prediccion, RecomendacionTarifa

logger = logging.getLogger(__name__)
CERO = Decimal("0")
OCUPANTES = ("en_curso", "finalizada")
EN_CARTERA = ("pendiente", "confirmada", "en_curso", "finalizada")


def _rango(desde, hasta):
    return [desde + timedelta(days=i) for i in range((hasta - desde).days + 1)]


def _pct(a, b):
    return round(float(a) / float(b) * 100, 2) if b else 0.0


def _div(a, b):
    return (Decimal(a) / Decimal(b)).quantize(Decimal("0.01")) if b else CERO


# ---------------------------------------------------------------- Indicadores


def noches_disponibles_por_dia(hotel, desde, hasta):
    """Habitaciones vendibles por día (activas, existentes a esa fecha y no bloqueadas)."""
    habs = list(Habitacion.objects.filter(hotel=hotel, activo=True).values("id", "creado_en"))
    bloqueos = list(
        BloqueoHabitacion.objects.filter(hotel=hotel, activo=True, fecha_desde__lte=hasta).values(
            "habitacion_id", "fecha_desde", "fecha_hasta"
        )
    )
    resultado = {}
    for d in _rango(desde, hasta):
        bloqueadas = {
            b["habitacion_id"]
            for b in bloqueos
            if b["fecha_desde"] <= d and (b["fecha_hasta"] is None or b["fecha_hasta"] >= d)
        }
        resultado[d] = sum(1 for h in habs if h["id"] not in bloqueadas)
    return resultado


def noches_ocupadas_por_dia(hotel, desde, hasta, estados=OCUPANTES, tipo=None, creadas_antes=None):
    from reservas.models import DetalleReserva

    qs = DetalleReserva.objects.filter(
        hotel=hotel, activo=True, reserva__estado__in=estados, fecha_entrada__lte=hasta, fecha_salida__gt=desde
    )
    if estados != OCUPANTES:
        qs = qs.filter(vigente=True)
    if tipo is not None:
        qs = qs.filter(tipo_habitacion=tipo)
    if creadas_antes is not None:
        qs = qs.filter(reserva__creado_en__lt=creadas_antes)
    conteo = defaultdict(int)
    for entrada, salida in qs.values_list("fecha_entrada", "fecha_salida"):
        d = max(entrada, desde)
        while d < salida and d <= hasta:
            conteo[d] += 1
            d += timedelta(days=1)
    return {d: conteo.get(d, 0) for d in _rango(desde, hasta)}


def kpis(hotel, desde, hasta):
    """Indicadores del período [desde, hasta] (ambas fechas inclusive, por noche)."""
    from caja.models import Cargo
    from compras.models import Gasto
    from mantenimiento.models import Mantenimiento
    from reservas.models import Reserva

    disponibles = noches_disponibles_por_dia(hotel, desde, hasta)
    ocupadas = noches_ocupadas_por_dia(hotel, desde, hasta)
    total_disp = sum(disponibles.values())
    total_ocup = sum(ocupadas.values())
    cargos = Cargo.objects.filter(hotel=hotel, activo=True, fecha__gte=desde, fecha__lte=hasta)
    ingresos_aloj = cargos.filter(origen=Cargo.Origen.NOCHE).aggregate(t=Sum("importe"))["t"] or CERO
    ingresos_totales = cargos.aggregate(t=Sum("importe"))["t"] or CERO

    reservas = Reserva.objects.filter(hotel=hotel, activo=True, fecha_entrada__gte=desde, fecha_entrada__lte=hasta)
    total_res = reservas.count()
    canceladas = reservas.filter(estado=Reserva.Estado.CANCELADA).count()
    no_show = reservas.filter(estado=Reserva.Estado.NO_SHOW).count()
    efectivas = reservas.filter(estado__in=OCUPANTES)
    noches_efectivas = sum(r.noches for r in efectivas)
    antelaciones = [
        (r.fecha_entrada - timezone.localtime(r.creado_en).date()).days
        for r in reservas.exclude(estado=Reserva.Estado.CANCELADA)
    ]

    por_canal = defaultdict(lambda: CERO)
    por_tipo = defaultdict(lambda: CERO)
    for canal, tipo, importe in cargos.filter(origen=Cargo.Origen.NOCHE).values_list(
        "reserva__canal", "detalle__tipo_habitacion__nombre", "importe"
    ):
        por_canal[dict(Reserva.Canal.choices).get(canal, canal)] += importe
        por_tipo[tipo or "Sin tipo"] += importe

    mant = Mantenimiento.objects.filter(
        hotel=hotel,
        activo=True,
        estado=Mantenimiento.Estado.REALIZADO,
        fecha_realizado__gte=desde,
        fecha_realizado__lte=hasta,
    )
    costo_hab, costo_activo, costo_mes = defaultdict(lambda: CERO), defaultdict(lambda: CERO), defaultdict(lambda: CERO)
    for m in mant.select_related("habitacion", "activo_relacionado").prefetch_related("repuestos"):
        costo = m.costo_total
        if m.habitacion_id:
            costo_hab[f"Hab. {m.habitacion}"] += costo
        if m.activo_relacionado_id:
            costo_activo[str(m.activo_relacionado)] += costo
        costo_mes[f"{m.fecha_realizado:%Y-%m}"] += costo
    gastos = (
        Gasto.objects.filter(hotel=hotel, activo=True, fecha__gte=desde, fecha__lte=hasta).aggregate(t=Sum("importe"))[
            "t"
        ]
        or CERO
    )
    costo_mant_sin_compras = sum((m.costo_mano_obra + m.costo_externo for m in mant), CERO)
    gastos_operativos = gastos + costo_mant_sin_compras

    return {
        "desde": desde,
        "hasta": hasta,
        "noches_disponibles": total_disp,
        "noches_ocupadas": total_ocup,
        "ocupacion": _pct(total_ocup, total_disp),
        "ingresos_alojamiento": ingresos_aloj,
        "ingresos_totales": ingresos_totales,
        "adr": _div(ingresos_aloj, total_ocup),
        "revpar": _div(ingresos_aloj, total_disp),
        "reservas": total_res,
        "estadia_promedio": round(noches_efectivas / efectivas.count(), 2) if efectivas.count() else 0,
        "antelacion_promedio": round(sum(antelaciones) / len(antelaciones), 1) if antelaciones else 0,
        "tasa_cancelacion": _pct(canceladas, total_res),
        "tasa_no_show": _pct(no_show, total_res),
        "ingresos_por_canal": dict(sorted(por_canal.items(), key=lambda x: -x[1])),
        "ingresos_por_tipo": dict(sorted(por_tipo.items(), key=lambda x: -x[1])),
        "costo_mant_por_habitacion": dict(sorted(costo_hab.items(), key=lambda x: -x[1])),
        "costo_mant_por_activo": dict(sorted(costo_activo.items(), key=lambda x: -x[1])),
        "costo_mant_por_mes": dict(sorted(costo_mes.items())),
        "gastos_operativos": gastos_operativos,
        "rentabilidad": ingresos_totales - gastos_operativos,
        "serie_ocupacion": [{"fecha": d, "ocupacion": _pct(ocupadas[d], disponibles[d])} for d in sorted(disponibles)],
    }


def comparar_anio_anterior(hotel, desde, hasta):
    actual = kpis(hotel, desde, hasta)

    def menos_un_anio(d):
        try:
            return d.replace(year=d.year - 1)
        except ValueError:  # 29 de febrero
            return d.replace(year=d.year - 1, day=28)

    anterior = kpis(hotel, menos_un_anio(desde), menos_un_anio(hasta))
    variaciones = {}
    for k in (
        "ocupacion",
        "adr",
        "revpar",
        "ingresos_alojamiento",
        "ingresos_totales",
        "estadia_promedio",
        "antelacion_promedio",
        "tasa_cancelacion",
        "tasa_no_show",
        "rentabilidad",
    ):
        a, b = float(actual[k]), float(anterior[k])
        variaciones[k] = round((a / b - 1) * 100, 1) if b else None
    return actual, anterior, variaciones


def periodo(vista, referencia=None, a_la_fecha=False):
    """Rango para las vistas diaria, mensual y anual.

    Con a_la_fecha, un período en curso se corta en hoy (los días futuros aún no tienen ocupación real)."""
    ref = referencia or timezone.localdate()
    if vista == "diaria":
        return ref, ref
    if vista == "anual":
        inicio, fin = date(ref.year, 1, 1), date(ref.year, 12, 31)
    else:
        inicio = ref.replace(day=1)
        fin = (inicio + timedelta(days=32)).replace(day=1) - timedelta(days=1)
    hoy = timezone.localdate()
    if a_la_fecha and inicio <= hoy < fin:
        fin = hoy
    return inicio, fin


# ---------------------------------------------------------------- Predicción de demanda

HORIZONTES = [1, 7, 14, 30, 60, 90]


def _mape(real, pred):
    real, pred = np.asarray(real, dtype=float), np.asarray(pred, dtype=float)
    mask = real > 0
    if not mask.any():
        return None
    return float(np.mean(np.abs((real[mask] - pred[mask]) / real[mask])) * 100)


def serie_historica(hotel, desde, hasta):
    disp = noches_disponibles_por_dia(hotel, desde, hasta)
    ocup = noches_ocupadas_por_dia(hotel, desde, hasta)
    df = pd.DataFrame({"fecha": list(disp), "disponibles": list(disp.values()), "ocupadas": [ocup[d] for d in disp]})
    df["ocupacion"] = np.where(df["disponibles"] > 0, df["ocupadas"] / df["disponibles"] * 100, 0.0)
    df["fecha"] = pd.to_datetime(df["fecha"])
    return df


def _features(fechas, cartera):
    f = pd.DataFrame({"fecha": pd.to_datetime(fechas)})
    f["dow"] = f["fecha"].dt.dayofweek
    f["mes"] = f["fecha"].dt.month
    doy = f["fecha"].dt.dayofyear
    f["doy_sin"] = np.sin(2 * np.pi * doy / 365.25)
    f["doy_cos"] = np.cos(2 * np.pi * doy / 365.25)
    f["feriado"] = [int(feriados.es_feriado(d.date())) for d in f["fecha"]]
    f["finde_largo"] = [int(feriados.es_fin_de_semana_largo(d.date())) for d in f["fecha"]]
    f["cartera"] = cartera
    return f.drop(columns=["fecha"])


def _linea_base(hist, fechas):
    """Promedio estacional por día de la semana (mismo mes); si falta, mismo día de la semana."""
    h = hist.copy()
    h["dow"], h["mes"] = h["fecha"].dt.dayofweek, h["fecha"].dt.month
    por_mes_dow = h.groupby(["mes", "dow"])["ocupacion"].mean().to_dict()
    por_dow = h.groupby("dow")["ocupacion"].mean().to_dict()
    general = h["ocupacion"].mean() if len(h) else 0.0
    res = []
    for d in pd.to_datetime(fechas):
        res.append(por_mes_dow.get((d.month, d.dayofweek), por_dow.get(d.dayofweek, general)))
    return np.array(res, dtype=float)


def _cartera(hotel, fechas, lead_days):
    """Ocupación ya reservada (en cartera) para cada fecha, vista `lead_days` antes."""
    res = []
    habs = Habitacion.objects.filter(hotel=hotel, activo=True).count() or 1
    for d in fechas:
        d = d.date() if hasattr(d, "date") else d
        corte = timezone.make_aware(pd.Timestamp(d - timedelta(days=lead_days)).to_pydatetime())
        n = noches_ocupadas_por_dia(hotel, d, d, estados=EN_CARTERA, creadas_antes=corte)[d]
        res.append(n / habs * 100)
    return res


def predecir_demanda(hotel, dias=90, hoy=None):
    """Calcula y guarda la ocupación proyectada de los próximos `dias`. Devuelve el resumen del modelo."""
    from sklearn.ensemble import GradientBoostingRegressor

    hoy = hoy or timezone.localdate()
    from reservas.models import Reserva

    primera = (
        Reserva.objects.filter(hotel=hotel, activo=True)
        .order_by("fecha_entrada")
        .values_list("fecha_entrada", flat=True)
        .first()
    )
    futuras = [hoy + timedelta(days=i) for i in range(dias)]
    habs = Habitacion.objects.filter(hotel=hotel, activo=True).count() or 1
    cartera_hoy = [noches_ocupadas_por_dia(hotel, d, d, estados=EN_CARTERA)[d] / habs * 100 for d in futuras]

    if primera is None or (hoy - primera).days < 60:
        modelo = "reglas"
        pred = np.array(cartera_hoy, dtype=float)
        resumen = {
            "modelo": modelo,
            "motivo": "Menos de 60 días de historia: se usa la ocupación en cartera.",
            "dias_historia": (hoy - primera).days if primera else 0,
        }
        mape_m = mape_b = None
    else:
        hist = serie_historica(hotel, primera, hoy - timedelta(days=1))
        base_fut = _linea_base(hist, futuras)
        dias_hist = len(hist)
        corte = int(dias_hist * 0.8)
        test = hist.iloc[corte:]
        base_test = _linea_base(hist.iloc[:corte], test["fecha"])
        mape_b = _mape(test["ocupacion"], base_test)
        modelo, mape_m = "linea_base", None
        pred = np.maximum(base_fut, cartera_hoy)
        resumen = {"modelo": modelo, "dias_historia": dias_hist, "mape_linea_base": mape_b}
        if dias_hist >= 365:
            # Filas de entrenamiento: (fecha, horizonte) con la cartera vista a ese horizonte.
            filas_x, filas_y, filas_fecha = [], [], []
            muestra = hist.iloc[::2]  # submuestreo para acotar el costo de cálculo
            for h in HORIZONTES:
                cart = _cartera(hotel, muestra["fecha"], h)
                x = _features(muestra["fecha"], cart)
                x["horizonte"] = h
                filas_x.append(x)
                filas_y.append(muestra["ocupacion"].to_numpy())
                filas_fecha.append(muestra["fecha"].to_numpy())
            X = pd.concat(filas_x, ignore_index=True)
            y = np.concatenate(filas_y)
            fechas_x = np.concatenate(filas_fecha)
            limite = hist["fecha"].iloc[corte]
            entrenar = fechas_x < np.datetime64(limite)
            gbr = GradientBoostingRegressor(random_state=42, n_estimators=200, max_depth=3, learning_rate=0.05)
            gbr.fit(X[entrenar], y[entrenar])
            pred_test = gbr.predict(X[~entrenar])
            base_eval = _linea_base(hist.iloc[:corte], pd.to_datetime(fechas_x[~entrenar]))
            mape_m = _mape(y[~entrenar], pred_test)
            mape_b = _mape(y[~entrenar], base_eval)
            resumen.update({"mape_modelo": mape_m, "mape_linea_base": mape_b})
            # El modelo solo se activa si mejora a la línea base.
            if mape_m is not None and mape_b is not None and mape_m < mape_b:
                gbr.fit(X, y)
                xf = _features(futuras, cartera_hoy)
                xf["horizonte"] = [min(HORIZONTES, key=lambda h: abs(h - (d - hoy).days)) for d in futuras]
                pred = np.maximum(gbr.predict(xf), cartera_hoy)
                modelo = "ml_gradient_boosting"
                resumen["modelo"] = modelo
            else:
                resumen["motivo"] = "El modelo de ML no mejoró a la línea base: se mantiene la línea base."
        else:
            resumen["motivo"] = "Menos de 12 meses de historia: se usa la línea base estacional."
    pred = np.clip(pred, 0, 100)
    with transaction.atomic():
        for d, valor, cart in zip(futuras, pred, cartera_hoy):
            Prediccion.objects.update_or_create(
                hotel=hotel,
                tipo=Prediccion.Tipo.OCUPACION,
                fecha_objetivo=d,
                defaults={
                    "valor": Decimal(str(round(float(valor), 2))),
                    "modelo": resumen["modelo"],
                    "mape_modelo": _dec(mape_m),
                    "mape_linea_base": _dec(mape_b),
                    "datos_base": {
                        "en_cartera": round(cart, 2),
                        "feriado": feriados.es_feriado(d),
                        "dia_semana": d.weekday(),
                        **{k: v for k, v in resumen.items() if isinstance(v, (str, int, float))},
                    },
                },
            )
    return resumen


def _dec(v):
    return Decimal(str(round(v, 2))) if v is not None else None


# ---------------------------------------------------------------- Tarifas inteligentes


def recomendar_tarifas(hotel, dias=60, hoy=None):
    from habitaciones.services import precio_noche

    hoy = hoy or timezone.localdate()
    preds = {
        p.fecha_objetivo: p
        for p in Prediccion.objects.filter(
            hotel=hotel, fecha_objetivo__gte=hoy, fecha_objetivo__lt=hoy + timedelta(days=dias)
        )
    }
    creadas = 0
    for tipo in TipoHabitacion.objects.filter(hotel=hotel, activo=True):
        cant = tipo.habitaciones.filter(activo=True).count()
        if not cant:
            continue
        cartera_tipo = noches_ocupadas_por_dia(
            hotel, hoy, hoy + timedelta(days=dias - 1), estados=EN_CARTERA, tipo=tipo
        )
        for i in range(dias):
            d = hoy + timedelta(days=i)
            pred = preds.get(d)
            proyectada = float(pred.valor) if pred else 0.0
            ocup_tipo = cartera_tipo[d] / cant * 100
            precio, _ = precio_noche(tipo, d)
            if not precio:
                continue
            factor, razones = 1.0, []
            ref = max(proyectada, ocup_tipo)
            if ref >= 85:
                factor += 0.15
                razones.append(f"Ocupación proyectada muy alta ({ref:.0f} %)")
            elif ref >= 70:
                factor += 0.08
                razones.append(f"Ocupación proyectada alta ({ref:.0f} %)")
            elif ref <= 35 and i <= 14:
                factor -= 0.10
                razones.append(f"Ocupación baja ({ref:.0f} %) a menos de 15 días")
            elif ref <= 50 and i <= 30:
                factor -= 0.05
                razones.append(f"Ocupación moderada ({ref:.0f} %) a menos de 30 días")
            if feriados.es_fin_de_semana_largo(d):
                factor += 0.05
                razones.append("Feriado / fin de semana largo")
            if not razones:
                continue
            sugerido = Decimal(str(float(precio) * factor))
            minimo = tipo.precio_minimo or (precio * Decimal("0.7"))
            maximo = tipo.precio_maximo or (precio * Decimal("1.3"))
            sugerido = min(max(sugerido, minimo), maximo).quantize(Decimal("1"))
            if abs(sugerido - precio) / precio < Decimal("0.03"):
                continue
            RecomendacionTarifa.objects.filter(
                hotel=hotel, tipo_habitacion=tipo, fecha=d, estado=RecomendacionTarifa.Estado.PENDIENTE
            ).delete()
            RecomendacionTarifa.objects.create(
                hotel=hotel,
                tipo_habitacion=tipo,
                fecha=d,
                precio_actual=precio,
                precio_sugerido=sugerido,
                fundamento={
                    "razones": razones,
                    "ocupacion_proyectada_hotel": round(proyectada, 1),
                    "ocupacion_en_cartera_tipo": round(ocup_tipo, 1),
                    "dias_de_antelacion": i,
                    "modelo_demanda": pred.modelo if pred else "sin predicción",
                    "minimo": str(minimo),
                    "maximo": str(maximo),
                },
            )
            creadas += 1
    return creadas


@transaction.atomic
def decidir_recomendacion(rec, aprobar, usuario):
    """Siempre la aprueba una persona. Al aprobar se crea una tarifa puntual para ese día."""
    from habitaciones.models import Tarifa

    if rec.estado != RecomendacionTarifa.Estado.PENDIENTE:
        from django.core.exceptions import ValidationError

        raise ValidationError("La recomendación ya fue decidida.")
    rec.estado = RecomendacionTarifa.Estado.APROBADA if aprobar else RecomendacionTarifa.Estado.RECHAZADA
    rec.decidida_por = usuario
    rec.decidida_en = timezone.now()
    rec.save()
    if aprobar:
        Tarifa.objects.create(
            hotel=rec.hotel,
            tipo_habitacion=rec.tipo_habitacion,
            temporada="Tarifa dinámica",
            fecha_desde=rec.fecha,
            fecha_hasta=rec.fecha,
            precio_noche=rec.precio_sugerido,
            creado_por=usuario,
        )
    return rec


# ---------------------------------------------------------------- Mantenimiento predictivo


def ranking_riesgo(hotel, hoy=None):
    from mantenimiento.models import Activo, Incidencia

    hoy = hoy or timezone.localdate()
    filas = []
    for activo in Activo.objects.filter(hotel=hotel, activo=True).select_related("habitacion"):
        fallas = sorted(
            timezone.localtime(i.reportada_en).date()
            for i in Incidencia.objects.filter(activo_relacionado=activo, activo=True).exclude(
                origen=Incidencia.Origen.PREVENTIVO
            )
        )
        costo = sum((m.costo_total for m in activo.mantenimientos.filter(activo=True, estado="realizado")), CERO)
        intervalos = [(b - a).days for a, b in zip(fallas, fallas[1:])]
        mtbf = round(sum(intervalos) / len(intervalos), 1) if intervalos else None
        dias_desde = (hoy - fallas[-1]).days if fallas else None
        ultimo_anio = sum(1 for f in fallas if f >= hoy - timedelta(days=365))
        riesgo = ultimo_anio * 10
        if mtbf and dias_desde is not None:
            riesgo += min(dias_desde / mtbf, 2) * 20
        if activo.umbral_reemplazo:
            riesgo += min(float(costo / activo.umbral_reemplazo), 1.5) * 30
        filas.append(
            {
                "activo": activo,
                "fallas": len(fallas),
                "fallas_ultimo_anio": ultimo_anio,
                "mtbf_dias": mtbf,
                "dias_desde_ultima": dias_desde,
                "costo_acumulado": costo,
                "riesgo": round(riesgo, 1),
            }
        )
    return sorted(filas, key=lambda f: -f["riesgo"])


def ranking_habitaciones(hotel, hoy=None):
    from mantenimiento.models import Incidencia

    hoy = hoy or timezone.localdate()
    filas = []
    for hab in Habitacion.objects.filter(hotel=hotel, activo=True):
        fallas = sorted(
            timezone.localtime(i.reportada_en).date() for i in Incidencia.objects.filter(habitacion=hab, activo=True)
        )
        intervalos = [(b - a).days for a, b in zip(fallas, fallas[1:])]
        costo = sum((m.costo_total for m in hab.mantenimientos.filter(activo=True, estado="realizado")), CERO)
        filas.append(
            {
                "habitacion": hab,
                "fallas": len(fallas),
                "mtbf_dias": round(sum(intervalos) / len(intervalos), 1) if intervalos else None,
                "costo_acumulado": costo,
            }
        )
    return sorted(filas, key=lambda f: (-f["fallas"], -f["costo_acumulado"]))


# ---------------------------------------------------------------- Alertas


def crear_alerta(hotel, tipo, clave, titulo, mensaje, datos=None, nivel=Alerta.Nivel.ADVERTENCIA, notificar=True):
    if Alerta.objects.filter(hotel=hotel, clave=clave, resuelta=False).exists():
        return None
    try:
        with transaction.atomic():
            alerta = Alerta.objects.create(
                hotel=hotel, tipo=tipo, clave=clave, titulo=titulo, mensaje=mensaje, datos_base=datos or {}, nivel=nivel
            )
    except IntegrityError:
        return None
    if notificar:
        from notificaciones import services as notif

        notif.notificar_roles(hotel, [roles.ADMIN, roles.DUENO], titulo, mensaje, url="/bi/alertas/")
    return alerta


def alerta_diferencia_caja(caja):
    return crear_alerta(
        caja.hotel,
        Alerta.Tipo.DIFERENCIA_CAJA,
        f"caja:{caja.pk}",
        f"Diferencia en cierre de caja de {caja.usuario}",
        f"Esperado $ {caja.monto_esperado} / contado $ {caja.monto_contado} (diferencia $ {caja.diferencia}). "
        f"USD: diferencia {caja.diferencia_usd}.",
        {
            "caja": caja.pk,
            "esperado": str(caja.monto_esperado),
            "contado": str(caja.monto_contado),
            "diferencia": str(caja.diferencia),
            "diferencia_usd": str(caja.diferencia_usd),
        },
        nivel=Alerta.Nivel.CRITICA if abs(caja.diferencia) > 1000 else Alerta.Nivel.ADVERTENCIA,
    )


def alerta_stock_bajo(producto):
    total = producto.stock_total
    return crear_alerta(
        producto.hotel,
        Alerta.Tipo.STOCK_BAJO,
        f"stock:{producto.pk}",
        f"Stock bajo: {producto}",
        f"Quedan {total} {producto.unidad} (mínimo {producto.stock_minimo}).",
        {"producto": producto.pk, "stock": str(total), "minimo": str(producto.stock_minimo)},
    )


def alerta_incidencias_repetidas(incidencia, umbral=3, dias=30):
    from mantenimiento.models import Incidencia

    hab = incidencia.habitacion_afectada
    if hab is None:
        return None
    desde = timezone.now() - timedelta(days=dias)
    qs = Incidencia.objects.filter(activo=True, reportada_en__gte=desde, habitacion=hab) | Incidencia.objects.filter(
        activo=True, reportada_en__gte=desde, activo_relacionado__habitacion=hab
    )
    cantidad = qs.distinct().count()
    if cantidad < umbral:
        return None
    return crear_alerta(
        incidencia.hotel,
        Alerta.Tipo.INCIDENCIAS_REPETIDAS,
        f"repetidas:{hab.pk}:{timezone.localdate():%Y-%m}",
        f"Incidencias repetidas en la habitación {hab}",
        f"{cantidad} incidencias en los últimos {dias} días. Revise la causa raíz.",
        {"habitacion": hab.pk, "incidencias": list(qs.distinct().values_list("id", flat=True)), "dias": dias},
    )


def alerta_reemplazo_activo(activo):
    if activo is None or not activo.umbral_reemplazo:
        return None
    costo = sum((m.costo_total for m in activo.mantenimientos.filter(activo=True, estado="realizado")), CERO)
    if costo < activo.umbral_reemplazo:
        return None
    return crear_alerta(
        activo.hotel,
        Alerta.Tipo.REEMPLAZO_ACTIVO,
        f"reemplazo:{activo.pk}",
        f"Evaluar reemplazo de {activo}",
        f"El costo acumulado de mantenimiento ($ {costo}) superó el umbral de $ {activo.umbral_reemplazo}.",
        {"activo": activo.pk, "costo_acumulado": str(costo), "umbral": str(activo.umbral_reemplazo)},
        nivel=Alerta.Nivel.CRITICA,
    )


def alertas_ocupacion_baja(hotel, hoy=None, umbral=40, dias=14):
    hoy = hoy or timezone.localdate()
    bajas = list(
        Prediccion.objects.filter(
            hotel=hotel, fecha_objetivo__gte=hoy, fecha_objetivo__lt=hoy + timedelta(days=dias), valor__lt=umbral
        )
    )
    if not bajas:
        return None
    promedio = sum(float(p.valor) for p in bajas) / len(bajas)
    return crear_alerta(
        hotel,
        Alerta.Tipo.OCUPACION_BAJA,
        f"ocupacion_baja:{hoy:%Y-%W}",
        f"Ocupación proyectada baja en {len(bajas)} de los próximos {dias} días",
        f"Promedio proyectado {promedio:.0f} % (umbral {umbral} %). Considere promociones o ajustar tarifas.",
        {
            "dias": [
                {"fecha": p.fecha_objetivo.isoformat(), "ocupacion": float(p.valor), "modelo": p.modelo} for p in bajas
            ],
            "umbral": umbral,
        },
    )


def alertas_riesgo(hotel):
    creadas = 0
    for fila in ranking_riesgo(hotel)[:5]:
        if (
            fila["mtbf_dias"]
            and fila["dias_desde_ultima"] is not None
            and fila["fallas"] >= 3
            and fila["dias_desde_ultima"] >= 0.8 * fila["mtbf_dias"]
        ):
            a = crear_alerta(
                hotel,
                Alerta.Tipo.RIESGO_FALLA,
                f"riesgo:{fila['activo'].pk}:{timezone.localdate():%Y-%m}",
                f"Riesgo de falla: {fila['activo']}",
                f"Tiempo medio entre fallas {fila['mtbf_dias']} días; última falla hace {fila['dias_desde_ultima']} "
                "días. Se recomienda una revisión preventiva.",
                {k: (str(v) if isinstance(v, Decimal) else v) for k, v in fila.items() if k != "activo"},
            )
            creadas += bool(a)
    return creadas


def proceso_nocturno(hotel):
    from inventario.services import productos_bajo_minimo

    resumen = predecir_demanda(hotel)
    recs = recomendar_tarifas(hotel)
    alertas_ocupacion_baja(hotel)
    alertas_riesgo(hotel)
    for p in productos_bajo_minimo(hotel):
        alerta_stock_bajo(p)
    return {"prediccion": resumen, "recomendaciones": recs}


def resumen_ventas_por_canal(hotel, desde, hasta):
    from reservas.models import Reserva

    return (
        Reserva.objects.filter(hotel=hotel, activo=True, fecha_entrada__gte=desde, fecha_entrada__lte=hasta)
        .values("canal")
        .annotate(reservas=Count("id"), total=Sum("total"))
        .order_by("-total")
    )
