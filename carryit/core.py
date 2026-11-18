"""Lógica de descarga (sin interfaz). Envuelve yt-dlp y localiza FFmpeg / Deno."""
from __future__ import annotations

import glob
import logging
import os
import re
import shutil
import sys
import tempfile
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Callable

import yt_dlp
from yt_dlp.utils import DownloadCancelled

from .i18n import _

log = logging.getLogger("carryit")

VIDEO_FORMATS = ["MP4", "MKV", "WEBM"]
AUDIO_FORMATS = ["MP3", "M4A", "OPUS", "FLAC", "WAV"]
LOSSLESS_AUDIO = {"FLAC", "WAV"}
DEFAULT_HEIGHTS = [2160, 1440, 1080, 720, 480, 360]
AUDIO_BITRATES = ["320", "256", "192", "128"]

class _Limiter:
    """Cuántas descargas corren a la vez; el resto espera en cola. El límite se puede cambiar en vivo."""

    def __init__(self, limit: int) -> None:
        self.limit = limit
        self.active = 0
        self._cond = threading.Condition()

    def set_limit(self, limit: int) -> None:
        with self._cond:
            self.limit = max(1, int(limit))
            self._cond.notify_all()

    def __enter__(self):
        with self._cond:
            while self.active >= self.limit:
                self._cond.wait()
            self.active += 1
        return self

    def __exit__(self, *exc) -> None:
        with self._cond:
            self.active -= 1
            self._cond.notify_all()


MAX_PARALLEL = 3
_slots = _Limiter(MAX_PARALLEL)


def set_max_parallel(n: int) -> None:
    _slots.set_limit(n)


# Cómo se nombran los archivos (Ajustes).
FILENAME_STYLES = {
    "title": "%(title)s",
    "title_channel": "%(title)s - %(channel,uploader|Desconocido)s",
    "channel_title": "%(channel,uploader|Desconocido)s - %(title)s",
}

# YouTube a veces rechaza (403) un enlace que él mismo entregó. Se reintenta con enlaces nuevos.
MAX_ATTEMPTS = 3
_RETRYABLE = ("403", "forbidden", "http error 5", "timed out", "connection reset",
              "incompleteread", "remote end closed", "giving up after", "unable to download video data")


def _is_retryable(errors: list[str]) -> bool:
    return any(p in e.lower() for e in errors for p in _RETRYABLE)


# --------------------------------------------------------------------------- #
# Localización de herramientas externas
# --------------------------------------------------------------------------- #
def app_dir() -> str:
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _exe(name: str) -> str:
    return f"{name}.exe" if os.name == "nt" else name


def find_ffmpeg() -> str | None:
    """Devuelve la carpeta que contiene ffmpeg, o None."""
    exe = _exe("ffmpeg")
    base = app_dir()
    for folder in (os.path.join(base, "ffmpeg", "bin"), os.path.join(base, "ffmpeg"), base):
        if os.path.isfile(os.path.join(folder, exe)):
            return folder
    found = shutil.which("ffmpeg")
    if found:
        return os.path.dirname(found)
    if os.name == "nt":
        # Instalación por winget (la PATH puede no estar refrescada aún).
        pattern = os.path.join(os.environ.get("LOCALAPPDATA", ""), "Microsoft", "WinGet",
                               "Packages", "Gyan.FFmpeg*", "*", "bin", exe)
        matches = sorted(glob.glob(pattern), reverse=True)
        if matches:
            return os.path.dirname(matches[0])
        for folder in (r"C:\ffmpeg\bin", r"C:\Program Files\ffmpeg\bin"):
            if os.path.isfile(os.path.join(folder, exe)):
                return folder
    return None


def find_deno() -> str | None:
    """Deno es el motor JavaScript que yt-dlp usa para resolver los retos de YouTube."""
    exe = _exe("deno")
    for folder in (app_dir(), os.path.dirname(sys.executable)):
        path = os.path.join(folder, exe)
        if os.path.isfile(path):
            return path
    found = shutil.which("deno")
    if found:
        return found
    try:
        import deno  # paquete de PyPI que trae el binario
        return deno.find_deno_bin()
    except Exception:
        return None


def ytdlp_version() -> str:
    return yt_dlp.version.__version__


