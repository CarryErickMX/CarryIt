"""Preferencias del usuario guardadas en %APPDATA%\\CarryIt\\settings.json."""
from __future__ import annotations

import json
import os
import shutil
from dataclasses import asdict, dataclass, fields

from . import APP_ID

LEGACY_IDS = ("DescargadorYT",)  # nombres anteriores de la app


def data_dir() -> str:
    base = os.environ.get("APPDATA") or os.path.expanduser("~")
    path = os.path.join(base, APP_ID)
    if not os.path.isdir(path):
        os.makedirs(path, exist_ok=True)
        # Traer las preferencias de la versión con el nombre anterior.
        for old in LEGACY_IDS:
            old_settings = os.path.join(base, old, "settings.json")
            if os.path.isfile(old_settings):
                try:
                    shutil.copy2(old_settings, os.path.join(path, "settings.json"))
                except OSError:
                    pass
                break
    return path


def default_output_dir() -> str:
    downloads = os.path.join(os.path.expanduser("~"), "Downloads")
    return downloads if os.path.isdir(downloads) else os.path.expanduser("~")


@dataclass
class Settings:
    output_dir: str = ""
    mode: str = "video"
    video_format: str = "MP4"
    video_quality: str = "best"      # "best" o la altura, p. ej. "1080"
    audio_format: str = "MP3"
    audio_quality: str = "320 kbps"
    playlist: bool = False
    appearance: str = "Dark"
    language: str = "auto"           # auto (idioma de Windows) | es | en
    auto_update: bool = True
    last_update_check: float = 0.0
    welcome_shown: bool = False
    max_parallel: int = 3            # descargas simultáneas
    filename_style: str = "title"    # ver core.FILENAME_STYLES
    split_folders: bool = False      # separar en carpetas «Videos» y «Audio»
    watch_clipboard: bool = True     # detectar enlaces copiados
    notify: bool = True              # avisar al terminar si la ventana no está al frente
    subtitles: str = "none"          # none | es | en | es_en
    keep_subtitle_files: bool = False  # además de incrustarlos, guardar el .srt aparte
    rate_limit: str = ""             # "" = sin límite; p. ej. "2M"
    cookies_browser: str = ""        # navegador con sesión iniciada para sitios que la piden

    @classmethod
    def load(cls) -> "Settings":
        s = cls()
        try:
            with open(os.path.join(data_dir(), "settings.json"), encoding="utf-8") as fh:
                raw = json.load(fh)
            known = {f.name for f in fields(cls)}
            for key, value in raw.items():
                if key in known:
                    setattr(s, key, value)
        except (OSError, ValueError):
            pass
        if not s.output_dir or not os.path.isdir(s.output_dir):
            s.output_dir = default_output_dir()
        s._migrate()
        return s

    def _migrate(self) -> None:
        """Convierte valores guardados por versiones anteriores (textos en español) a códigos."""
        q = str(self.video_quality)
        if not (q == "best" or q.isdigit()):
            head = q.split("p")[0]
            self.video_quality = head if head.isdigit() else "best"
        old_subs = {"Sin subtítulos": "none", "Español": "es", "Inglés": "en", "Español e inglés": "es_en"}
        if self.subtitles in old_subs:
            self.subtitles = old_subs[self.subtitles]
        if self.subtitles not in ("none", "es", "en", "es_en"):
            self.subtitles = "none"
        if self.language not in ("auto", "es", "en"):
            self.language = "auto"

    def save(self) -> None:
        try:
            with open(os.path.join(data_dir(), "settings.json"), "w", encoding="utf-8") as fh:
                json.dump(asdict(self), fh, indent=2, ensure_ascii=False)
        except OSError:
            pass
