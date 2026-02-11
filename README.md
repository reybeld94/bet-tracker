# Bet Tracker (Local)

## Requisitos

- Python 3.10+
- Windows, macOS o Linux

## Instalación

### 1) Crear y activar entorno virtual

**macOS / Linux**

```bash
python -m venv .venv
source .venv/bin/activate
```

**Windows (PowerShell)**

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

### 2) Instalar dependencias

```bash
pip install -r requirements.txt
```

## Base de datos y migraciones

La base de datos se maneja con Alembic. El flujo estándar es:

```bash
alembic upgrade head
```

Esto crea/actualiza `data/bets.db` a la última versión.

### Crear nuevas migraciones (cuando cambies modelos)

```bash
alembic revision --autogenerate -m "describe change"
alembic upgrade head
```

> Nota: el esquema **no** se crea automáticamente en runtime. Usa Alembic para mantener la DB en sync con los modelos.

## Ejecutar la app

```bash
uvicorn app.main:app --reload
```

Visita: http://127.0.0.1:8000

## Auto-picks (cola + worker)

Variables recomendadas:
- `APP_ADMIN_PASSWORD`: password simple para acceder a `/ui/settings` (requerido).
- `APP_SECRET_KEY`: clave para encriptar el API key (Fernet, base64). Si no existe, se genera una temporal y se loguea.

### Flujo completo

Migraciones:

```bash
alembic upgrade head
```

Ingesta (ya existe):

```bash
python -m app.ingestion.run --today --leagues NBA,NHL
```

Enqueue jobs (opcional/manual):

```bash
python -m app.picks.enqueue --today --leagues NBA,NHL
```

Worker:

```bash
python -m app.picks.worker
```

App:

```bash
uvicorn app.main:app --reload
```

UI:

Abrir http://127.0.0.1:8000/ui/settings?admin_password=TU_PASSWORD para pegar el token y configurar.

## Ingesta automática (programable)

Forma recomendada (un comando):

```bash
python -m app.ingestion.run --today --leagues NBA,NHL
```

También puedes ejecutar por fecha explícita:

```bash
python -m app.ingestion.run --date 2024-01-15 --leagues NBA,NHL
```

### Programar con cron (Linux/macOS)

Ejemplo cada 15 minutos:

```bash
*/15 * * * * /path/to/.venv/bin/python -m app.ingestion.run --today --leagues NBA,NHL >> /path/to/logs/ingestion.log 2>&1
```

### Programar con Windows Task Scheduler

1) Crea una tarea básica.
2) Acción: iniciar un programa.
3) Programa/script: ruta a `python.exe` de tu virtualenv.
4) Argumentos: `-m app.ingestion.run --today --leagues NBA,NHL`.
5) Inicia la tarea cada X minutos (por ejemplo, cada 15).

## Auto-ingesta al levantar la app

La app ejecuta auto-ingesta siempre al iniciar y, tras cada ciclo, encola automáticamente
partidos pendientes cuya hora de inicio esté dentro de la ventana previa de 2 horas (entre inicio-2h e inicio).
Además, al iniciar también levanta el worker en segundo plano para procesar la cola sin
pasos manuales adicionales.

Variables útiles:
- `AUTO_INGEST_LEAGUES`: lista de ligas separadas por coma.
- `AUTO_INGEST_INTERVAL_MINUTES`: cada cuántos minutos se re-sincroniza (mínimo 1).

```bash
AUTO_INGEST_LEAGUES=NBA,NHL \
AUTO_INGEST_INTERVAL_MINUTES=15 \
uvicorn app.main:app --reload
```

## ESPN Scoreboard (endpoint y base URL)

El cliente ESPN usa la variable `ESPN_BASE_URL` (default: `https://site.api.espn.com`).
Si necesitas apuntar a otro host, exporta la variable antes de correr la app.

### Prueba rápida del scoreboard

```bash
python -m app.ingestion.probe --league NBA --date today
```
