# Impulso Hotel — Specs por fases

Nov 4, 2026 · @Nicolás

## 1. Visión y alcance

**Producto:** IMPULSO HOTEL — Hotel Management System. Plataforma web modular y responsive (computadora, tablet, celular) para administrar hostels, hoteles pequeños, medianos, grandes y cadenas en Argentina, comercializada como SaaS bajo la marca Impulso.

**Objetivos del producto**

- Centralizar la operación diaria del hotel (PMS): reservas, recepción, habitaciones y huéspedes.
- Controlar la economía: caja, pagos, facturación electrónica ARCA, gastos y proveedores.
- Digitalizar operaciones internas: limpieza, mantenimiento, compras, inventario y personal.
- Diferenciarse con inteligencia de negocios: dashboards, predicción de demanda, tarifas inteligentes y mantenimiento predictivo.

**Roles de usuario**

| Rol | Uso principal |
| --- | --- |
| Administrador / Gerente | Configuración, tarifas, reportes, caja general |
| Recepción | Reservas, huéspedes, check-in/out, cobros |
| Limpieza | Tareas asignadas, estado de habitaciones |
| Mantenimiento | Incidencias, órdenes preventivas y correctivas |
| Administración / Compras | Gastos, proveedores, compras, inventario |
| Dueño (lectura) | Dashboards e indicadores |
| Superadmin Impulso | Clientes, planes y soporte (Fase 5) |

**Principios de desarrollo**

- Cada fase deja un producto usable en un hotel real; nada se construye “para después”.
- El modelo de datos es multi-hotel desde la Fase 1, aunque la comercialización multi-hotel llega en la Fase 5.
- Seguridad, permisos y auditoría desde el primer día.
- Cada fase se especifica con: objetivo, alcance, modelo de datos, pantallas, API, reglas de negocio, criterios de aceptación y fuera de alcance.

## 2. Arquitectura y convenciones transversales

**Stack**

| Componente | Tecnología |
| --- | --- |
| Backend | Python + Django |
| API | Django REST Framework (versionada en `/api/v1/`, documentada con drf-spectacular) |
| Frontend | Templates Django + HTML5, CSS3, JavaScript y Bootstrap 5 (HTMX opcional para interactividad) |
| Base de datos | PostgreSQL |
| Gráficos | Chart.js |
| Datos e IA | Pandas, NumPy, scikit-learn |
| Tareas programadas | Celery + Redis (o django-q) |
| Reportes | Excel (openpyxl) y PDF (WeasyPrint) |
| Infraestructura | Servidor cloud, entornos dev / staging / producción |
| Versionado y CI | Git, GitHub, GitHub Actions |

**Capas:** Interfaz web → Django + API REST (lógica de negocio, seguridad, permisos) → PostgreSQL (datos operativos) → IA y análisis (predicciones, alertas) → Integraciones externas (ARCA, pasarelas de pago, Booking.com, WhatsApp).

**Apps Django propuestas:** `core` (hoteles, usuarios, roles, auditoría), `habitaciones`, `huespedes`, `reservas`, `recepcion`, `caja`, `facturacion`, `inventario`, `compras`, `limpieza`, `mantenimiento`, `personal`, `notificaciones`, `bi`, `integraciones`.

**Convenciones obligatorias**

- **Multi-hotel:** todo modelo operativo tiene FK a `hotel`. Un middleware fija el hotel activo del usuario y los querysets filtran siempre por él. Propuesta inicial: tenant por columna (`hotel_id`), un solo esquema.
- **Modelo base abstracto:** `hotel`, `creado_en`, `actualizado_en`, `creado_por`, `activo` (borrado lógico, nunca físico en datos operativos).
- **Permisos:** roles como grupos de Django con permisos por módulo y acción; en la API, permission classes de DRF. Ejemplo: limpieza no ve precios ni caja general.
- **Auditoría:** tabla `auditoria` (usuario, acción, modelo, objeto\_id, valores antes/después en JSON, IP, fecha), alimentada por señales o django-simple-history.
- **Dinero:** `DecimalField(12, 2)`, moneda ARS por defecto y campo `moneda` para USD con tipo de cambio registrado.
- **Fechas:** `USE_TZ = True`, zona `America/Argentina/Buenos_Aires`.
- **Calidad:** pytest-django con cobertura mínima del 70 % en lógica de negocio, black + flake8, CI en cada pull request, secretos en `.env`, backups diarios de PostgreSQL con prueba de restauración.