# --------------------------------------------------------------------------- #
# Opciones base de yt-dlp
# --------------------------------------------------------------------------- #
class _Logger:
    """yt-dlp exige un logger cuando no hay consola (pythonw)."""

    def __init__(self) -> None:
        self.errors: list[str] = []
        self.warnings: list[str] = []

    def debug(self, msg: str) -> None:
        pass

    def info(self, msg: str) -> None:
        pass

    def warning(self, msg: str) -> None:
        log.warning(msg)
        self.warnings.append(msg)

    def error(self, msg: str) -> None:
        log.error(msg)
        self.errors.append(msg)


BROWSERS = {"firefox": "Firefox", "chrome": "Chrome", "edge": "Edge", "brave": "Brave", "opera": "Opera"}
_cookies_browser: str | None = None


def set_cookies_browser(browser: str | None) -> None:
    """Usa la sesión iniciada en ese navegador para sitios que piden cuenta (Instagram, Vimeo…)."""
    global _cookies_browser
    _cookies_browser = browser if browser in BROWSERS else None


def _apply_tools(opts: dict) -> dict:
    ff = find_ffmpeg()
    if ff:
        opts["ffmpeg_location"] = ff
    dn = find_deno()
    if dn:
        opts["js_runtimes"] = {"deno": {"path": dn}}
    if _cookies_browser:
        opts["cookiesfrombrowser"] = (_cookies_browser, None, None, None)
    return opts


def _clean_error(msg: str) -> str:
    msg = msg.replace("ERROR: ", "").strip()
    lowered = msg.lower()
    if "private video" in lowered:
        return _("El video es privado.")
    if "sign in to confirm your age" in lowered:
        return _("El video tiene restricción de edad (requiere iniciar sesión).")
    if "unavailable" in lowered:
        return _("El video no está disponible.")
    if "is not a valid url" in lowered or "unsupported url" in lowered:
        return _("El enlace no es válido.")
    if ("could not copy" in lowered and "cookie" in lowered) or "failed to decrypt" in lowered:
        return _("No se pudo leer la sesión del navegador. Ciérralo por completo y reintenta, "
                 "o elige otro navegador en Ajustes (Firefox es el más compatible).")
    if ("login" in lowered or "logged-in" in lowered or "authentication" in lowered
            or "cookies" in lowered or "sign in" in lowered):
        return _("Este sitio pide iniciar sesión para ver este contenido. En Ajustes elige el navegador "
                 "donde tienes tu sesión abierta y vuelve a intentarlo.")
    if "unable to download webpage" in lowered or "getaddrinfo" in lowered:
        return _("No hay conexión con el sitio. Revisa tu internet.")
    if "ffmpeg" in lowered and "not found" in lowered:
        return _("No se encontró FFmpeg; es necesario para unir video/audio y convertir a MP3.")
    if "403" in lowered or "forbidden" in lowered:
        return _("El sitio rechazó la descarga (error 403) varias veces. "
                 "Presiona Reintentar en unos minutos o usa «Actualizar yt-dlp».")
    if "429" in lowered or "too many requests" in lowered:
        return _("El sitio está limitando las descargas (demasiadas solicitudes). Espera unos minutos.")
    if "requested format is not available" in lowered:
        return _("La calidad o el formato elegido no está disponible para este video.")
    if "members-only" in lowered or "join this channel" in lowered:
        return _("El video es exclusivo para miembros del canal.")
    if "live event" in lowered or "premieres in" in lowered:
        return _("El video es un estreno o transmisión que aún no empieza.")
    if "copyright" in lowered or "blocked it in your country" in lowered or "not available in your country" in lowered:
        return _("El video está bloqueado en tu país o por derechos de autor.")
    if "timed out" in lowered or "connection reset" in lowered or "remote end closed" in lowered:
        return _("Se perdió la conexión con el sitio. Revisa tu internet y presiona Reintentar.")
    if "no space left" in lowered:
        return _("No hay espacio suficiente en el disco.")
    if "permission denied" in lowered:
        return _("No hay permiso para guardar en la carpeta elegida.")
    return _("Error de descarga:") + " " + re.sub(r"^\[[\w:]+\] [\w-]+: ", "", msg.splitlines()[0])[:250]


