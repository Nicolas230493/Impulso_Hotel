"""Carga datos de demostración: planes, empresa con dos hoteles, usuarios por rol y ~14 meses de historia."""

import random
from datetime import date, time, timedelta
from decimal import Decimal

from django.contrib.auth.models import Group
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from core import actual, roles
from core.models import Empresa, Hotel, Usuario

CLAVE = "Impulso2026!"
NOMBRES = [
    "Juan",
    "María",
    "Lucía",
    "Martín",
    "Sofía",
    "Diego",
    "Valentina",
    "Pablo",
    "Camila",
    "Federico",
    "Florencia",
    "Nicolás",
    "Agustina",
    "Tomás",
    "Julieta",
    "Matías",
    "Carolina",
    "Santiago",
    "Paula",
    "Ignacio",
]
APELLIDOS = [
    "González",
    "Rodríguez",
    "Gómez",
    "Fernández",
    "López",
    "Díaz",
    "Martínez",
    "Pérez",
    "García",
    "Sánchez",
    "Romero",
    "Sosa",
    "Álvarez",
    "Torres",
    "Ruiz",
    "Ramírez",
    "Flores",
    "Benítez",
    "Acosta",
    "Medina",
]


class Command(BaseCommand):
    help = "Carga datos de demostración (idempotente: no hace nada si ya existe el hotel demo)."

    def add_arguments(self, parser):
        parser.add_argument("--meses", type=int, default=14, help="Meses de historia a generar")

    def handle(self, *args, **opciones):
        if Hotel.objects.filter(nombre="Hotel Impulso Bariloche").exists():
            self.stdout.write("Los datos demo ya existen.")
            return
        random.seed(42)
        self._saas()
        with transaction.atomic():
            empresa = Empresa.objects.create(
                razon_social="Hoteles del Sur S.A.",
                cuit="30712345678",
                email="admin@hotelesdelsur.com.ar",
                telefono="+54 294 442-0000",
            )
            from saas.models import EstadoOnboarding, Plan, Suscripcion

            hoy = timezone.localdate()
            Suscripcion.objects.create(
                empresa=empresa,
                plan=Plan.objects.get(nombre="Empresarial"),
                estado=Suscripcion.Estado.ACTIVA,
                inicio=hoy - timedelta(days=400),
                proximo_cobro=hoy + timedelta(days=12),
            )
            h1 = Hotel.objects.create(
                empresa=empresa,
                nombre="Hotel Impulso Bariloche",
                cuit="30712345678",
                direccion="Av. Bustillo 1234",
                localidad="San Carlos de Bariloche",
                provincia="Río Negro",
                telefono="+54 294 442-1111",
                email="reservas@impulsobariloche.com.ar",
                hora_checkin=time(14),
                hora_checkout=time(10),
                politica_cancelacion="Sin cargo hasta 72 h antes. Luego se retiene la seña.",
            )
            h2 = Hotel.objects.create(
                empresa=empresa,
                nombre="Hostel Impulso Mendoza",
                cuit="30712345678",
                direccion="Av. Arístides Villanueva 500",
                localidad="Mendoza",
                provincia="Mendoza",
                condicion_iva="RI",
            )
            for h in (h1, h2):
                EstadoOnboarding.objects.create(hotel=h, paso=5, completo=True)
            usuarios = self._usuarios(h1, h2)
        for hotel, n_habs in ((h1, 20), (h2, 8)):
            with actual.contexto(hotel=hotel, usuario=usuarios["admin"]), transaction.atomic():
                self._hotel(hotel, n_habs, usuarios, opciones["meses"])
        self.stdout.write(
            self.style.SUCCESS(
                f"Datos demo cargados. Usuarios: admin, recepcion, limpieza, mantenimiento, compras, dueno, soporte "
                f"(contraseña {CLAVE})."
            )
        )

    # ------------------------------------------------------------------
    def _saas(self):
        from saas.models import ArticuloConocimiento, DocumentoLegal, Plan, VersionCambio

        base = ["reservas", "caja", "facturacion", "inventario", "compras"]
        prof = base + ["limpieza", "mantenimiento", "personal", "whatsapp", "bi"]
        Plan.objects.get_or_create(
            nombre="Inicial",
            defaults=dict(
                publico_objetivo="Hostels y hoteles pequeños",
                max_habitaciones=20,
                max_hoteles=1,
                modulos=base,
                precio_mensual=Decimal("0"),
                orden=1,
            ),
        )
        Plan.objects.get_or_create(
            nombre="Profesional",
            defaults=dict(
                publico_objetivo="Hoteles medianos",
                max_habitaciones=80,
                max_hoteles=1,
                modulos=prof,
                precio_mensual=Decimal("0"),
                orden=2,
            ),
        )
        Plan.objects.get_or_create(
            nombre="Empresarial",
            defaults=dict(
                publico_objetivo="Hoteles grandes y cadenas",
                max_habitaciones=None,
                max_hoteles=20,
                modulos=prof + ["ia", "multi_hotel", "api"],
                precio_mensual=Decimal("0"),
                soporte_prioritario=True,
                orden=3,
            ),
        )
        DocumentoLegal.objects.get_or_create(
            tipo="terminos",
            version="1.0",
            defaults={
                "contenido": (
                    "BORRADOR A VALIDAR CON ASESORÍA LEGAL.\n\nImpulso presta el servicio de software de gestión hotelera "
                    "en modalidad de suscripción mensual. El cliente es responsable de la carga de datos y del cumplimiento "
                    "de sus obligaciones fiscales. Ante falta de pago, la cuenta pasa a modo solo lectura; los datos no se "
                    "eliminan."
                )
            },
        )
        DocumentoLegal.objects.get_or_create(
            tipo="datos",
            version="1.0",
            defaults={
                "contenido": (
                    "BORRADOR A VALIDAR CON ASESORÍA LEGAL.\n\nContrato de tratamiento de datos personales (Ley 25.326). "
                    "El hotel es responsable de la base de datos de huéspedes; Impulso actúa como encargado del tratamiento, "
                    "aplica medidas de seguridad, no cede datos a terceros y asiste en el ejercicio de los derechos de acceso, "
                    "rectificación y supresión."
                )
            },
        )
        for cat, titulo, texto in [
            (
                "Recepción",
                "Cómo hacer un walk-in",
                "Desde el panel de recepción, «Walk-in». Cargue documento del "
                "huésped, fecha de salida y elija la habitación: se crea la reserva y el check-in en un paso.",
            ),
            (
                "Caja",
                "Arqueo y cierre de caja",
                "En «Mi caja» indique el efectivo contado al cerrar. El sistema "
                "calcula lo esperado (inicial + ingresos − egresos en efectivo) y registra la diferencia.",
            ),
            (
                "Facturación",
                "Emitir una nota de crédito",
                "Una factura con CAE no se modifica. Desde la factura, "
                "«Emitir nota de crédito» con el motivo y, si es parcial, el importe.",
            ),
            (
                "Datos personales",
                "Pedido de acceso o supresión de un huésped",
                "Desde la ficha del huésped: "
                "«Exportar datos» (acceso) o «Suprimir datos» (anonimiza y conserva lo fiscal).",
            ),
        ]:
            ArticuloConocimiento.objects.get_or_create(titulo=titulo, defaults={"categoria": cat, "contenido": texto})
        VersionCambio.objects.get_or_create(
            version="1.0.0",
            defaults={
                "titulo": "Lanzamiento",
                "descripcion": "Reservas, recepción, caja, facturación ARCA, operaciones, "
                "inteligencia de negocios y comercialización SaaS.",
            },
        )

    def _usuarios(self, h1, h2):
        datos = [
            ("admin", roles.ADMIN, "Ana", "Administradora"),
            ("recepcion", roles.RECEPCION, "Raúl", "Recepción"),
            ("limpieza", roles.LIMPIEZA, "Laura", "Mucama"),
            ("limpieza2", roles.LIMPIEZA, "Lidia", "Mucama"),
            ("mantenimiento", roles.MANTENIMIENTO, "Marcos", "Técnico"),
            ("compras", roles.COMPRAS, "Carla", "Compras"),
            ("dueno", roles.DUENO, "Daniel", "Dueño"),
        ]
        res = {}
        for username, rol, nombre, apellido in datos:
            u = Usuario.objects.create_user(
                username=username,
                password=CLAVE,
                first_name=nombre,
                last_name=apellido,
                email=f"{username}@hotelesdelsur.com.ar",
                hotel_activo=h1,
            )
            u.groups.add(Group.objects.get(name=rol))
            u.hoteles.add(h1)
            if username in ("admin", "dueno"):
                u.hoteles.add(h2)
            res[username] = u
        sa = Usuario.objects.create_user(
            username="soporte",
            password=CLAVE,
            first_name="Soporte",
            last_name="Impulso",
            es_superadmin_impulso=True,
            is_staff=True,
        )
        sa.groups.add(Group.objects.get(name=roles.SUPERADMIN))
        return res

    def _hotel(self, hotel, n_habs, usuarios, meses):
        from caja.models import Cargo, Pago
        from caja.services import cargar_noches_reserva
        from compras.models import CategoriaGasto, Gasto, Proveedor
        from facturacion.models import PuntoVenta
        from habitaciones.models import Habitacion, Tarifa, TipoHabitacion
        from huespedes.models import Huesped
        from inventario.models import Deposito, Producto
        from inventario.services import registrar_movimiento
        from limpieza.models import ChecklistItem
        from mantenimiento.models import Activo, Incidencia, Mantenimiento, PlanPreventivo
        from notificaciones.models import PlantillaMensaje
        from personal.models import Empleado, Turno
        from reservas import services as res
        from reservas.models import Estadia, Reserva

        hoy = timezone.localdate()
        admin = usuarios["admin"]
        # --- Habitaciones y tarifas
        tipos = [
            TipoHabitacion.objects.create(
                hotel=hotel,
                nombre=n,
                capacidad=c,
                camas=cm,
                precio_base=p,
                precio_minimo=p * Decimal("0.7"),
                precio_maximo=p * Decimal("1.5"),
                amenities="Wi-Fi, TV, calefacción, baño privado",
            )
            for n, c, cm, p in [
                ("Individual", 1, "1 cama simple", Decimal("45000")),
                ("Doble", 2, "1 cama matrimonial", Decimal("65000")),
                ("Triple", 3, "1 matrimonial + 1 simple", Decimal("82000")),
                ("Suite", 4, "1 king + sofá cama", Decimal("120000")),
            ]
        ]
        habs = []
        for i in range(n_habs):
            piso = 1 + i // 6
            tipo = tipos[[0, 1, 1, 1, 2, 3][i % 6]]
            habs.append(Habitacion.objects.create(hotel=hotel, numero=f"{piso}{i % 6 + 1:02d}", piso=piso, tipo=tipo))
        for anio in (hoy.year - 1, hoy.year, hoy.year + 1):
            for t in tipos:
                Tarifa.objects.create(
                    hotel=hotel,
                    tipo_habitacion=t,
                    temporada=f"Invierno {anio}",
                    fecha_desde=date(anio, 7, 1),
                    fecha_hasta=date(anio, 8, 31),
                    precio_noche=t.precio_base * Decimal("1.4"),
                )
                Tarifa.objects.create(
                    hotel=hotel,
                    tipo_habitacion=t,
                    temporada=f"Verano {anio}",
                    fecha_desde=date(anio, 1, 2),
                    fecha_hasta=date(anio, 2, 28),
                    precio_noche=t.precio_base * Decimal("1.2"),
                )
        for i, txt in enumerate(
            [
                "Cambiar sábanas y toallas",
                "Limpiar baño",
                "Reponer amenities",
                "Aspirar y trapear",
                "Vaciar cestos",
                "Revisar minibar",
            ]
        ):
            ChecklistItem.objects.create(
                hotel=hotel, descripcion=txt, orden=i, tipo_tarea="" if i not in (0, 5) else "completa"
            )
        PuntoVenta.objects.create(
            hotel=hotel,
            numero=1 if hotel.nombre.startswith("Hotel") else 2,
            descripcion="Recepción",
            tipos_habilitados=[1, 3, 6, 8, 11, 13],
            por_defecto=True,
        )
        dep = Deposito.objects.create(hotel=hotel, nombre="Depósito principal")
        Deposito.objects.create(hotel=hotel, nombre="Office de pisos")
        for codigo, txt in [
            (
                "confirmacion",
                "Hola {nombre}, tu reserva {codigo} en {hotel} está confirmada: " "{entrada} al {salida}.",
            ),
            ("recordatorio", "Hola {nombre}, mañana te esperamos en {hotel}."),
            ("info_ingreso", "¡Bienvenido/a {nombre}! Check-in desde las {checkin}."),
            ("encuesta", "Gracias por elegir {hotel}. Contanos tu experiencia: {encuesta_url}"),
        ]:
            PlantillaMensaje.objects.create(
                hotel=hotel, codigo=codigo, cuerpo=txt, nombre_plantilla_meta=codigo, aprobada=True
            )
        # --- Inventario, proveedores, gastos
        prods = {}
        for nombre, cat, costo, venta, minimo in [
            ("Agua mineral 500 ml", "minibar", 600, 1500, 24),
            ("Gaseosa lata", "minibar", 800, 2000, 24),
            ("Cerveza artesanal", "minibar", 1800, 4500, 12),
            ("Shampoo monodosis", "amenities", 250, None, 100),
            ("Jabón de tocador", "amenities", 200, None, 100),
            ("Lavandina 5 L", "limpieza", 3500, None, 6),
            ("Detergente 5 L", "limpieza", 5200, None, 4),
            ("Juego de sábanas doble", "blancos", 28000, None, 10),
            ("Filtro de aire acondicionado", "repuestos", 9000, None, 4),
            ("Flexible de agua", "repuestos", 4500, None, 5),
            ("Lámpara LED", "repuestos", 2500, None, 10),
        ]:
            p = Producto.objects.create(
                hotel=hotel,
                nombre=nombre,
                categoria=cat,
                costo=costo,
                precio_venta=venta,
                stock_minimo=minimo,
                unidad="unidad",
            )
            registrar_movimiento(p, dep, "entrada", minimo * 3, "Stock inicial", admin, costo_unitario=costo)
            prods[nombre] = p
        provs = [
            Proveedor.objects.create(hotel=hotel, razon_social=n, cuit=c, rubro=r)
            for n, c, r in [
                ("Distribuidora Andina SRL", "30700000011", "Bebidas"),
                ("Limpiamax SA", "30700000022", "Limpieza"),
                ("Textil Patagonia SA", "30700000033", "Blancos"),
                ("Electro Sur SRL", "30700000044", "Repuestos"),
            ]
        ]
        cats = {
            n: CategoriaGasto.objects.create(hotel=hotel, nombre=n)
            for n in [
                "Servicios (luz, gas, agua)",
                "Sueldos y cargas",
                "Insumos",
                "Mantenimiento",
                "Marketing",
                "Impuestos y tasas",
            ]
        }
        escala = Decimal(len(habs)) / 20
        d = hoy.replace(day=1) - timedelta(days=30 * meses)
        while d <= hoy:
            for cat, monto in [
                ("Servicios (luz, gas, agua)", 900000),
                ("Sueldos y cargas", 6500000),
                ("Insumos", 450000),
                ("Marketing", 200000),
                ("Impuestos y tasas", 350000),
            ]:
                g = Gasto.objects.create(
                    hotel=hotel,
                    fecha=d.replace(day=min(10, 28)),
                    categoria=cats[cat],
                    descripcion=f"{cat} {d:%m/%Y}",
                    importe=(Decimal(monto) * escala * Decimal(random.uniform(0.85, 1.15))).quantize(Decimal("1")),
                    proveedor=random.choice(provs) if cat == "Insumos" else None,
                )
                Gasto.objects.filter(pk=g.pk).update(
                    creado_en=timezone.make_aware(timezone.datetime.combine(g.fecha, time(10)))
                )
            d = (d + timedelta(days=32)).replace(day=1)
        # --- Huéspedes
        huespedes = []
        for i in range(260 if len(habs) > 10 else 120):
            extranjero = random.random() < 0.15
            huespedes.append(
                Huesped.objects.create(
                    hotel=hotel,
                    nombre=random.choice(NOMBRES),
                    apellido=random.choice(APELLIDOS),
                    tipo_doc="PAS" if extranjero else "DNI",
                    nro_doc=f"{'AB' if extranjero else ''}{20000000 + i * 7919 + len(habs)}",
                    nacionalidad=random.choice(["Chile", "Brasil", "Uruguay", "EE.UU."]) if extranjero else "Argentina",
                    pais_residencia="Chile" if extranjero else "Argentina",
                    telefono=f"+54911{4000000 + i:07d}",
                    email=f"huesped{i}@correo.com",
                    consentimiento_datos=True,
                    consentimiento_whatsapp=random.random() < 0.7,
                )
            )
        # --- Historia de reservas (por habitación, sin superposiciones)
        inicio = hoy - timedelta(days=30 * meses)
        fin = hoy + timedelta(days=60)
        canales = ["directo"] * 3 + ["booking"] * 4 + ["whatsapp"] * 2 + ["telefono", "web"]
        medios = ["efectivo", "debito", "credito", "credito", "transferencia", "billetera"]
        en_casa_hoy = 0
        for hab in habs:
            d = inicio + timedelta(days=random.randint(0, 3))
            while d < fin:
                mes = d.month
                alta = mes in (1, 2, 7, 8) or (mes == 10 and d.day > 8)
                prob = 0.82 if alta else (0.55 if d.weekday() >= 4 else 0.4)
                if random.random() > prob:
                    d += timedelta(days=random.randint(1, 3))
                    continue
                noches = random.choice([1, 2, 2, 3, 3, 4, 5, 7])
                salida = d + timedelta(days=noches)
                if salida > fin:
                    break
                antelacion = random.choice([0, 1, 3, 7, 15, 30, 45, 60, 90])
                creado = timezone.make_aware(timezone.datetime.combine(d - timedelta(days=antelacion), time(12)))
                if creado.date() > hoy:
                    creado = timezone.make_aware(timezone.datetime.combine(hoy - timedelta(days=1), time(12)))
                titular = random.choice(huespedes)
                cant = random.randint(1, hab.tipo.capacidad)
                r = res.crear_reserva(
                    hotel,
                    titular,
                    d,
                    salida,
                    [{"habitacion": hab, "cantidad_huespedes": cant}],
                    canal=random.choice(canales),
                    estado=Reserva.Estado.PENDIENTE,
                    usuario=admin,
                    permitir_pasado=True,
                )
                # Se confirma sin disparar mensajes (datos históricos)
                Reserva.objects.filter(pk=r.pk).update(creado_en=creado, estado=Reserva.Estado.CONFIRMADA)
                r.refresh_from_db()
                azar = random.random()
                det = r.detalles.first()
                if salida <= hoy:
                    if azar < 0.08:
                        res.cancelar(r, random.choice(["Cambio de planes", "Problema de salud", "Viaje cancelado"]))
                    elif azar < 0.12:
                        Reserva.objects.filter(pk=r.pk).update(estado=Reserva.Estado.NO_SHOW)
                        r.detalles.update(vigente=False)
                    else:
                        self._estadia(
                            r,
                            det,
                            hab,
                            d,
                            salida,
                            admin,
                            Estadia,
                            cargar_noches_reserva,
                            Pago,
                            medios,
                            prods,
                            Cargo,
                            finalizada=True,
                        )
                elif d <= hoy < salida:
                    self._estadia(
                        r,
                        det,
                        hab,
                        d,
                        salida,
                        admin,
                        Estadia,
                        cargar_noches_reserva,
                        Pago,
                        medios,
                        prods,
                        Cargo,
                        finalizada=False,
                    )
                    en_casa_hoy += 1
                elif azar < 0.15:
                    Reserva.objects.filter(pk=r.pk).update(estado=Reserva.Estado.PENDIENTE)
                d = salida + timedelta(days=random.randint(0, 2))
        # Estado actual de las habitaciones
        for hab in habs:
            if not Estadia.objects.filter(habitacion=hab, hora_real_salida__isnull=True).exists():
                hab.estado = random.choice(["libre", "libre", "limpia", "sucia"])
                hab.save()
        # --- Mantenimiento: activos, planes e historia de incidencias
        activos = []
        for hab in habs:
            a = Activo.objects.create(
                hotel=hotel,
                nombre="Aire acondicionado split",
                tipo="climatizacion",
                habitacion=hab,
                marca=random.choice(["BGH", "Surrey", "LG"]),
                fecha_instalacion=hoy - timedelta(days=random.randint(400, 2500)),
                umbral_reemplazo=Decimal("350000"),
            )
            activos.append(a)
            PlanPreventivo.objects.create(
                hotel=hotel,
                activo_relacionado=a,
                tarea="Limpieza de filtros",
                frecuencia_dias=90,
                proxima_fecha=hoy + timedelta(days=random.randint(-5, 80)),
            )
        caldera = Activo.objects.create(
            hotel=hotel,
            nombre="Caldera central",
            tipo="termotanque",
            area="Sala de máquinas",
            marca="Peisa",
            umbral_reemplazo=Decimal("900000"),
            fecha_instalacion=hoy - timedelta(days=3000),
        )
        PlanPreventivo.objects.create(
            hotel=hotel,
            activo_relacionado=caldera,
            tarea="Service anual de caldera",
            frecuencia_dias=365,
            proxima_fecha=hoy + timedelta(days=20),
        )
        tecnico = usuarios["mantenimiento"]
        problemáticos = random.sample(activos, min(3, len(activos)))
        for a in activos + [caldera]:
            n = random.randint(3, 6) if a in problemáticos else random.choice([0, 0, 1, 1, 2])
            for _ in range(n):
                cuando = timezone.now() - timedelta(days=random.randint(5, 30 * meses))
                inc = Incidencia.objects.create(
                    hotel=hotel,
                    habitacion=a.habitacion,
                    activo_relacionado=a,
                    titulo=random.choice(["No enfría", "Pierde agua", "Hace ruido", "No enciende"]),
                    categoria="climatizacion",
                    origen=random.choice(["limpieza", "recepcion", "huesped"]),
                    prioridad=random.choice([2, 3]),
                    estado="cerrada",
                    asignada_a=tecnico,
                    reportada_en=cuando,
                    resuelta_en=cuando + timedelta(hours=random.randint(2, 30)),
                    cerrada_en=cuando + timedelta(days=1),
                    solucion="Reparado",
                )
                Mantenimiento.objects.create(
                    hotel=hotel,
                    tipo="correctivo",
                    estado="realizado",
                    incidencia=inc,
                    activo_relacionado=a,
                    habitacion=a.habitacion,
                    tecnico=tecnico,
                    fecha_programada=cuando.date(),
                    fecha_realizado=cuando.date(),
                    descripcion="Reparación",
                    horas=Decimal(random.randint(1, 4)),
                    costo_mano_obra=Decimal(random.randint(15, 60) * 1000),
                    costo_externo=Decimal(random.choice([0, 0, 40000, 90000])),
                )
        # Incidencia abierta actual
        Incidencia.objects.create(
            hotel=hotel,
            habitacion=habs[2],
            titulo="Gotea la canilla del baño",
            categoria="plomeria",
            origen="limpieza",
            prioridad=3,
        )
        # --- Personal
        for u, area, puesto in [
            (usuarios["recepcion"], "recepcion", "Recepcionista"),
            (usuarios["limpieza"], "limpieza", "Mucama"),
            (usuarios["mantenimiento"], "mantenimiento", "Técnico de mantenimiento"),
        ]:
            if hotel.nombre.startswith("Hotel"):
                e = Empleado.objects.create(
                    hotel=hotel,
                    nombre=u.first_name,
                    apellido=u.last_name,
                    dni=str(30000000 + u.pk),
                    puesto=puesto,
                    area=area,
                    usuario=u,
                )
                lunes = hoy - timedelta(days=hoy.weekday())
                for i in range(6):
                    Turno.objects.create(
                        hotel=hotel,
                        empleado=e,
                        fecha=lunes + timedelta(days=i),
                        hora_inicio=time(7 if i % 2 else 15),
                        hora_fin=time(15 if i % 2 else 23),
                    )
        self.stdout.write(
            f"  {hotel}: {len(habs)} habitaciones, {Reserva.objects.filter(hotel=hotel).count()} "
            f"reservas, {en_casa_hoy} alojadas hoy."
        )

    def _estadia(
        self, r, det, hab, entrada, salida, usuario, Estadia, cargar_noches, Pago, medios, prods, Cargo, finalizada
    ):
        from reservas.models import Reserva

        ingreso = timezone.make_aware(timezone.datetime.combine(entrada, time(random.randint(13, 21))))
        egreso = timezone.make_aware(timezone.datetime.combine(salida, time(random.randint(8, 11))))
        Estadia.objects.create(
            hotel=r.hotel,
            reserva=r,
            detalle=det,
            habitacion=hab,
            hora_real_entrada=ingreso,
            hora_real_salida=egreso if finalizada else None,
            registrado_entrada_por=usuario,
        )
        Reserva.objects.filter(pk=r.pk).update(
            estado=Reserva.Estado.FINALIZADA if finalizada else Reserva.Estado.EN_CURSO
        )
        r.refresh_from_db()
        hoy = timezone.localdate()
        cargar_noches(r, hasta=salida if finalizada else hoy + timedelta(days=1))
        if random.random() < 0.35:
            p = random.choice([prods["Agua mineral 500 ml"], prods["Gaseosa lata"], prods["Cerveza artesanal"]])
            Cargo.objects.create(
                hotel=r.hotel,
                reserva=r,
                concepto=p.nombre,
                cantidad=random.randint(1, 4),
                precio_unitario=p.precio_venta,
                origen="consumo",
                producto=p,
                fecha=min(entrada + timedelta(days=1), salida - timedelta(days=1)),
            )
        Cargo.objects.filter(reserva=r).update(creado_en=ingreso)
        if finalizada:
            from caja.services import total_cargos

            total = total_cargos(r)
            p = Pago.objects.create(
                hotel=r.hotel, reserva=r, medio=random.choice(medios), importe=total, fecha=egreso, creado_por=usuario
            )
            Pago.objects.filter(pk=p.pk).update(creado_en=egreso)
        elif random.random() < 0.6:
            Pago.objects.create(
                hotel=r.hotel,
                reserva=r,
                medio="transferencia",
                tipo="sena",
                importe=(r.total * Decimal("0.3")).quantize(Decimal("1")),
                fecha=ingreso,
            )
            hab.estado = "ocupada"
            hab.save()
        else:
            hab.estado = "ocupada"
            hab.save()