## 3. Fase 1 — MVP: gestión hotelera básica

**Objetivo:** que un hotel piloto pueda manejar reservas y recepción sin planillas ni cuadernos.

### Alcance funcional

1. **Usuarios y permisos:** login, logout, recuperación de contraseña, alta/baja/modificación de usuarios, asignación de rol, bloqueo tras intentos fallidos.
2. **Hotel:** datos del establecimiento (nombre, CUIT, dirección, contacto), horario estándar de check-in/out, política de cancelación.
3. **Habitaciones:** tipos (individual, doble, triple, suite; capacidad, camas, amenities) y habitaciones (número, piso, tipo, estado).
4. **Tarifas y temporadas:** precio por noche según tipo de habitación y temporada (fecha desde/hasta).
5. **Huéspedes:** datos personales (nombre, tipo y número de documento, nacionalidad, email, teléfono, fecha de nacimiento, dirección), historial de estadías, preferencias, búsqueda y detección de duplicados por documento.
6. **Reservas:** crear, modificar y cancelar; una o varias habitaciones por reserva; canal de origen (directo, teléfono, WhatsApp, Booking.com cargado a mano); seña informativa; cálculo automático del total.
7. **Check-in y check-out:** asignación de habitación, registro de acompañantes, hora real de entrada y salida; walk-in (reserva + check-in en un paso).
8. **Calendario de disponibilidad (rack):** grilla habitaciones × días, crear reserva desde una celda libre.
9. **Mapa visual de habitaciones (versión básica):** vista por piso con colores por estado, actualizada en tiempo real.

### Estados

- **Reserva:** pendiente → confirmada → en curso (check-in) → finalizada (check-out); o cancelada / no-show.
- **Habitación:** libre, reservada, ocupada, sucia, limpia, fuera de servicio.

### Modelo de datos

| Tabla | Campos clave |
| --- | --- |
| usuarios / roles | usuario, email, rol, hoteles permitidos |
| hoteles | nombre, cuit, dirección, hora\_checkin, hora\_checkout |
| tipos\_habitacion | nombre, capacidad, camas, amenities |
| habitaciones | número, piso, tipo, estado |
| tarifas | tipo\_habitacion, temporada, fecha\_desde, fecha\_hasta, precio\_noche |
| huespedes | nombre, apellido, tipo\_doc, nro\_doc, nacionalidad, contacto, preferencias |
| reservas | titular, fecha\_entrada, fecha\_salida, estado, canal, total, seña |
| detalle\_reservas | reserva, habitación, tarifa aplicada, cantidad de huéspedes |
| checkin\_checkout | reserva, habitación, hora\_real\_entrada, hora\_real\_salida, acompañantes |
| auditoria | usuario, acción, modelo, objeto\_id, antes, después, fecha |

### Reglas de negocio

- No se permite superposición de fechas en la misma habitación (la fecha de salida es exclusiva). Se valida en la base con un `ExclusionConstraint` de PostgreSQL sobre un rango de fechas, además de la validación en el formulario.
- La cantidad de huéspedes no puede superar la capacidad del tipo de habitación.
- Una habitación fuera de servicio no es reservable en ese período.
- El check-in exige reserva confirmada en la fecha (con tolerancia configurable). Al hacer check-out, la habitación pasa a “sucia”.
- Toda cancelación registra motivo y usuario.
- Una tarea diaria marca como no-show las reservas sin check-in pasada la hora límite.

### Pantallas

Login · Panel de recepción (llegadas y salidas del día, ocupación actual) · Rack/calendario · Mapa de habitaciones · Ficha de reserva · Ficha de huésped · Configuración (habitaciones, tipos, tarifas, usuarios).

### API

`/api/v1/habitaciones/` · `/api/v1/disponibilidad/?desde=&hasta=&tipo=` · `/api/v1/reservas/` con acciones `checkin`, `checkout` y `cancelar` · `/api/v1/huespedes/`.

### Permisos de la fase

