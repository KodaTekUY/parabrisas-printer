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

## Logs persistentes

El agente usa logging nativo de Python, sin dependencias adicionales. Al iniciar con
`python -m app` (también es el comando de Docker), captura desde el arranque los mensajes
propios y de Uvicorn. Usar un solo proceso servidor por archivo de logs.

- Los archivos quedan en la carpeta `logs` junto a `compose.yml` en la PC anfitriona.
  El montaje `./logs:/app/logs` conserva el historial al reiniciar o recrear el contenedor.
- El archivo activo es `printer-agent.log`; los históricos llevan sufijo `.AAAA-MM-DD`.
- Se rota a medianoche, con el primer evento del nuevo día. En Docker se usa
  `TZ=America/Montevideo`; al ejecutar Python directamente se usa la zona horaria del sistema.
- `LOG_RETENTION_FILES=14` conserva el activo y hasta 13 históricos. Es retención por
  cantidad de archivos diarios, no por antigüedad exacta durante días sin actividad.
  La rotación diaria no impone un límite de tamaño a cada archivo.
- `LOG_LEVEL=INFO` admite DEBUG, INFO, WARNING, ERROR y CRITICAL.
  `LOG_DIR=logs` define la carpeta en ejecución directa; Compose fija `/app/logs` dentro del contenedor.
- Los archivos son texto UTF-8 con fecha y offset horario, evento, agente,
  impresora, IP/puerto, trabajo, intento, etapa y duración cuando corresponde.
  No se registra el contenido del ticket, credenciales ni argumentos de excepciones;
  los errores incluyen tipo, códigos disponibles y frames del traceback.

Cada respuesta **204 No Content** se registra a nivel INFO. Si el último registro
persistido también era un No Content, se reemplaza esa línea por la respuesta más
reciente, incluyendo su hora, impresora y duración. Esta regla es global entre
impresoras. Un trabajo, error u otro evento corta la secuencia: sus registros nunca
se reemplazan. Al cambiar de día se inicia una nueva línea en el archivo nuevo.

La consola de Docker no permite sobrescribir entradas capturadas: muestra el primer
No Content de cada secuencia y omite las repeticiones consecutivas. El archivo mantiene
la **última** respuesta actualizada. Los mensajes automáticos repetidos de HTTPX se
sustituyen por estos eventos propios, también en DEBUG.

Se distinguen `job_claimed`, `tcp_connected`, `tcp_sent` y `result_confirmed`.
Un envío TCP terminado **no confirma que haya salido papel**. Si el reporte al
servidor falla después del envío, queda identificado por separado.

Si falla la escritura en disco, el agente continúa imprimiendo y deja una advertencia
en consola. Los fallos de escritura se reintentan con los eventos siguientes y se
informa su recuperación; la advertencia no se repite en cada consulta. Los errores
que impidan construir el handler al arrancar requieren corregir el acceso y reiniciar.
Docker conserva además su propia salida con un máximo de tres archivos de 10 MiB.

Después de actualizar el código, recrear el servicio para aplicar el montaje y los
límites de Docker. No se importan automáticamente logs de contenedores anteriores.
Comandos compatibles con **CMD**:

```bat
docker compose up -d --build printer-agent
notepad logs\printer-agent.log
findstr /C:"printerId=facturacion" logs\printer-agent.log*
docker compose logs --tail 100 printer-agent
```

## Desarrollo

```bash
python -m venv .venv
source .venv/Scripts/activate
pip install -e '.[dev]'
python -m app
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
