"""Descarga de imágenes (fotos, carruseles, galerías) con gallery-dl, y miniaturas de videos con yt-dlp.

Tiene la misma forma que core.DownloadTask (eventos "stage", "progress", "file", "done", "error",
"cancelled"), para que la interfaz las trate igual.
"""
from __future__ import annotations

import logging
import os
import re
import threading
import time
import urllib.parse

from . import core
from .i18n import _

log = logging.getLogger("carryit")

IMAGE_FORMATS = ["JPG", "Original"]
_CONVERT = {".webp", ".avif", ".heic", ".heif", ".bmp", ".jfif"}     # se pasan a JPG si se elige «JPG»
_IMAGE_EXT = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".avif", ".heic", ".heif", ".bmp", ".jfif"}
_lock = threading.Lock()            # la configuración de gallery-dl es global: una galería a la vez
PROBE_LIMIT = 300
_local = threading.local()          # descarga (ImageTask) que corre en este hilo


class _InterruptibleTime:
    """Reemplaza al módulo `time` dentro de gallery-dl: sus esperas (p. ej. «el sitio pide esperar 60 s»)
    se cortan al instante si el usuario cancela, y avisan en pantalla si son largas."""

    def __getattr__(self, name):
        return getattr(time, name)

    @staticmethod
    def sleep(seconds: float) -> None:
        task = getattr(_local, "task", None)
        if task is None:
            time.sleep(seconds)
            return
        if seconds >= 5:
            task.on_event({"type": "stage",
                           "text": _("El sitio pidió esperar un momento ({s} s)…").format(s=int(seconds))})
        if task._cancel.wait(seconds):
            from gallery_dl import exception
            raise exception.TerminateExtraction()


def _patch_waits() -> None:
    from gallery_dl.downloader import http
    from gallery_dl.extractor import common
    for module in (http, common):
        if not isinstance(module.time, _InterruptibleTime):
            module.time = _InterruptibleTime()


def _gdl():
    """Importa gallery-dl solo cuando hace falta (tarda un poco en cargar sus 1000+ sitios)."""
    from gallery_dl import config, exception, extractor, job
    return config, exception, extractor, job


def version() -> str:
    try:
        from gallery_dl import version as v
        return v.__version__
    except Exception:
        return "?"


def is_youtube(url: str) -> bool:
    host = (urllib.parse.urlparse(url).hostname or "").lower()
    return host.endswith(("youtube.com", "youtu.be"))


def supported(url: str) -> bool:
    """¿gallery-dl sabe sacar imágenes de este enlace?"""
    if is_youtube(url):
        return False
    try:
        _cfg, _exc, extractor, _job = _gdl()
        extr = extractor.find(url)
        return extr is not None and extr.category not in ("directlink", "noop", "generic", "ytdl")
    except Exception:
        return False


# --------------------------------------------------------------------------- #
# Captura de errores de gallery-dl (los escribe en el registro, no como excepciones)
# --------------------------------------------------------------------------- #
class _Capture(logging.Handler):
    def __init__(self) -> None:
        super().__init__(logging.WARNING)
        self.thread = threading.get_ident()
        self.messages: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        # Errores, y los avisos de cookies (p. ej. «Failed to decrypt cookie»): explican por qué el sitio
        # luego pide iniciar sesión.
        if record.thread == self.thread and (record.levelno >= logging.ERROR or "cookie" in record.name
                                             or "cookie" in str(record.msg).lower()):
            try:
                self.messages.append(record.getMessage())
            except Exception:
                pass


def login_message() -> str:
    return core.login_message()


def _clean_error(messages: list[str]) -> str:
    text = " ".join(messages)
    low = text.lower()
    # Si no se pudo leer la sesión del navegador, decirlo (si no, el sitio solo dice «inicia sesión»).
    cookie_msg = core.cookie_problem(text) if core._cookies_browser else None
    if cookie_msg:
        return cookie_msg
    if any(k in low for k in ("authrequired", "authorizationerror", "login", "cookies", "account",
                              "redirected to", "not logged in", "authentication", "401", "unauthorized")):
        return login_message()
    if "notfounderror" in low or "404" in low or "not found" in low:
        return _("La publicación no existe o fue borrada.")
    if "429" in low or "rate limit" in low or "too many requests" in low:
        return _("El sitio está limitando las descargas (demasiadas solicitudes). Espera unos minutos.")
    if "noextractorerror" in low or "unsupported url" in low:
        return _("CarryIt no sabe sacar imágenes de este sitio.")
    if "unable to download data" in low or "connection" in low or "timed out" in low:
        return _("No hay conexión con el sitio. Revisa tu internet.")
    first = re.sub(r"^\w+(Error|Exception):\s*", "", messages[-1]) if messages else ""
    return (_("Error de descarga:") + " " + first[:200]) if first else _("No se encontraron imágenes en este enlace.")