| Rol | Puede |
| --- | --- |
| Administrador | Todo |
| Recepción | Reservas, huéspedes, check-in/out, ver tarifas |
| Limpieza | Ver mapa, cambiar sucia → limpia |
| Mantenimiento | Marcar o liberar “fuera de servicio” |

### Criterios de aceptación

- Una reserva de dos habitaciones se carga en menos de dos minutos.
- Un intento de sobre-reserva devuelve un error claro, tanto por la web como por la API.
- Todo cambio en reservas y tarifas queda registrado en auditoría.
- Todas las pantallas se usan cómodamente en un celular de 360 px de ancho.
- Tests automatizados de disponibilidad, transiciones de estado y permisos.

**Fuera de alcance:** cobros reales, facturación, channel manager, WhatsApp.

**Entregable:** sistema en staging operando con un hotel piloto.

## 4. Fase 2 — Administración y economía

**Objetivo:** controlar todo el dinero del hotel: cobros, caja, facturación electrónica, gastos y stock básico.

### Alcance funcional

1. **Cuenta del huésped:** cargos automáticos por noche, extras y consumos cargados a la habitación (incluido restaurante, de forma manual); saldo en tiempo real.
2. **Pagos:** efectivo, débito, crédito, transferencia y billeteras virtuales; señas, pagos parciales y devoluciones; ARS y USD con tipo de cambio registrado.
3. **Caja:** apertura con monto inicial, movimientos, cierre con arqueo (esperado vs. contado y diferencia); caja por turno o usuario; caja general solo para administración.
4. **Facturación electrónica:** comprobantes según la condición fiscal del hotel (A, B o C) y notas de crédito, integradas con ARCA mediante WSAA (certificado digital) y WSFEv1 para obtener el CAE. Se trabaja primero en homologación.
5. **Gastos:** egresos con categoría, medio de pago y comprobante adjunto.
6. **Proveedores:** CUIT, condición frente al IVA, rubro y contacto.
7. **Inventario básico:** productos e insumos, stock por depósito, movimientos de entrada y salida, stock mínimo.
8. **Informes económicos:** ingresos por día y medio de pago, cierres de caja, cuentas pendientes, IVA ventas; exportables a Excel y PDF.

### Modelo de datos (nuevas tablas)

| Tabla | Campos clave |
| --- | --- |
| cargos | reserva, concepto, fecha, importe, origen |
| pagos | reserva, medio, importe, moneda, tipo\_cambio, tipo (pago / seña / devolución) |
| cajas | usuario, apertura, cierre, monto\_inicial, monto\_contado, diferencia |
| movimientos\_caja | caja, tipo (ingreso / egreso), importe, concepto, referencia |
| puntos\_venta | número, tipos de comprobante habilitados |
| facturas / items\_factura | tipo, punto de venta, número, CAE, vencimiento CAE, receptor, totales e IVA |
| gastos | categoría, proveedor, importe, comprobante |
| proveedores | razón social, CUIT, condición IVA, rubro |
| productos / inventario | producto, depósito, cantidad, tipo de movimiento, stock mínimo |

### Reglas de negocio

- No hay check-out con saldo pendiente, salvo autorización o cuenta corriente de empresa.
- Todo pago en efectivo genera un movimiento en la caja abierta del usuario; una caja cerrada no admite movimientos.
- Una factura con CAE es inmutable: se corrige solo con nota de crédito.
- La numeración se sincroniza con ARCA (último comprobante autorizado). Si ARCA no responde, el comprobante queda en cola con reintentos y alerta, sin bloquear el check-out.
- El stock no puede quedar negativo (configurable por hotel).

### Criterios de aceptación

- Se emite una factura B en homologación y se obtiene el CAE.
- El arqueo de un turno de prueba cuadra al centavo con los movimientos registrados.
- El cierre de caja se exporta a PDF y Excel.

**Fuera de alcance:** cobros online con pasarela, órdenes de compra (Fase 3).

## 5. Fase 3 — Operaciones

**Objetivo:** digitalizar el trabajo interno del hotel y conectarlo con el estado de las habitaciones.

### Alcance funcional

