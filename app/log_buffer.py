"""In-memory circular buffer log handler for the dashboard Activity Log."""

from __future__ import annotations

import logging
from collections import deque
from datetime import datetime, timezone
from dataclasses import dataclass, asdict


@dataclass(frozen=True)
class LogEntry:
    timestamp: str
    level: str
    logger: str
    message: str


class BufferHandler(logging.Handler):
    """Stores the last *maxlen* log records in a deque for dashboard display."""

    def __init__(self, maxlen: int = 200) -> None:
        super().__init__()
        self._buffer: deque[LogEntry] = deque(maxlen=maxlen)

    def emit(self, record: logging.LogRecord) -> None:
        try:
            entry = LogEntry(
                timestamp=datetime.fromtimestamp(record.created, tz=timezone.utc)
                .strftime("%Y-%m-%d %H:%M:%S UTC"),
                level=record.levelname,
                logger=record.name,
                message=self.format(record),
            )
            self._buffer.append(entry)
        except Exception:
            self.handleError(record)

    def entries(self, limit: int = 100) -> list[dict]:
        """Return the most recent *limit* entries (newest first)."""
        items = list(self._buffer)[-limit:]
        items.reverse()
        return [asdict(e) for e in items]


# Module-level singleton
_handler: BufferHandler | None = None


def get_buffer_handler() -> BufferHandler:
    """Return (and lazily create) the singleton BufferHandler."""
    global _handler
    if _handler is None:
        _handler = BufferHandler(maxlen=200)
        _handler.setFormatter(logging.Formatter("%(message)s"))
        _handler.setLevel(logging.DEBUG)
    return _handler


def install_buffer_handler() -> BufferHandler:
    """Attach the buffer handler to the relevant app loggers."""
    handler = get_buffer_handler()

    # Attach to the loggers we care about
    target_loggers = [
        "app.main",
        "app.picks.worker",
        "app.picks.enqueue",
        "app.ingestion.sync",
        "app.ingestion.espn_client",
        "app.ai.openai_client",
    ]
    for name in target_loggers:
        lg = logging.getLogger(name)
        if handler not in lg.handlers:
            lg.addHandler(handler)
        lg.setLevel(logging.DEBUG)

    return handler