def _configure(output_dir: str, directory: list[str], url: str = "") -> None:
    config, *_rest = _gdl()
    config.clear()
    config.set(("extractor",), "base-directory", output_dir)
    config.set(("extractor",), "directory", directory)
    config.set(("extractor",), "skip", True)                  # no repetir archivos que ya existen
    config.set(("downloader",), "mtime", False)               # fecha de hoy, como los videos
    # Si el sitio limita (error 429), pocos reintentos y esperas cortas: mejor avisar que quedarse minutos.
    config.set(("downloader",), "retries", 2)
    config.set(("downloader",), "sleep-429", 10)
    config.set(("extractor",), "retries", 2)
    config.set(("extractor",), "sleep-429", 10)
    config.set(("output",), "mode", "null")
    _patch_waits()
    # gallery-dl acepta una sola fuente de cookies: la sesión iniciada en CarryIt para este sitio; si no
    # hay, la del navegador elegido en Ajustes; si tampoco, las demás sesiones de CarryIt.
    from . import sessions
    browser = core._cookies_browser
    own = sessions.cookie_copy()
    if own and (sessions.has_session_for(url) or not browser):
        config.set(("extractor",), "cookies", own)
        config.set(("extractor",), "cookies-update", False)
    elif browser:
        config.set(("extractor",), "cookies", [browser])


def _person(kw: dict) -> str:
    for key in ("username", "owner_username", "author", "user", "uploader", "artist", "account", "channel"):
        v = kw.get(key)
        if isinstance(v, dict):
            v = (v.get("displayName") or v.get("display_name") or v.get("name") or v.get("nick")
                 or v.get("username") or v.get("handle"))
        if isinstance(v, str) and v.strip():
            return v.strip()
    return ""


def _post_id(kw: dict) -> str:
    for key in ("post_shortcode", "shortcode", "post_id", "tweet_id", "id", "gallery_id", "album_id"):
        v = kw.get(key)
        if v not in (None, ""):
            return str(v)
    return ""


def _title(kw: dict, category: str) -> str:
    for key in ("title", "description", "content", "caption", "text"):
        v = kw.get(key)
        if isinstance(v, str) and v.strip():
            line = v.strip().splitlines()[0]
            return line[:90] + ("…" if len(line) > 90 else "")
    who = _person(kw)
    return " · ".join(x for x in (category.title(), who) if x) or category.title()


def _safe(name: str) -> str:
    return re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name).strip(" .")[:120] or "imagenes"


# --------------------------------------------------------------------------- #
# Análisis
# --------------------------------------------------------------------------- #
def probe(url: str) -> core.MediaInfo:
    """Cuenta las imágenes de una publicación o galería sin descargarlas."""
    _config, exception, extractor, job = _gdl()
    items: list[tuple[str, dict]] = []
    meta: dict = {}

    class ProbeJob(job.Job):
        def handle_directory(self, kwdict):
            if not meta:
                meta.update(kwdict)

        def handle_url(self, url, kwdict):
            if not meta:
                meta.update(kwdict)
            items.append((url, dict(kwdict)))
            if len(items) >= PROBE_LIMIT:
                raise exception.TerminateExtraction()

        def handle_queue(self, url, kwdict):
            cls = kwdict.get("_extractor")
            extr = cls.from_url(url) if cls else extractor.find(url)
            if extr is not None:
                ProbeJob(extr, self).run()

    capture = _Capture()
    logging.getLogger().addHandler(capture)
    try:
        with _lock:
            _configure(os.getcwd(), [], url)
            extr = extractor.find(url)
            if extr is None:
                raise RuntimeError(_("CarryIt no sabe sacar imágenes de este sitio."))
            category = extr.category
            try:
                ProbeJob(extr).run()
            except exception.TerminateExtraction:
                pass
    finally:
        logging.getLogger().removeHandler(capture)
    if not items:
        raise RuntimeError(_clean_error(capture.messages))
    def is_image(u: str, kw: dict) -> bool:
        ext = kw.get("extension") or os.path.splitext(urllib.parse.urlparse(u).path)[1]
        return u.startswith("http") and "." + str(ext).lower().lstrip(".") in _IMAGE_EXT

    thumb = next((u for u, kw in items if is_image(u, kw)), None) or meta.get("display_url") or meta.get("thumbnail")
    uploader = _person(meta)
    if uploader.lower() == category.lower():
        uploader = ""                    # p. ej. la cuenta oficial «Bluesky» en Bluesky: no repetirlo
    return core.MediaInfo(
        url=url,
        title=_title(meta, category),
        uploader=uploader,
        thumbnail=thumb if isinstance(thumb, str) and thumb.startswith("http") else None,
        is_images=True,
        count=len(items),
        site=category.title(),
    )