# --------------------------------------------------------------------------- #
# Análisis de un enlace
# --------------------------------------------------------------------------- #
@dataclass
class MediaInfo:
    url: str
    title: str
    uploader: str = ""
    duration: int | None = None
    thumbnail: str | None = None
    is_playlist: bool = False
    count: int = 1
    heights: list[int] = field(default_factory=list)
    # Solo listas: (índice en la lista empezando en 1, título, duración en segundos o None)
    entries: list[tuple[int, str, int | None]] = field(default_factory=list)
    heights_known: bool = True     # False si el sitio no dice qué resoluciones tiene
    audio_only: bool = False       # el enlace no tiene video (p. ej. SoundCloud)
    site: str = ""                 # sitio de origen según yt-dlp (Youtube, Facebook, TikTok…)
    track: str = ""                # nombre de la canción, si el sitio lo da
    artist: str = ""               # artista, si el sitio lo da


UNAVAILABLE_TITLES = {"[Private video]", "[Deleted video]", "[Video privado]", "[Video eliminado]"}


def fetch_info(url: str, playlist: bool) -> MediaInfo:
    logger = _Logger()
    opts = _apply_tools({
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
        "logger": logger,
        "skip_download": True,
        "extract_flat": "in_playlist",
        "noplaylist": not playlist,
    })
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)
    except Exception as exc:  # yt-dlp lanza DownloadError con mensajes en inglés
        raise RuntimeError(_clean_error(str(exc))) from exc

    if info.get("_type") == "playlist" or info.get("entries") is not None:
        raw = list(info.get("entries") or [])
        entries = [e for e in raw if e]
        items = [(i, e.get("title") or e.get("id") or f"Video {i}", e.get("duration"))
                 for i, e in enumerate(raw, start=1) if e]
        thumb = _best_thumb(info.get("thumbnails"))
        if not thumb and entries:
            thumb = _best_thumb(entries[0].get("thumbnails")) or entries[0].get("thumbnail")
        return MediaInfo(
            url=url,
            title=info.get("title") or _("Lista de reproducción"),
            uploader=info.get("uploader") or info.get("channel") or "",
            thumbnail=thumb,
            is_playlist=True,
            count=info.get("playlist_count") or len(entries),
            heights=list(DEFAULT_HEIGHTS),
            entries=items,
        )

    formats = info.get("formats") or []
    heights = sorted(
        {f["height"] for f in formats if f.get("height") and f.get("vcodec") not in (None, "none")},
        reverse=True,
    )
    # Solo audio: todos los formatos dicen explícitamente que no traen video (SoundCloud, podcasts…).
    audio_only = bool(formats) and all(f.get("vcodec") == "none" for f in formats)
    artists = info.get("artists") or ([info["artist"]] if info.get("artist") else [])
    return MediaInfo(
        url=url,
        title=info.get("title") or url,
        uploader=info.get("uploader") or info.get("channel") or "",
        duration=info.get("duration"),
        thumbnail=info.get("thumbnail") or _best_thumb(info.get("thumbnails")),
        heights=heights or list(DEFAULT_HEIGHTS),
        heights_known=bool(heights),
        audio_only=audio_only,
        site=info.get("extractor_key") or "",
        track=info.get("track") or "",
        artist=", ".join(artists),
    )


def _best_thumb(thumbs) -> str | None:
    if not thumbs:
        return None
    jpgs = [t for t in thumbs if t.get("url", "").split("?")[0].endswith(".jpg")]
    pool = jpgs or thumbs
    pool = sorted(pool, key=lambda t: (t.get("width") or 0) * (t.get("height") or 0))
    return pool[-1].get("url")


@dataclass
class SearchResult:
    url: str
    video_id: str
    title: str
    channel: str = ""
    duration: int | None = None
    thumbnail: str = ""


def search(query: str, limit: int = 12) -> list[SearchResult]:
    """Busca videos en YouTube por texto (sin descargar nada)."""
    opts = _apply_tools({
        "quiet": True, "no_warnings": True, "noprogress": True, "logger": _Logger(),
        "skip_download": True, "extract_flat": True,
    })
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(f"ytsearch{limit}:{query}", download=False)
    except Exception as exc:
        raise RuntimeError(_clean_error(str(exc))) from exc
    results = []
    for e in info.get("entries") or []:
        if not e or not e.get("id"):
            continue
        vid = e["id"]
        results.append(SearchResult(
            url=f"https://www.youtube.com/watch?v={vid}",
            video_id=vid,
            title=e.get("title") or vid,
            channel=e.get("channel") or e.get("uploader") or "",
            duration=int(e["duration"]) if e.get("duration") else None,
            thumbnail=f"https://i.ytimg.com/vi/{vid}/mqdefault.jpg",
        ))
    return results