1. **Limpieza:** tareas generadas cada día (salida → limpieza completa; ocupada → repaso), asignación por mucama, vista móvil con iniciar/terminar, checklist por tipo de habitación, reporte de incidencias y objetos olvidados. Al terminar, la habitación pasa a “limpia” en el mapa.
2. **Mantenimiento correctivo:** incidencias con origen (limpieza, recepción, huésped), categoría (plomería, eléctrica, climatización, etc.), prioridad, fotos, estados (abierta → asignada → en curso → resuelta → cerrada), repuestos usados (descuentan stock), costo y tiempo de resolución.
3. **Mantenimiento preventivo:** registro de activos y equipos por habitación o área, planes con frecuencia que generan órdenes automáticas. Punto de partida: la estructura de datos del proyecto previo de digitalización de incidencias, inventario, compras y mantenimiento hotelero.
4. **Compras:** solicitud → orden de compra → recepción (ingresa stock) → factura del proveedor → pago (egreso); comparación de precios por proveedor.
5. **Personal:** empleados (puesto, área, contacto), turnos y horarios, permisos y licencias, asignación de tareas; vínculo opcional con un usuario del sistema.
6. **Notificaciones:** internas (campana) y por email; WhatsApp Business (API oficial, plantillas aprobadas, consentimiento del huésped) para confirmación de reserva, recordatorio previo, información de ingreso y encuesta posterior a la estadía.

### Modelo de datos (nuevas tablas)

| Tabla | Campos clave |
| --- | --- |
| tareas\_limpieza | habitación, fecha, tipo, asignada\_a, estado, inicio, fin |
| incidencias | habitación / activo, origen, categoría, prioridad, estado, bloqueante |
| activos | nombre, tipo, ubicación, marca, fecha de instalación |
| mantenimientos | incidencia o plan, técnico, repuestos, costo, horas |
| planes\_preventivos | activo, tarea, frecuencia, próxima fecha |
| solicitudes\_compra / compras / items\_compra | producto, cantidad, proveedor, precio, estado |
| empleados / turnos / licencias | empleado, fechas, horario, tipo |
| notificaciones / plantillas\_mensaje | canal, destinatario, plantilla, estado de envío |

### Reglas de negocio

- Una incidencia marcada como bloqueante pone la habitación fuera de servicio hasta su cierre.
- Recepción recibe una advertencia si intenta hacer check-in en una habitación sucia.
- El costo de cada mantenimiento se imputa a la habitación y al activo (insumo clave para la Fase 4).
- Ningún mensaje de WhatsApp sale sin consentimiento registrado del huésped.

### Criterios de aceptación

- Una mucama completa su jornada solo desde el celular.
- Una incidencia reportada aparece al técnico en menos de un minuto.
- La recepción de una compra actualiza el stock automáticamente.
- El huésped recibe la confirmación por WhatsApp al confirmarse la reserva.

## 6. Fase 4 — Inteligencia de negocios

**Objetivo:** convertir los datos acumulados en decisiones: indicadores, reportes, predicciones y alertas.

### Dashboard gerencial: indicadores

| Indicador | Cálculo |
| --- | --- |
| Ocupación % | noches ocupadas / noches disponibles |
| ADR (tarifa promedio) | ingresos por alojamiento / noches vendidas |
| RevPAR | ingresos por alojamiento / noches disponibles |
| Estadía promedio | noches vendidas / reservas |
| Antelación promedio | fecha de entrada − fecha de creación de la reserva |
| Tasa de cancelación y no-show | canceladas o no-show / reservas totales |
| Ingresos por canal y tipo | agrupado por canal de origen y tipo de habitación |
| Costo de mantenimiento | por habitación, activo y mes |
| Rentabilidad | ingresos − gastos operativos, por período |

Vistas diaria, mensual y anual, con comparación contra el mismo período del año anterior.

### Reportes

Exportación a Excel y PDF; envío programado por email (por ejemplo, resumen semanal al dueño).

### Análisis predictivo

- **Predicción de demanda:** primero una línea base (promedio estacional por día de la semana); luego un modelo de ML con día de la semana, temporada, feriados argentinos y reservas ya en cartera. Requiere idealmente 12 meses de historia; sin ella, se usan reglas.
- **Tarifas inteligentes:** recomendación de precio según ocupación proyectada, antelación, temporada y demanda, dentro de mínimos y máximos definidos por el hotel. Siempre la aprueba una persona.
- **Mantenimiento predictivo:** frecuencia de fallas y tiempo medio entre fallas por activo y habitación, ranking de riesgo, alerta de reemplazo cuando el costo acumulado supera un umbral.
- **Alertas inteligentes:** ocupación proyectada baja, diferencias de caja, stock bajo, incidencias repetidas en la misma habitación.