def probe_thumbnail(url: str) -> core.MediaInfo:
    """Para videos (YouTube…): la «imagen» es la portada del video."""
    info = core.fetch_info(url, playlist=False)
    info.is_images = True
    info.thumb_only = True
    info.count = 1
    return info


# --------------------------------------------------------------------------- #
# Descarga
# --------------------------------------------------------------------------- #
def to_jpg(path: str) -> str:
    """Convierte WEBP/AVIF/… a JPG (las animadas se dejan como están). Devuelve la ruta final."""
    base, ext = os.path.splitext(path)
    if ext.lower() not in _CONVERT:
        return path
    try:
        from PIL import Image
        with Image.open(path) as im:
            if getattr(im, "n_frames", 1) > 1:
                return path
            if im.mode in ("RGBA", "LA", "P"):
                im = im.convert("RGBA")
                bg = Image.new("RGB", im.size, (255, 255, 255))
                bg.paste(im, mask=im.split()[-1])
                im = bg
            else:
                im = im.convert("RGB")
            target = base + ".jpg"
            n = 2
            while os.path.exists(target):
                target = f"{base} ({n}).jpg"
                n += 1
            im.save(target, "JPEG", quality=92, optimize=True)
        os.remove(path)
        return target
    except Exception:
        log.exception("No se pudo convertir a JPG: %s", path)
        return path


