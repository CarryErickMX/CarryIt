"""Historial de descargas, guardado en %APPDATA%\\CarryIt\\history.json."""
from __future__ import annotations

import json
import os
import threading
import time
from dataclasses import asdict, dataclass, field

from .settings import data_dir

MAX_ENTRIES = 500
_lock = threading.Lock()


@dataclass
class HistoryEntry:
    key: str                 # identificador estable (core.media_key)
    url: str
    title: str
    kind: str                # p. ej. "MP3 320k" o "MP4 1080p"
    files: list[str] = field(default_factory=list)
    folder: str = ""
    date: float = field(default_factory=time.time)

    @property
    def exists(self) -> bool:
        return any(os.path.isfile(f) for f in self.files)


def _path() -> str:
    return os.path.join(data_dir(), "history.json")


def load() -> list[HistoryEntry]:
    try:
        with open(_path(), encoding="utf-8") as fh:
            raw = json.load(fh)
        known = set(HistoryEntry.__dataclass_fields__)
        return [HistoryEntry(**{k: v for k, v in e.items() if k in known}) for e in raw]
    except (OSError, ValueError, TypeError):
        return []


def _save(entries: list[HistoryEntry]) -> None:
    tmp = _path() + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump([asdict(e) for e in entries[:MAX_ENTRIES]], fh, ensure_ascii=False, indent=1)
    os.replace(tmp, _path())


def add(entry: HistoryEntry) -> None:
    with _lock:
        entries = [e for e in load() if not (e.key == entry.key and e.kind == entry.kind)]
        entries.insert(0, entry)
        try:
            _save(entries)
        except OSError:
            pass


def find(key: str) -> HistoryEntry | None:
    """La descarga más reciente de ese mismo video o lista cuyos archivos todavía existen."""
    for e in load():
        if e.key == key and e.exists:
            return e
    return None


def clear() -> None:
    with _lock:
        try:
            _save([])
        except OSError:
            pass


def remove(entry: HistoryEntry) -> None:
    with _lock:
        try:
            _save([e for e in load() if not (e.key == entry.key and e.date == entry.date)])
        except OSError:
            pass