_YT_ID = re.compile(r"(?:v=|youtu\.be/|/shorts/|/live/|/embed/)([\w-]{11})")
_YT_LIST = re.compile(r"[?&]list=([\w-]+)")


def media_key(url: str, playlist: bool = False) -> str:
    """Identificador estable de lo que se descarga (para el historial y avisar de repetidos)."""
    if playlist:
        m = _YT_LIST.search(url)
        if m:
            return f"yt-list:{m.group(1)}"
    m = _YT_ID.search(url)
    if m:
        return f"yt:{m.group(1)}"
    return url.strip().split("#")[0]


SUPPORTED_SITES = ("youtube.com", "youtu.be", "facebook.com", "fb.watch", "tiktok.com", "instagram.com",
                   "x.com", "twitter.com", "vimeo.com", "soundcloud.com", "twitch.tv", "dailymotion.com",
                   "dai.ly", "reddit.com")


def is_media_url(text: str) -> bool:
    """¿El texto es un enlace de un sitio de video conocido? (para detectar enlaces copiados)."""
    m = re.match(r"https?://([^/\s]+)/\S+$", text.strip())
    if not m:
        return False
    host = m.group(1).lower().split(":")[0]
    return any(host == s or host.endswith("." + s) for s in SUPPORTED_SITES)


def fetch_thumbnail(url: str) -> bytes | None:
    import urllib.request
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            return resp.read()
    except Exception:
        return None


# --------------------------------------------------------------------------- #
# Descarga
# --------------------------------------------------------------------------- #
@dataclass
class DownloadOptions:
    url: str
    output_dir: str
    mode: str = "video"            # "video" | "audio"
    video_format: str = "MP4"      # MP4 | MKV | WEBM
    height: int | None = None      # None = mejor calidad
    compat: bool = False           # MP4 compatible con todo (H.264 + AAC, hasta 1080p)
    audio_format: str = "MP3"      # MP3 | M4A | OPUS | FLAC | WAV
    audio_bitrate: str = "320"     # kbps (se ignora en FLAC/WAV)
    playlist: bool = False
    playlist_items: str | None = None  # p. ej. "1-3,7,9"; None = todos
    filename_style: str = "title"      # ver FILENAME_STYLES
    subtitles: str = ""                # idiomas, p. ej. "es.*,en.*"; "" = sin subtítulos (solo video)
    keep_subtitle_files: bool = False  # además de incrustarlos, guardar el .srt aparte
    section: tuple[float, float] | None = None   # recortar: (inicio, fin) en segundos
    rate_limit: str = ""               # p. ej. "2M" (2 MB/s); "" = sin límite
    tags: dict | None = None           # audio: {"title": ..., "artist": ...} elegidos por el usuario


def parse_time(text: str) -> float | None:
    """'1:20' -> 80, '1:02:03' -> 3723, '95' -> 95. None si no es válido."""
    text = text.strip().replace(",", ".")
    if not text:
        return None
    try:
        parts = [float(p) for p in text.split(":")]
    except ValueError:
        return None
    if len(parts) > 3 or any(p < 0 for p in parts):
        return None
    secs = 0.0
    for p in parts:
        secs = secs * 60 + p
    return secs