class ImageTask:
    """Descarga imágenes en un hilo y reporta eventos mediante `on_event(dict)`."""

    can_pause = False

    def __init__(self, options: core.DownloadOptions, on_event, resume_files=None) -> None:
        self.options = options
        self.on_event = on_event
        self._cancel = threading.Event()
        self.files: list[str] = []
        self.thread = threading.Thread(target=self._run, daemon=True)

    # misma interfaz que core.DownloadTask
    def start(self) -> None:
        self.thread.start()

    def cancel(self) -> None:
        self._cancel.set()

    def pause(self) -> None:
        self.cancel()

    @property
    def cancelled(self) -> bool:
        return self._cancel.is_set()

    @property
    def partial_files(self) -> set[str]:
        return set()

    def _add_file(self, path: str) -> None:
        if (self.options.image_format or "JPG").upper() == "JPG":
            path = to_jpg(path)
        self.files.append(path)
        self.on_event({"type": "file", "path": path})

    def _run(self) -> None:
        self.on_event({"type": "stage", "text": _("En cola…")})
        with core._slots:
            if self._cancel.is_set():
                self.on_event({"type": "cancelled"})
                return
            self.on_event({"type": "stage", "text": _("Conectando…")})
            _local.task = self       # las esperas de gallery-dl en este hilo responden a «Cancelar»
            try:
                os.makedirs(self.options.output_dir, exist_ok=True)
                if supported(self.options.url):
                    self._run_gallery()
                else:
                    self._run_thumbnail()
                if self._cancel.is_set():
                    self.on_event({"type": "cancelled"})
                else:
                    self.on_event({"type": "done", "files": list(self.files), "partial_errors": 0})
            except Exception as exc:
                if self._cancel.is_set():
                    self.on_event({"type": "cancelled"})
                else:
                    log.exception("Fallo al descargar imágenes de %s", self.options.url)
                    self.on_event({"type": "error", "message": str(exc)})
            finally:
                _local.task = None

    # -- portada de un video (YouTube y otros sitios de video) --
    def _run_thumbnail(self) -> None:
        import yt_dlp
        opts = core._apply_tools({"quiet": True, "no_warnings": True, "skip_download": True,
                                  "noplaylist": True, "logger": core._Logger()}, self.options.url)
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(self.options.url, download=False)
        except Exception as exc:
            raise RuntimeError(core._clean_error(str(exc))) from exc
        thumbs = [t for t in info.get("thumbnails") or [] if t.get("url")]
        thumbs.sort(key=lambda t: (t.get("preference") or 0, (t.get("width") or 0) * (t.get("height") or 0)))
        candidates = [t["url"] for t in reversed(thumbs)] or [info.get("thumbnail")]
        data, src = None, ""
        for u in candidates:
            if u and (data := core.fetch_thumbnail(u)):
                src = u
                break
        if not data:
            raise RuntimeError(_("Este video no tiene portada para descargar."))
        ext = os.path.splitext(urllib.parse.urlparse(src).path)[1].lower() or ".jpg"
        name = _safe(info.get("title") or info.get("id") or "portada")
        path = os.path.join(self.options.output_dir, name + ext)
        n = 2
        while os.path.exists(path):
            path = os.path.join(self.options.output_dir, f"{name} ({n}){ext}")
            n += 1
        with open(path, "wb") as fh:
            fh.write(data)
        self.on_event({"type": "progress", "title": info.get("title"), "stream": "image", "fraction": 1.0,
                       "index": None, "total": None})
        self._add_file(path)

    # -- fotos y galerías --
    def _run_gallery(self) -> None:
        _config, exception, extractor, job = _gdl()
        task = self

        # 1) ¿Cuántas imágenes son? Una sola va directo a la carpeta; varias, en una subcarpeta.
        self.on_event({"type": "stage", "text": _("Buscando las imágenes…")})
        info = probe(self.options.url)
        total = info.count
        meta_extr = extractor.find(self.options.url)
        folder = []
        if total > 1:
            name = " - ".join(x for x in (info.site, info.uploader, _post_id_from_url(self.options.url)) if x)
            folder = [_safe(name or info.title)]
        done_count = [0]

        class Output:
            def start(self, path): pass
            def skip(self, path):
                done_count[0] += 1
                if os.path.isfile(path):
                    task._add_file(path)

            def success(self, path):
                done_count[0] += 1
                task._add_file(path)

            def progress(self, bytes_total, bytes_downloaded, bytes_per_second):
                if task._cancel.is_set():
                    raise exception.TerminateExtraction()
                frac = (bytes_downloaded / bytes_total) if bytes_total else 0
                task.on_event({"type": "progress", "title": info.title, "stream": "image",
                               "index": min(done_count[0] + 1, total), "total": total,
                               "fraction": min((done_count[0] + frac) / max(total, 1), 1.0),
                               "speed": bytes_per_second})

        class Job(job.DownloadJob):
            def __init__(self, url, parent=None):
                super().__init__(url, parent)
                self.out = Output()

            def handle_url(self, url, kwdict):
                if task._cancel.is_set():
                    raise exception.TerminateExtraction()
                task.on_event({"type": "progress", "title": info.title, "stream": "image",
                               "index": min(done_count[0] + 1, total), "total": total,
                               "fraction": done_count[0] / max(total, 1)})
                super().handle_url(url, kwdict)

        capture = _Capture()
        logging.getLogger().addHandler(capture)
        try:
            with _lock:
                _configure(self.options.output_dir, folder, self.options.url)
                try:
                    status = Job(meta_extr or self.options.url).run()
                except exception.TerminateExtraction:
                    status = 0
        finally:
            logging.getLogger().removeHandler(capture)
        if not self.files and not self._cancel.is_set():
            raise RuntimeError(_clean_error(capture.messages) if status or capture.messages
                               else _("No se encontraron imágenes en este enlace."))


def _post_id_from_url(url: str) -> str:
    """Último tramo útil de la dirección (p. ej. el código de una publicación de Instagram)."""
    parts = [p for p in urllib.parse.urlparse(url).path.split("/") if p]
    return parts[-1] if parts else ""
