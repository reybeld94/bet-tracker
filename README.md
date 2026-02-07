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