def fmt_clock(secs: float) -> str:
    secs = int(round(secs))
    h, rem = divmod(secs, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def compress_indices(indices) -> str:
    """[1,2,3,7,9,10] -> "1-3,7,9-10" (formato de --playlist-items)."""
    out: list[str] = []
    nums = sorted(set(indices))
    i = 0
    while i < len(nums):
        j = i
        while j + 1 < len(nums) and nums[j + 1] == nums[j] + 1:
            j += 1
        out.append(str(nums[i]) if i == j else f"{nums[i]}-{nums[j]}")
        i = j + 1
    return ",".join(out)


def build_args(o: DownloadOptions) -> list[str]:
    name = FILENAME_STYLES.get(o.filename_style, FILENAME_STYLES["title"])
    args = [
        "--paths", o.output_dir,
        "--no-mtime",              # que el archivo tenga la fecha de hoy
        "--embed-metadata",
        "--yes-playlist" if o.playlist else "--no-playlist",
        # Video suelto: "Título.ext". Lista: "Nombre de la lista/001 - Título.ext"
        # (el "." evita que un video suelto termine en la raíz de la unidad)
        "--output", f"%(playlist_title,playlist_id|.)s/%(playlist_index&{{:03d}} - |)s{name}.%(ext)s",
        "--retries", "10",
        "--fragment-retries", "10",
    ]
    if o.playlist_items:
        args += ["--playlist-items", o.playlist_items]

    if o.mode == "audio":
        fmt = o.audio_format.upper()
        args += ["--format", "ba/b", "--extract-audio", "--audio-format", fmt.lower()]
        if fmt not in LOSSLESS_AUDIO:
            args += ["--audio-quality", f"{o.audio_bitrate}K"]
        if fmt != "WAV":
            args += ["--embed-thumbnail"]
    else:
        fmt = o.video_format.upper()
        res = f"res:{o.height}" if o.height else "res"
        selector = "bv*+ba/b"
        if fmt == "MP4" and o.compat:
            # Compatible con todo: video H.264 + audio AAC (lo abre cualquier tele, celular o reproductor).
            # YouTube solo lo da hasta 1080p; si un sitio no lo tiene, se usa lo mejor disponible.
            selector = ("bv*[vcodec^=avc]+ba[acodec^=mp4a]/bv*[vcodec^=avc]+ba/"
                        "b[vcodec^=avc]/bv*+ba/b")
            sort = "res:1080,fps,vcodec:h264,acodec:aac"
        elif fmt == "MP4":
            # h264 + aac si existe a esa resolución; en 1440p/4K YouTube solo tiene AV1 o VP9.
            sort = f"{res},fps,vcodec:h264,acodec:aac"
        elif fmt == "WEBM":
            sort = f"{res},fps,vcodec:vp9,acodec:opus"
        else:
            sort = f"{res},fps"
        args += ["--format", selector, "--format-sort", sort,
                 "--merge-output-format", fmt.lower()]
        if fmt != "WEBM":
            args += ["--embed-thumbnail"]
        if o.subtitles:
            # Subtítulos hechos por personas si existen; si no, los automáticos. Se incrustan en el video.
            args += ["--write-subs", "--write-auto-subs", "--sub-langs", o.subtitles, "--embed-subs"]
            if fmt != "WEBM":
                args += ["--convert-subs", "srt"]
            if not o.keep_subtitle_files:
                args += ["--compat-options", "no-keep-subs"]

    if o.section and not o.playlist:
        start, end = o.section
        # Recorte exacto: se vuelve a codificar solo alrededor de los cortes.
        args += ["--download-sections", f"*{start:.2f}-{end:.2f}", "--force-keyframes-at-cuts"]
    if o.rate_limit:
        args += ["--limit-rate", o.rate_limit]
    return args


SUBTITLE_LANGS = {          # código guardado en Ajustes -> idiomas que se piden a yt-dlp
    "es": "es,es-419,es-ES,es-MX,es-US",
    "en": "en,en-US,en-GB",
    "es_en": "es,es-419,es-ES,es-MX,es-US,en,en-US,en-GB",
}


def has_subtitles(path: str) -> bool:
    """¿El video trae al menos una pista de subtítulos?"""
    ff = find_ffmpeg()
    probe = os.path.join(ff, _exe("ffprobe")) if ff else None
    if not probe or not os.path.isfile(probe):
        return True  # no se puede comprobar: no se avisa
    try:
        import subprocess
        r = subprocess.run([probe, "-v", "error", "-select_streams", "s", "-show_entries", "stream=index",
                            "-of", "csv=p=0", path], capture_output=True, text=True, timeout=30,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        return bool(r.stdout.strip())
    except Exception:
        return True


_BAD_NAME = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def apply_tags(path: str, tags: dict, filename_style: str) -> str:
    """Escribe título y artista en un archivo de audio y lo renombra igual. Devuelve la ruta final."""
    title = (tags.get("title") or "").strip()
    artist = (tags.get("artist") or "").strip()
    try:
        import mutagen
        audio = mutagen.File(path, easy=True)
        if audio is not None:
            if title:
                audio["title"] = [title]
            if artist:
                audio["artist"] = [artist]
            audio.save()
    except Exception:
        log.exception("No se pudieron escribir las etiquetas de %s", path)
    if not title:
        return path
    if filename_style == "title_channel" and artist:
        name = f"{title} - {artist}"
    elif filename_style == "channel_title" and artist:
        name = f"{artist} - {title}"
    else:
        name = title
    name = _BAD_NAME.sub("_", name).strip(" .")[:180] or "audio"
    folder, ext = os.path.dirname(path), os.path.splitext(path)[1]
    target = os.path.join(folder, name + ext)
    n = 2
    while os.path.exists(target) and os.path.normcase(target) != os.path.normcase(path):
        target = os.path.join(folder, f"{name} ({n}){ext}")
        n += 1
    try:
        os.replace(path, target)
        return target
    except OSError:
        return path


class DownloadTask:
    """Ejecuta una descarga en un hilo y reporta eventos mediante `on_event(dict)`."""

    def __init__(self, options: DownloadOptions, on_event: Callable[[dict], None],
                 resume_files: set[str] | None = None) -> None:
        self.options = options
        self.on_event = on_event
        self._cancel = threading.Event()
        self._paused = False
        # Al reanudar se heredan los archivos parciales de la descarga pausada (para limpiarlos si hace falta).
        self._tmpfiles: set[str] = set(resume_files or ())
        self.files: list[str] = []
        self._started = time.time()
        self.thread = threading.Thread(target=self._run, daemon=True)

    def start(self) -> None:
        self.thread.start()

    def cancel(self) -> None:
        self._cancel.set()

    def pause(self) -> None:
        """Detiene la descarga conservando lo ya bajado; al reanudar, yt-dlp continúa desde ahí."""
        self._paused = True
        self._cancel.set()

    def _stopped_event(self) -> dict:
        if self._paused:
            return {"type": "paused"}
        self._remove_partials()
        return {"type": "cancelled"}

    @property
    def cancelled(self) -> bool:
        return self._cancel.is_set()

    # -- hooks de yt-dlp (se ejecutan en el hilo de descarga) --
    def _progress_hook(self, d: dict) -> None:
        if self._cancel.is_set():
            raise DownloadCancelled()
        info = d.get("info_dict") or {}
        if d.get("tmpfilename"):
            self._tmpfiles.add(d["tmpfilename"])
        if d.get("filename"):
            self._tmpfiles.add(d["filename"])
        ev = {
            "type": "progress",
            "title": info.get("title"),
            "index": info.get("playlist_index"),
            "total": info.get("n_entries") or info.get("playlist_count"),
            "stream": "audio" if info.get("vcodec") == "none" else "video",
        }
        if d["status"] == "downloading":
            total = d.get("total_bytes") or d.get("total_bytes_estimate")
            done = d.get("downloaded_bytes") or 0
            ev.update(
                fraction=(done / total) if total else None,
                downloaded=done,
                total_bytes=total,
                speed=d.get("speed"),
                eta=d.get("eta"),
            )
        elif d["status"] == "finished":
            ev.update(fraction=1.0)
        else:
            return
        self.on_event(ev)

    def _pp_hook(self, d: dict) -> None:
        if d.get("status") == "started":
            names = {
                "Merger": _("Uniendo video y audio…"),
                "ExtractAudio": _("Convirtiendo audio…"),
                "EmbedThumbnail": _("Agregando portada…"),
                "Metadata": _("Agregando datos…"),
                "EmbedSubtitle": _("Agregando subtítulos…"),
                "SubtitlesConvertor": _("Convirtiendo subtítulos…"),
            }
            pp = d.get("postprocessor", "")
            self.on_event({"type": "stage", "text": names.get(pp, _("Procesando…"))})

    def _post_hook(self, filepath: str) -> None:
        self.files.append(filepath)
        self.on_event({"type": "file", "path": filepath})

    def _attempt(self, logger: _Logger, extra: dict) -> int:
        """Un intento completo con yt-dlp. Devuelve el código de salida (0 = todo bien)."""
        parsed = yt_dlp.parse_options(build_args(self.options))
        opts = _apply_tools(dict(parsed.ydl_opts))
        opts.update(
            quiet=True,
            no_warnings=True,
            noprogress=True,
            logger=logger,
            progress_hooks=[self._progress_hook],
            postprocessor_hooks=[self._pp_hook],
            post_hooks=[self._post_hook],
            **extra,
        )
        if self.options.subtitles:
            # Si los subtítulos fallan (YouTube los limita a veces), el video se descarga igual.
            opts["ignoreerrors"] = True
        if not opts.get("ffmpeg_location"):
            log.warning("FFmpeg no encontrado")
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                return ydl.download([self.options.url])
        except DownloadCancelled:
            raise
        except Exception as exc:  # errores de extracción que yt-dlp no ignora
            if self._cancel.is_set():
                raise DownloadCancelled() from exc
            logger.errors.append(str(exc))
            return 1

    def _run(self) -> None:
        self.on_event({"type": "stage", "text": _("En cola…")})
        with _slots:
            if self._cancel.is_set():
                self.on_event(self._stopped_event())
                return
            self.on_event({"type": "stage", "text": _("Conectando…")})
            # Archivo temporal de "ya descargados": al reintentar una lista no se repite lo que ya bajó.
            archive = os.path.join(tempfile.gettempdir(), f"carryit-{uuid.uuid4().hex}.txt")
            try:
                os.makedirs(self.options.output_dir, exist_ok=True)
                for attempt in range(1, MAX_ATTEMPTS + 1):
                    logger = _Logger()
                    extra: dict = {"download_archive": archive}
                    if attempt == MAX_ATTEMPTS:
                        # Último intento con otro cliente de YouTube (formatos HLS, menos propensos al 403).
                        extra["extractor_args"] = {"youtube": {"player_client": ["visionos"]}}
                    rc = self._attempt(logger, extra)
                    if self._cancel.is_set():
                        raise DownloadCancelled()
                    if rc and any("416" in e for e in logger.errors):
                        # Lo ya descargado no coincide con el archivo del servidor (pasa al reanudar):
                        # se descarta ese pedazo y se baja de nuevo.
                        log.warning("Error 416 al reanudar %s; se descarta lo parcial", self.options.url)
                        self._discard_parts()
                        if attempt < MAX_ATTEMPTS:
                            continue
                    if not rc or attempt == MAX_ATTEMPTS or not _is_retryable(logger.errors):
                        break
                    log.warning("Intento %d fallido para %s; reintentando", attempt, self.options.url)
                    self.on_event({"type": "stage",
                                   "text": _("El sitio rechazó la conexión, reintentando ({n}/{total})…").format(
                                       n=attempt + 1, total=MAX_ATTEMPTS)})
                    if self._cancel.wait(2 * attempt):
                        raise DownloadCancelled()
                if rc and not self.files:
                    raise RuntimeError(logger.errors[-1] if logger.errors else _("La descarga falló."))
                o = self.options
                if o.tags and o.mode == "audio" and len(self.files) == 1:
                    self.on_event({"type": "stage", "text": _("Guardando título y artista…")})
                    self.files = [apply_tags(self.files[0], o.tags, o.filename_style)]
                # Se revisa el archivo final: ¿quedó con subtítulos? (el sitio puede no tenerlos o limitarlos)
                subs_failed = bool(o.subtitles) and o.mode == "video" and not all(
                    has_subtitles(f) for f in self.files)
                self.on_event({"type": "done", "files": list(self.files),
                               "partial_errors": len(logger.errors) if rc else 0,
                               "subs_failed": subs_failed})
            except DownloadCancelled:
                self.on_event(self._stopped_event())
            except Exception as exc:
                if self._cancel.is_set():
                    self.on_event(self._stopped_event())
                else:
                    log.exception("Fallo en la descarga de %s", self.options.url)
                    self.on_event({"type": "error", "message": _clean_error(str(exc))})
            finally:
                try:
                    os.remove(archive)
                except OSError:
                    pass

    @property
    def partial_files(self) -> set[str]:
        return set(self._tmpfiles)

    def _discard_parts(self) -> None:
        for path in self._tmpfiles:
            for candidate in (path + ".part", path + ".ytdl", path if path.endswith(".part") else ""):
                if candidate and os.path.isfile(candidate):
                    try:
                        os.remove(candidate)
                    except OSError:
                        pass

    def _remove_partials(self) -> None:
        """Borra .part/.ytdl y las miniaturas o pistas sueltas que dejó esta descarga."""
        candidates: set[str] = set()
        for path in self._tmpfiles:
            candidates.update({path, path + ".part", path + ".ytdl"})
            # "Titulo.f401.mp4" -> "Titulo"
            base = re.sub(r"(\.f[\w-]+)?\.\w+(\.part)?$", "", path)
            candidates.update(base + ext for ext in (".webp", ".jpg", ".png"))
            if re.search(r"\.f[\w-]+\.\w+(\.part)?$", path):  # pista separada (video o audio)
                candidates.add(re.sub(r"\.part$", "", path))
        for candidate in candidates:
            try:
                if os.path.isfile(candidate) and os.path.getmtime(candidate) >= self._started - 1:
                    os.remove(candidate)
            except OSError:
                pass