### Implementación

Procesos nocturnos con Celery que calculan con Pandas, NumPy y scikit-learn y guardan resultados en tablas `predicciones` y `alertas`; gráficos con Chart.js.

### Criterios de aceptación

- Los indicadores coinciden con un cálculo manual sobre una muestra de datos.
- Cada modelo reporta su error (MAPE) frente a la línea base y solo se activa si la mejora.
- Cada recomendación de precio o alerta muestra en qué datos se basa.

## 7. Fase 5 — Comercialización SaaS

**Objetivo:** convertir el sistema en un producto vendible de Impulso, con alta de clientes, suscripciones y soporte.

### Alcance funcional

1. **Multi-hotel:** una empresa cliente con varios hoteles, usuarios con acceso a más de uno y consolidado de cadena.
2. **Panel de administración general (Impulso):** alta de clientes, plan y estado de suscripción, métricas de uso, acceso de soporte auditado.
3. **Suscripciones mensuales:** planes por cantidad de habitaciones y módulos, período de prueba, cobro recurrente con una pasarela local, modo solo lectura ante falta de pago.
4. **Onboarding:** asistente de configuración inicial (hotel, habitaciones, tarifas, usuarios) e importación de huéspedes y reservas desde Excel.
5. **Canales de venta:** conexión con Booking.com y otros canales mediante un channel manager o proveedor autorizado; motor de reservas propio para la web del hotel como candidato.
6. **Soporte y actualizaciones:** mesa de ayuda, base de conocimiento, historial de cambios, actualizaciones sin cortes de servicio.
7. **Legal:** términos y condiciones, contrato de tratamiento de datos con cada hotel.

### Planes comerciales (propuesta a validar)

| Plan | Público objetivo | Incluye |
| --- | --- | --- |
| Inicial | Hostels y hoteles pequeños | Fases 1 y 2, un hotel |
| Profesional | Hoteles medianos | + Operaciones, dashboards y WhatsApp |
| Empresarial | Hoteles grandes y cadenas | + Multi-hotel, IA, API y soporte prioritario |

Los límites de habitaciones y los precios de cada plan se definen tras estudiar a los competidores (Cloudbeds, Mews, Little Hotelier, OPERA Cloud y, en Argentina, Anfy, Arion PMS, Axis PMS, CQR, Lodgy y Pxsol).

### Criterios de aceptación

- Un hotel nuevo se da de alta y queda operativo sin intervención técnica.
- Los datos de un cliente nunca son visibles para otro (tests de aislamiento).
- La suspensión por falta de pago no borra datos.

## 8. Requisitos de Argentina y decisiones abiertas

### Requisitos que aplican desde la Fase 1

- **Protección de datos (Ley 25.326):** finalidad informada y consentimiento del huésped, derechos de acceso, rectificación y supresión, inscripción de la base ante la autoridad de control y medidas de seguridad.
- **ARCA:** validar tipos de comprobante, requisitos y servicios web antes de implementar la facturación; contemplar la facturación a turistas extranjeros cuando corresponda.
- **Seguridad:** contraseñas con hash (el estándar de Django), HTTPS, doble factor para administradores, backups, auditoría y permisos por rol.
- **Pagos:** tarjetas, transferencias y billeteras virtuales.
- **Registro de huéspedes:** verificar si la provincia o el municipio del hotel piloto exigen un registro o informe de pasajeros.

### Decisiones abiertas

1. Multi-hotel por columna `hotel_id` (propuesto) o por esquema de PostgreSQL.
2. Frontend con templates y Bootstrap (propuesto) o una SPA separada.
3. Proveedor cloud y región.
4. Pasarela de pagos y de suscripciones.
5. Channel manager o proveedor autorizado para Booking.com.
6. Hotel piloto para validar la Fase 1.
7. Qué partes del proyecto previo de mantenimiento se reutilizan tal cual.

### Próximo paso

Convertir la Fase 1 en un backlog de historias de usuario con criterios de aceptación y arrancar por `core` (hoteles, usuarios, roles y auditoría).
