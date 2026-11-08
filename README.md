# IMPULSO HOTEL — Hotel Management System

Plataforma web modular y responsive para administrar hostels, hoteles y cadenas en Argentina, comercializable
como SaaS. Implementa las cinco fases de `Impulso Hotel — Specs por fases.md`.

**Stack:** Python 3.12 · Django 5.1 · Django REST Framework (`/api/v1/`, documentada con drf-spectacular) ·
PostgreSQL 16 · Bootstrap 5 + HTMX · Chart.js · Pandas / NumPy / scikit-learn · Celery + Redis ·
openpyxl (Excel) · WeasyPrint (PDF).

## Puesta en marcha (desarrollo)

```bash
docker run -d --name impulso-pg -e POSTGRES_USER=impulso -e POSTGRES_PASSWORD=impulso \
  -e POSTGRES_DB=impulso -p 5433:5432 postgres:16-alpine
python3 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
cp .env.example .env
.venv/bin/python manage.py migrate
.venv/bin/python manage.py cargar_demo        # datos de demostración (~3 min)
.venv/bin/python manage.py runserver
```

Abrir http://localhost:8000 · API: http://localhost:8000/api/v1/ · Swagger: http://localhost:8000/api/v1/docs/

**Usuarios demo** (contraseña `Impulso2026!`): `admin`, `recepcion`, `limpieza`, `mantenimiento`, `compras`,
`dueno` y `soporte` (superadmin de Impulso). La demo crea la empresa «Hoteles del Sur S.A.» con dos hoteles,
14 meses de historia (≈ 2.270 reservas), cargos, pagos, gastos, activos, incidencias y planes preventivos.

Con Docker completo (web + worker + beat + PostgreSQL + Redis): `docker compose up --build`.

Tareas programadas (Celery beat, ver `CELERY_BEAT_SCHEDULE`): no-show, cargo de noches, tareas de limpieza,
órdenes preventivas, reintento de ARCA, WhatsApp programados, proceso nocturno de BI, reportes por email y
cobro de suscripciones. En desarrollo pueden ejecutarse a mano desde `manage.py shell`.

## Estructura

| App | Contenido |
| --- | --- |
| `core` | Hoteles, empresas, usuarios, roles (grupos), auditoría, middleware multi-hotel, 2FA, CRUD genérico, exportación Excel/PDF |
| `habitaciones` | Tipos, habitaciones, tarifas por temporada, períodos fuera de servicio, cotización y disponibilidad |
| `huespedes` | Ficha, historial, detección de duplicados, derechos de acceso y supresión (Ley 25.326) |
| `reservas` | Reservas multi-habitación, check-in/out, walk-in, no-show; `ExclusionConstraint` contra sobre-reservas |
| `recepcion` | Panel del día, rack/calendario, mapa de habitaciones en tiempo real |
| `caja` | Cuenta del huésped, pagos ARS/USD, cajas con arqueo, cuentas corrientes, informes económicos |
| `facturacion` | Facturas A/B/C y notas de crédito, cliente ARCA (WSAA + WSFEv1), cola con reintentos, QR, libro IVA |
| `inventario` | Productos, depósitos, stock y movimientos |
| `compras` | Proveedores, gastos, solicitud → orden → recepción → factura → pago, comparación de precios |
| `limpieza` | Tareas diarias, vista móvil con checklist, objetos olvidados |
| `mantenimiento` | Incidencias (estados, fotos, bloqueantes), activos, planes preventivos, repuestos y costos |
| `personal` | Empleados, turnos, licencias, planilla semanal |
| `notificaciones` | Campana interna, email, WhatsApp Business con plantillas y consentimiento |
| `bi` | Indicadores, comparación interanual, predicción de demanda, tarifas inteligentes, mantenimiento predictivo, alertas, reportes programados |
| `integraciones` | WhatsApp Cloud API, interfaz de channel manager, pasarela de suscripciones |
| `saas` | Planes, suscripciones, solo lectura por falta de pago, onboarding, importación Excel, panel Impulso, soporte, base de conocimiento, legales |

## Calidad

```bash
.venv/bin/pytest                      # 77 tests
.venv/bin/pytest --cov=reservas.services --cov=caja.services --cov=facturacion.services ...  # ver CI
.venv/bin/black --check . && .venv/bin/flake8
```

Cobertura de la lógica de negocio (servicios): **85 %** (mínimo exigido 70 %). CI en `.github/workflows/ci.yml`
(black, flake8, migraciones, tests con cobertura mínima). Backups: `scripts/backup.sh` (pg_dump diario con
restauración de prueba).

