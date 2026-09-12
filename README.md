# Parabrisas Printer

Agente local multiimpresora para la Xprinter XP-470L. Consulta las colas del sistema por HTTPS,
convierte documentos estructurados a TSPL y los envía al destino indicado por TCP.

El agente no accede a PostgreSQL y no recibe órdenes desde el navegador.

## Configuración

1. Reservar una IP para cada impresora en el router y conectarlas por LAN.
2. Copiar `.env.example` como `.env`.
3. Usar en `PRINT_AGENT_API_KEY` el mismo secreto configurado en la aplicación.
4. Configurar `SYSTEM_API_URL` con la URL pública HTTPS del sistema.
5. Reemplazar `PRINTER_HOST` por `PRINTERS`, una lista JSON de nombres e IP. No hay fallback a la configuración antigua.

```dotenv
PRINTERS='[{"name":"Mostrador 1","ip":"192.168.1.51"},{"name":"Mostrador 2","ip":"192.168.1.52"},{"name":"Facturación","ip":"192.168.1.50"},{"name":"Pista","ip":"192.168.1.53"}]'
PRINTER_PORT=9100
```

Las IP son ejemplos: reemplazarlas por las reales. Los cuatro nombres deben escribirse exactamente así, incluida la tilde de Facturación. El `.env` debe guardarse en UTF-8. No se permiten nombres ni IP repetidos. Se puede configurar un subconjunto; los destinos no configurados permanecen en la cola del sistema sin ser reclamados. Todas las impresoras usan los parámetros TSPL/DPI actuales. Las IP no se guardan en la aplicación web.

La aplicación principal necesita:

```env
PRINT_AGENT_API_KEY=la-misma-clave-larga
```

## Docker

```bash
docker compose up -d --build
docker compose logs -f
```

Health checks locales:

```bash
curl http://localhost:8000/health
curl http://localhost:8000/health/printer
```

`/health` lista los destinos configurados y `/health/printer` informa conectividad por impresora (consulta en paralelo). Confirma que el puerto TCP acepta conexiones; no puede
garantizar que el papel haya salido físicamente.

## Desarrollo

```bash
python -m venv .venv
source .venv/Scripts/activate
pip install -e '.[dev]'
uvicorn app.main:app --reload
pytest
```

## Operación

- Polling predeterminado: 2 segundos.
- Un worker por impresora procesa una impresión por vez. Los workers de distintos destinos trabajan independientemente.
- Claim y resultado incluyen `printerId`. La respuesta debe coincidir con el destino solicitado; un error de enrutamiento nunca se imprime ni se redirige a otra impresora.
- La aplicación reserva cada trabajo mediante lease y máximo de intentos.
- Si la impresora está apagada, el agente reporta el error y el servidor agenda
  el siguiente intento.
- Las rutas de impresión del navegador siguen disponibles como respaldo.

## Actualizar desde la versión de una sola impresora

1. Detener el agente: `docker compose stop printer-agent` (dejar finalizar cualquier impresión activa antes del cambio).
2. Desplegar la aplicación principal y aplicar `pnpm db:migrate` contra su base. La migración 0043 asigna Facturación a los registros existentes, incluidos los pendientes, sin alterar su estado. No establece preferencias a usuarios.
3. Actualizar este proyecto y reemplazar `PRINTER_HOST` por `PRINTERS` en su `.env`. La IP de la impresora anterior debe ser la entrada Facturación.
4. Recrear el agente: `docker compose up -d --build printer-agent`.
5. Revisar ambos health checks y `docker compose logs -f printer-agent`. Probar físicamente un ticket en cada destino.

Los clientes antiguos sin `printerId` son rechazados por la API nueva; actualizar ambos proyectos de manera coordinada.

La preferencia se guarda en la cuenta del usuario, no en esta computadora. Al imprimir sin preferencia aparece un selector con Recordar activado. Cancelar deja la orden o el cobro guardado sin imprimir; cambiar la preferencia no imprime solicitudes antiguas sin destino. Cada nueva OT produce una solicitud automática y la confirmación de cobro puede generar otro ticket según su política.

La aplicación informa “Impresión encolada”. La aceptación por TCP no garantiza salida física; si se corta la conexión con el servidor después del envío pero antes del acuse, un reintento puede repetir el ticket. No hay garantía de impresión física exactamente una vez.

Pruebas focalizadas del cambio (sin conectar impresoras):

```bash
python -m pytest tests/test_config.py tests/test_api_client.py tests/test_worker.py tests/test_printer.py tests/test_health.py -q
```

Antes de habilitarlo en producción se debe probar físicamente el `CODEPAGE
UTF-8`, la alimentación continua (`GAP 0`) y el ancho real imprimible. Si el
firmware no acepta UTF-8, ajustar `PRINTER_CODEPAGE` y `PRINTER_ENCODING`.
