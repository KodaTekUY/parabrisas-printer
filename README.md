# Parabrisas Printer

Agente local para la Xprinter XP-470L. Consulta la cola del sistema por HTTPS,
convierte documentos estructurados a TSPL y los envía a la impresora por TCP.

El agente no accede a PostgreSQL y no recibe órdenes desde el navegador.

## Configuración

1. Reservar una IP para la impresora en el router.
2. Copiar `.env.example` como `.env`.
3. Usar en `PRINT_AGENT_API_KEY` el mismo secreto configurado en la aplicación.
4. Configurar `SYSTEM_API_URL` con la URL pública HTTPS del sistema.
5. Configurar `PRINTER_HOST` con la IP privada de la XP-470L.

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

`/health/printer` confirma que el puerto TCP acepta conexiones; no puede
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
- Un único worker procesa una impresión por vez.
- La aplicación reserva cada trabajo mediante lease y máximo de intentos.
- Si la impresora está apagada, el agente reporta el error y el servidor agenda
  el siguiente intento.
- Las rutas de impresión del navegador siguen disponibles como respaldo.

Antes de habilitarlo en producción se debe probar físicamente el `CODEPAGE
UTF-8`, la alimentación continua (`GAP 0`) y el ancho real imprimible. Si el
firmware no acepta UTF-8, ajustar `PRINTER_CODEPAGE` y `PRINTER_ENCODING`.