## Criterios de aceptación

| Fase | Criterio | Estado |
| --- | --- | --- |
| 1 | Sobre-reserva devuelve error claro por web y API | Test `test_sobre_reserva_por_api/web…`; además `ExclusionConstraint` en PostgreSQL |
| 1 | Cambios en reservas y tarifas quedan auditados | Test `test_auditoria_de_reservas_y_tarifas` (antes/después, usuario, IP) |
| 1 | Tests de disponibilidad, estados y permisos | `tests/test_disponibilidad.py`, `test_estados.py`, `test_permisos_api.py` |
| 1 | Reserva de dos habitaciones en < 2 min | Formulario de una sola pantalla con disponibilidad en vivo y detección del huésped por documento |
| 1 | Uso cómodo en celular de 360 px | Bootstrap responsive + menú lateral plegable; **no se verificó visualmente en un dispositivo** |
| 2 | Factura B con CAE en homologación | Cliente WSAA/WSFEv1 implementado; probado en modo **simulado**. Requiere certificado de homologación (ver abajo) |
| 2 | Arqueo cuadra al centavo | Test `test_arqueo_cuadra_al_centavo` (ARS y USD) |
| 2 | Cierre de caja a PDF y Excel | Test `test_exportaciones_cierre` |
| 3 | Mucama completa su jornada desde el celular | Test `test_jornada_de_mucama_desde_el_celular` |
| 3 | Incidencia visible al técnico en < 1 min | Notificación inmediata + campana con refresco cada 30 s |
| 3 | Recepción de compra actualiza stock | Test `test_circuito_de_compras_actualiza_stock` |
| 3 | Confirmación por WhatsApp | Test `test_whatsapp_requiere_consentimiento` (modo simulado; real requiere cuenta de Meta) |
| 4 | Indicadores = cálculo manual | Test `test_kpis_coinciden_con_calculo_manual` |
| 4 | El modelo reporta MAPE y solo se activa si mejora | Test `test_ml_solo_se_activa_si_mejora_la_linea_base` |
| 4 | Recomendaciones y alertas muestran sus datos | Campos `fundamento` / `datos_base`, visibles en pantalla |
| 5 | Alta de hotel sin intervención técnica | Test `test_alta_autoservicio_operativa` (registro + onboarding) |
| 5 | Datos de un cliente nunca visibles para otro | Test `test_aislamiento_entre_clientes` (web y API) |
| 5 | Suspensión por falta de pago no borra datos | Test `test_suspension_solo_lectura_sin_borrar_datos` |

## Integraciones externas: qué falta para pasar a real

Todas funcionan en modo `simulado` y están listas para conectarse configurando `.env`:

- **ARCA**: generar certificado de homologación (WSASS), asociarlo al servicio `wsfe`, crear el punto de venta
  y setear `ARCA_MODO=homologacion`, `ARCA_CUIT`, `ARCA_CERT`, `ARCA_KEY`. Los comprobantes simulados se marcan
  como «sin validez fiscal». Validar con el contador: tipos de comprobante, tratamiento de turistas extranjeros
  (opción de alojamiento exento incluida) y límite para identificar consumidores finales.
- **WhatsApp**: cuenta de WhatsApp Business Cloud API, plantillas aprobadas por Meta (cargar su nombre en
  Configuración → Plantillas) y `WHATSAPP_MODO=real`, `WHATSAPP_TOKEN`, `WHATSAPP_PHONE_ID`.
- **Pasarela de suscripciones** y **channel manager / Booking.com**: interfaces definidas en `integraciones/`;
  falta elegir proveedor (decisiones abiertas 4 y 5).
- **Feriados**: `bi/feriados.py` tiene los nacionales hasta 2027; los trasladables deben actualizarse cada año.
- **Legales**: términos y contrato de datos cargados como **borradores** a validar con asesoría legal.
- **Precios de los planes**: en $ 0 hasta completar el estudio de competidores.

## Decisiones tomadas (sobre las abiertas de la spec)

1. Multi-hotel por columna `hotel_id` (propuesta de la spec).
2. Frontend con templates + Bootstrap + HTMX (propuesta de la spec).
3. Proveedor cloud, pasarela, channel manager, hotel piloto y reutilización del proyecto previo de
   mantenimiento: quedan abiertas (no se conocen); el código no depende de ellas.
# Impulso_Hotel
