"""Interfaz de escritorio (CustomTkinter)."""
from __future__ import annotations

import io
import itertools
import os
import queue
import subprocess
import sys
import threading
import time
import webbrowser
from tkinter import filedialog, messagebox

import customtkinter as ctk
from PIL import Image

from . import APP_NAME, AUTHOR, GITHUB_REPO, __version__, core, resource, updater
from .i18n import _
from .settings import Settings

# Identidad: negro + dorado (ver tools/branding.py y resources/theme.json).
ACCENT = ("#FFB300", "#FFB300")
ACCENT_HOVER = ("#FF9100", "#FF9100")
ACCENT_TEXT = "#111111"          # texto sobre botones dorados
OUTLINE_TEXT = ("gray10", "gray90")
MUTED = ("gray40", "gray65")
OK_COLOR = ("#2E7D32", "#66BB6A")
ERR_COLOR = ("#C62828", "#EF5350")
THUMB_SIZE = (208, 117)

# Textos en pantalla (traducidos). Lo que se guarda en las preferencias son códigos, no estos textos.
BEST = _("Mejor calidad")
COMPAT = _("Compatible con todo (hasta 1080p)")   # solo MP4: H.264 + AAC
HEIGHT_LABELS = {2160: "2160p (4K)", 1440: "1440p (2K)", 1080: "1080p (Full HD)", 720: "720p (HD)"}
LOSSLESS_LABEL = _("Sin pérdida")
SUBS_LABELS = {"none": _("Sin subtítulos"), "es": _("Español"), "en": _("Inglés"), "es_en": _("Español e inglés")}
MODE_LABELS = {"video": _("Video"), "audio": _("Solo audio"), "images": _("Imágenes")}
IMAGE_QUALITY = _("Original del sitio")


def images_probe_limit() -> int:
    from . import images
    return images.PROBE_LIMIT


def height_label(h: int) -> str:
    return HEIGHT_LABELS.get(h, f"{h}p")


def label_height(label: str) -> int | None:
    """Texto o código de calidad -> altura (None = la mejor / compatible)."""
    if label in (BEST, COMPAT, "best", "compat", "Mejor calidad"):
        return None
    try:
        return int(label.split("p")[0])
    except ValueError:
        return None


def quality_code(label: str) -> str:
    """Texto del menú de calidad -> código que se guarda ("compat", "best" o "1080")."""
    if label == COMPAT:
        return "compat"
    h = label_height(label)
    return "best" if h is None else str(h)


def quality_label(code: str, video_format: str = "MP4") -> str:
    """Código guardado -> texto del menú (acepta también los textos antiguos)."""
    if code == "compat":
        return COMPAT if video_format == "MP4" else BEST
    h = label_height(code)
    return BEST if h is None else height_label(h)


def fmt_bytes(n: float | None) -> str:
    if not n:
        return "?"
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"


def fmt_time(sec: float | None) -> str:
    if sec is None:
        return "--:--"
    sec = int(sec)
    h, rem = divmod(sec, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


def shorten(text: str, limit: int = 70) -> str:
    return text if len(text) <= limit else text[: limit - 1] + "…"


def shorten_path(path: str, limit: int = 70) -> str:
    return path if len(path) <= limit else "…" + path[-(limit - 1):]


def open_path(path: str, select: bool = False) -> None:
    try:
        if select and os.path.exists(path) and os.name == "nt":
            subprocess.Popen(["explorer", f"/select,{os.path.normpath(path)}"])
        else:
            folder = path if os.path.isdir(path) else os.path.dirname(path)
            os.startfile(folder) if os.name == "nt" else subprocess.Popen(["xdg-open", folder])
    except OSError as exc:
        messagebox.showerror(APP_NAME, _("No se pudo abrir:") + f"\n{exc}")


def set_window_icon(win) -> None:
    """Asigna el ícono a la ventana en el tamaño exacto que usa Windows.

    Tkinter entrega siempre la versión de 32 px y Windows la achica mal a 24 px en la barra de
    tareas (se ve pixeleada). Aquí se carga del .ico el cuadro justo: 24 px × escala para la barra
    de tareas y 16 px × escala para la barra de título.
    """
    if os.name != "nt":
        return
    try:
        import ctypes
        from ctypes import wintypes
        user32 = ctypes.windll.user32
        user32.GetParent.restype = wintypes.HWND
        user32.LoadImageW.restype = wintypes.HANDLE
        user32.LoadImageW.argtypes = [wintypes.HINSTANCE, wintypes.LPCWSTR, wintypes.UINT,
                                      ctypes.c_int, ctypes.c_int, wintypes.UINT]
        user32.SendMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
        hwnd = user32.GetParent(win.winfo_id())
        dpi = user32.GetDpiForWindow(hwnd) or 96
        big = round(24 * dpi / 96)                                # botón de la barra de tareas (Windows 11)
        small = user32.GetSystemMetricsForDpi(49, dpi) or 16      # SM_CXSMICON: barra de título
        path = resource("icon.ico")
        h_big = user32.LoadImageW(None, path, 1, big, big, 0x10)  # IMAGE_ICON, LR_LOADFROMFILE
        h_small = user32.LoadImageW(None, path, 1, small, small, 0x10)
        if h_big:
            user32.SendMessageW(hwnd, 0x80, 1, h_big)             # WM_SETICON, ICON_BIG
        if h_small:
            user32.SendMessageW(hwnd, 0x80, 0, h_small)           # WM_SETICON, ICON_SMALL
        win._carryit_icons = (h_big, h_small)                     # que no se liberen
    except Exception:
        pass


def work_area(win) -> tuple[int, int, int, int]:
    """Espacio libre (sin la barra de tareas) del monitor donde está la ventana, en píxeles reales."""
    if os.name == "nt":
        try:
            import ctypes
            from ctypes import wintypes

            class MONITORINFO(ctypes.Structure):
                _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", wintypes.RECT),
                            ("rcWork", wintypes.RECT), ("dwFlags", wintypes.DWORD)]

            user32 = ctypes.windll.user32
            user32.GetParent.restype = wintypes.HWND
            user32.MonitorFromWindow.restype = wintypes.HMONITOR
            user32.MonitorFromWindow.argtypes = [wintypes.HWND, wintypes.DWORD]
            hwnd = user32.GetParent(win.winfo_id()) or win.winfo_id()
            monitor = user32.MonitorFromWindow(hwnd, 2)          # MONITOR_DEFAULTTONEAREST
            info = MONITORINFO()
            info.cbSize = ctypes.sizeof(MONITORINFO)
            if user32.GetMonitorInfoW(monitor, ctypes.byref(info)):
                r = info.rcWork
                return r.left, r.top, r.right, r.bottom
        except Exception:
            pass
    return 0, 0, win.winfo_screenwidth(), win.winfo_screenheight() - 48


def available_size(win) -> tuple[float, float]:
    """Tamaño máximo (en unidades de la interfaz, ya descontada la escala de Windows) para una ventana."""
    scale = ctk.ScalingTracker.get_window_scaling(win)
    left, top, right, bottom = work_area(win)
    frame_w, frame_h = round(16 * scale), round(40 * scale)    # bordes y barra de título
    return (right - left - frame_w) / scale, (bottom - top - frame_h) / scale


def fit_window(win, width: int, height: int, parent=None, min_size: tuple[int, int] | None = None) -> tuple[int, int]:
    """Da a la ventana el tamaño pedido si cabe en la pantalla; si no, la achica. La centra
    (sobre `parent` si se indica) sin que se salga de la pantalla ni quede detrás de la barra de tareas."""
    scale = ctk.ScalingTracker.get_window_scaling(win)
    left, top, right, bottom = work_area(parent or win)
    avail_w, avail_h = available_size(parent or win)
    w, h = int(min(width, avail_w)), int(min(height, avail_h))
    pw, ph = round(w * scale), round(h * scale)                # tamaño real en píxeles
    frame_h = round(40 * scale)
    if parent is not None and parent.winfo_ismapped():
        x = parent.winfo_rootx() + (parent.winfo_width() - pw) // 2
        y = parent.winfo_rooty() + (parent.winfo_height() - ph) // 2 - frame_h // 2
    else:
        x = left + (right - left - pw) // 2
        y = top + (bottom - top - ph - frame_h) // 2
    x = max(left, min(x, right - pw - round(16 * scale)))
    y = max(top, min(y, bottom - ph - frame_h))
    win.geometry(f"{w}x{h}+{x}+{y}")
    if min_size:
        win.minsize(min(min_size[0], w), min(min_size[1], h))
    return w, h


def notify_attention(win) -> None:
    """Hace parpadear el botón de la barra de tareas (hasta que el usuario abre la ventana) y suena un aviso."""
    if os.name != "nt":
        win.bell()
        return
    try:
        import ctypes
        import winsound
        from ctypes import wintypes

        class FLASHWINFO(ctypes.Structure):
            _fields_ = [("cbSize", wintypes.UINT), ("hwnd", wintypes.HWND), ("dwFlags", wintypes.DWORD),
                        ("uCount", wintypes.UINT), ("dwTimeout", wintypes.DWORD)]

        user32 = ctypes.windll.user32
        user32.GetParent.restype = wintypes.HWND
        hwnd = user32.GetParent(win.winfo_id())
        # FLASHW_TRAY | FLASHW_TIMERNOFG: parpadea hasta que la ventana pasa al frente.
        info = FLASHWINFO(ctypes.sizeof(FLASHWINFO), hwnd, 0x2 | 0xC, 0, 0)
        user32.FlashWindowEx(ctypes.byref(info))
        winsound.MessageBeep(winsound.MB_OK)
    except Exception:
        pass


def outline_button(master, text: str, command, **kw) -> ctk.CTkButton:
    """Botón secundario: solo borde, sin relleno dorado."""
    opts = dict(fg_color="transparent", border_width=1, text_color=OUTLINE_TEXT,
                hover_color=("#D9D9DE", "#26262B"))
    opts.update(kw)
    return ctk.CTkButton(master, text=text, command=command, **opts)


class SegmentToggle(ctk.CTkFrame):
    """Selector de dos o más opciones: la elegida en dorado con texto oscuro, las demás con borde.

    `values` es {código: texto en pantalla}; get()/set() trabajan con el código.
    """

    def __init__(self, master, values: dict[str, str], command=None, height: int = 32) -> None:
        super().__init__(master, fg_color="transparent")
        self._command = command
        self._value = next(iter(values))
        self._buttons: dict[str, ctk.CTkButton] = {}
        for i, (v, label) in enumerate(values.items()):
            b = ctk.CTkButton(self, text=label, height=height, width=110, corner_radius=6,
                              command=lambda v=v: self._click(v))
            b.grid(row=0, column=i, padx=(0 if i == 0 else 4, 0))
            self._buttons[v] = b
        self._paint()

    def _click(self, value: str) -> None:
        if value != self._value:
            self.set(value)
            if self._command:
                self._command(value)

    def _paint(self) -> None:
        for v, b in self._buttons.items():
            if v == self._value:
                b.configure(fg_color=ACCENT, hover_color=ACCENT_HOVER, text_color=ACCENT_TEXT, border_width=0)
            else:
                b.configure(fg_color="transparent", hover_color=("#D9D9DE", "#26262B"),
                            text_color=OUTLINE_TEXT, border_width=1)

    def get(self) -> str:
        return self._value

    def set(self, value: str) -> None:
        if value in self._buttons:
            self._value = value
            self._paint()


# --------------------------------------------------------------------------- #
class PlaylistDialog(ctk.CTkToplevel):
    """Ventana para marcar qué videos de una lista se descargan."""

    BATCH = 60  # casillas creadas por tanda, para que listas grandes no congelen la ventana

    def __init__(self, app: "App", info: core.MediaInfo, selected: set[int], on_accept) -> None:
        super().__init__(app)
        self.title(_("Elegir videos") + f" · {shorten(info.title, 50)}")
        fit_window(self, 680, 600, parent=app, min_size=(520, 380))
        self.transient(app)
        self.on_accept = on_accept
        self.entries = info.entries
        self.vars: dict[int, ctk.BooleanVar] = {}
        self.boxes: dict[int, ctk.CTkCheckBox] = {}

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        top = ctk.CTkFrame(self, fg_color="transparent")
        top.grid(row=0, column=0, sticky="ew", padx=16, pady=(16, 8))
        top.grid_columnconfigure(0, weight=1)
        self.search = ctk.CTkEntry(top, placeholder_text=_("Buscar en la lista…"))
        self.search.grid(row=0, column=0, sticky="ew")
        self.search.bind("<KeyRelease>", lambda _e: self._apply_filter())
        for col, (text, value) in enumerate(((_("Todos"), True), (_("Ninguno"), False)), start=1):
            ctk.CTkButton(top, text=text, width=80, fg_color="transparent", border_width=1,
                          text_color=("gray10", "gray90"),
                          command=lambda v=value: self._set_visible(v)).grid(row=0, column=col, padx=(8, 0))

        self.list = ctk.CTkScrollableFrame(self, corner_radius=10)
        self.list.grid(row=1, column=0, sticky="nsew", padx=16)

        bottom = ctk.CTkFrame(self, fg_color="transparent")
        bottom.grid(row=2, column=0, sticky="ew", padx=16, pady=12)
        bottom.grid_columnconfigure(0, weight=1)
        self.count_lbl = ctk.CTkLabel(bottom, text="", text_color=MUTED, anchor="w")
        self.count_lbl.grid(row=0, column=0, sticky="w")
        ctk.CTkButton(bottom, text=_("Cancelar"), width=100, fg_color="transparent", border_width=1,
                      text_color=("gray10", "gray90"), command=self.destroy).grid(row=0, column=1, padx=(8, 0))
        ctk.CTkButton(bottom, text=_("Aceptar"), width=100, fg_color=ACCENT, hover_color=ACCENT_HOVER,
                      text_color=ACCENT_TEXT,
                      command=self._accept).grid(row=0, column=2, padx=(8, 0))

        for idx, _title, _dur in self.entries:
            var = ctk.BooleanVar(value=idx in selected)
            var.trace_add("write", lambda *_args: self._update_count())
            self.vars[idx] = var
        self._update_count()
        self._build_batch(0)
        self.after(100, self._grab)
        self.after(300, lambda: set_window_icon(self))

    def _grab(self) -> None:
        try:
            self.lift()
            self.focus_force()
            self.grab_set()
        except Exception:
            pass

    def _build_batch(self, start: int) -> None:
        if not self.winfo_exists():
            return
        for idx, title, dur in self.entries[start:start + self.BATCH]:
            label = f"{idx:03d}   {shorten(title, 72)}"
            if dur:
                label += f"   ({fmt_time(dur)})"
            box = ctk.CTkCheckBox(self.list, text=label, variable=self.vars[idx])
            if title in core.UNAVAILABLE_TITLES:
                box.configure(text_color=MUTED)
            self.boxes[idx] = box
            if self._matches(title):
                box.pack(fill="x", anchor="w", padx=8, pady=3)
        if start + self.BATCH < len(self.entries):
            self.after(10, lambda: self._build_batch(start + self.BATCH))

    def _matches(self, title: str) -> bool:
        q = self.search.get().strip().lower()
        return not q or q in title.lower()

    def _apply_filter(self) -> None:
        for box in self.boxes.values():
            box.pack_forget()
        for idx, title, _dur in self.entries:
            box = self.boxes.get(idx)
            if box is not None and self._matches(title):
                box.pack(fill="x", anchor="w", padx=8, pady=3)

    def _set_visible(self, value: bool) -> None:
        for idx, title, _dur in self.entries:
            if self._matches(title):
                self.vars[idx].set(value)

    def _selected(self) -> set[int]:
        return {i for i, v in self.vars.items() if v.get()}

    def _update_count(self) -> None:
        self.count_lbl.configure(text=_("Seleccionados: {n} de {total}").format(
            n=len(self._selected()), total=len(self.entries)))

    def _accept(self) -> None:
        self.on_accept(self._selected())
        self.destroy()


# --------------------------------------------------------------------------- #
class DownloadRow(ctk.CTkFrame):
    def __init__(self, master, app: "App", task: core.DownloadTask, title: str, badge: str) -> None:
        super().__init__(master, corner_radius=10)
        self.app = app
        self.task = task
        self.state = "running"
        self.files: list[str] = []
        self._indeterminate = False

        self.grid_columnconfigure(0, weight=1)
        self.title_lbl = ctk.CTkLabel(self, text=shorten(title), anchor="w",
                                      font=ctk.CTkFont(size=13, weight="bold"))
        self.title_lbl.grid(row=0, column=0, sticky="ew", padx=(12, 6), pady=(8, 0))
        ctk.CTkLabel(self, text=badge, text_color=MUTED, anchor="e").grid(
            row=0, column=1, sticky="e", padx=12, pady=(8, 0))

        self.bar = ctk.CTkProgressBar(self, height=8, progress_color=ACCENT)
        self.bar.set(0)
        self.bar.grid(row=1, column=0, columnspan=2, sticky="ew", padx=12, pady=6)

        self.status = ctk.CTkLabel(self, text=_("En cola…"), anchor="w", text_color=MUTED)
        self.status.grid(row=2, column=0, sticky="ew", padx=12, pady=(0, 8))
        actions = ctk.CTkFrame(self, fg_color="transparent")
        actions.grid(row=2, column=1, sticky="e", padx=12, pady=(0, 8))
        # Solo aparece si la descarga falla: junta los datos del problema para enviarlos.
        self.report_btn = outline_button(actions, _("Copiar informe"), self._copy_report, width=110, height=26)
        self.btn = outline_button(actions, _("Cancelar"), self._on_button, width=104, height=26)
        self.btn.pack(side="right")
        # Pausar: solo mientras descarga (al reanudar sigue desde lo ya bajado).
        self.pause_btn = outline_button(actions, _("Pausar"), self._pause, width=80, height=26)
        if getattr(task, "can_pause", True):
            self.pause_btn.pack(side="right", padx=(0, 6))
        self._title_locked = not title.startswith("http")
        self.error_message = ""
        self._last_fraction = 0.0

    # -- estado visual --
    def _busy(self, on: bool) -> None:
        if on and not self._indeterminate:
            self.bar.configure(mode="indeterminate")
            self.bar.start()
            self._indeterminate = True
        elif not on and self._indeterminate:
            self.bar.stop()
            self.bar.configure(mode="determinate")
            self._indeterminate = False

    def handle(self, ev: dict) -> None:
        kind = ev["type"]
        if kind == "stage":
            self._busy(True)
            self.status.configure(text=ev["text"], text_color=MUTED)
        elif kind == "progress":
            if ev.get("title") and not self._title_locked:
                self.title_lbl.configure(text=shorten(ev["title"]))
            prefix = ""
            if ev.get("index") and ev.get("total"):
                prefix = f"({ev['index']}/{ev['total']}) {shorten(ev.get('title') or '', 40)} · "
            frac = ev.get("fraction")
            what = {"audio": _("Descargando audio"), "image": _("Descargando imágenes")}.get(
                ev["stream"], _("Descargando video"))
            if frac is None:
                self._busy(True)
                text = f"{prefix}{what}… {fmt_bytes(ev.get('downloaded'))}"
            else:
                self._busy(False)
                self.bar.set(frac)
                self._last_fraction = frac
                text = f"{prefix}{what} · {frac * 100:.0f}%"
                if ev.get("total_bytes"):
                    text += " " + _("de {size}").format(size=fmt_bytes(ev["total_bytes"]))
                if ev.get("speed"):
                    text += f" · {fmt_bytes(ev['speed'])}/s · " + _("quedan {time}").format(
                        time=fmt_time(ev.get("eta")))
            self.status.configure(text=text, text_color=MUTED)
        elif kind == "file":
            self.files.append(ev["path"])
        elif kind == "done":
            self._busy(False)
            self.bar.set(1)
            self.state = "done"
            self.pause_btn.pack_forget()
            self.files = list(ev["files"])     # rutas finales (p. ej. tras renombrar con título y artista)
            n = len(ev["files"])
            text = _("Completado") if n <= 1 else _("Completado · {n} archivos").format(n=n)
            if ev.get("partial_errors"):
                text += " · " + _("{n} con error").format(n=ev["partial_errors"])
            if ev.get("subs_failed"):
                text += " · " + _("sin subtítulos (el sitio no los tiene en ese idioma o no los entregó)")
            if n == 1 and not self._title_locked:
                self.title_lbl.configure(text=shorten(os.path.basename(ev["files"][0])))
            self.status.configure(text=text, text_color=OK_COLOR)
            self.btn.configure(text=_("Mostrar") if n == 1 else _("Abrir carpeta"))
            self.app.on_task_finished(self, ev)
        elif kind == "error":
            self._busy(False)
            self.bar.set(0)
            self.state = "error"
            self.pause_btn.pack_forget()
            self.error_message = ev["message"]
            self.status.configure(text=_("Error: {message}").format(message=ev["message"]), text_color=ERR_COLOR)
            self.btn.configure(text=_("Reintentar"))
            self.report_btn.pack(side="right", padx=(0, 6))
            self.app.on_task_finished(self, ev)
        elif kind == "cancelled":
            self._busy(False)
            self.state = "cancelled"
            self.pause_btn.pack_forget()
            self.status.configure(text=_("Cancelado"), text_color=MUTED)
            self.btn.configure(text=_("Quitar"), state="normal")
        elif kind == "paused":
            self._busy(False)
            self.bar.set(self._last_fraction)   # se ve hasta dónde iba
            self.state = "paused"
            self.pause_btn.pack_forget()
            self.status.configure(text=_("Pausado · lo descargado se conserva"), text_color=MUTED)
            self.btn.configure(text=_("Reanudar"), state="normal")

    def _pause(self) -> None:
        if self.state == "running":
            self.task.pause()
            self.pause_btn.configure(text=_("Pausando…"), state="disabled")

    def _copy_report(self) -> None:
        from . import report
        self.clipboard_clear()
        self.clipboard_append(report.build(self.error_message, self.task.options))
        self.report_btn.configure(text=_("¡Copiado!"))
        self.after(2000, lambda: self.report_btn.winfo_exists()
                   and self.report_btn.configure(text=_("Copiar informe")))

    def _on_button(self) -> None:
        if self.state == "running":
            self.task.cancel()
            self.btn.configure(text=_("Cancelando…"), state="disabled")
        elif self.state == "done":
            if len(self.files) == 1:
                open_path(self.files[0], select=True)
            else:
                target = os.path.dirname(self.files[0]) if self.files else self.task.options.output_dir
                open_path(target)
        elif self.state == "error":
            self.app.retry(self)
        elif self.state == "paused":
            self.app.resume(self)
        else:
            self.app.remove_row(self)


# --------------------------------------------------------------------------- #
class App(ctk.CTk):
    def __init__(self) -> None:
        self.settings = Settings.load()
        ctk.set_appearance_mode(self.settings.appearance)
        try:
            ctk.set_default_color_theme(resource("theme.json"))
        except Exception:
            ctk.set_default_color_theme("blue")
        super().__init__()

        self.title(APP_NAME)
        # Tamaño según el espacio libre real de la pantalla (resolución + escala de Windows).
        # Con poco alto (p. ej. laptop 1080p al 150 %) se usa un diseño compacto para que todo quepa.
        _avail_w, avail_h = available_size(self)
        self.compact = avail_h < 760
        self.thumb_size = (160, 90) if self.compact else THUMB_SIZE
        self._pad = 3 if self.compact else 6
        fit_window(self, 940, 820, min_size=(760, 600))
        self._set_icon()

        self.events: queue.Queue = queue.Queue()
        self.rows: dict[int, DownloadRow] = {}
        self._ids = itertools.count(1)
        self._analyze_token = 0
        self._analyzed: core.MediaInfo | None = None
        self._selection: set[int] | None = None  # videos marcados de la lista (None = todos)
        self._thumb_image = None
        self._pending_update: str | None = None
        self._app_release: dict | None = None
        self._last_clip = ""          # último enlace copiado que ya se tomó (para no repetirlo)
        self._tags: dict | None = None  # título y artista elegidos para el audio actual
        core.set_max_parallel(self.settings.max_parallel)
        core.set_cookies_browser(self.settings.cookies_browser or None)

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(4, weight=1)
        self._build_header()
        self._build_url_bar()
        self._build_info_card()
        self._build_options()
        self._build_downloads()
        self._build_footer()

        self._refresh_mode()
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.after(80, self._poll)
        self.after(200, self.url_entry.focus_set)
        if self.settings.auto_update and time.time() - self.settings.last_update_check > updater.CHECK_INTERVAL:
            self.after(2500, lambda: self._check_updates(manual=False))
        if not self.settings.welcome_shown:
            self.after(700, self._show_welcome)
        else:
            self.after(900, self._check_clipboard)
        # Al volver a la ventana (por ejemplo, después de copiar un enlace en el navegador).
        self.bind("<FocusIn>", lambda e: self._check_clipboard() if e.widget is self else None)

    # ------------------------------------------------------------------ UI --
    def _set_icon(self) -> None:
        try:
            ico = resource("icon.ico")
            self.iconbitmap(ico)
            # CTk vuelve a poner su ícono tras iniciar; después se asigna el nuestro en el tamaño exacto.
            self.after(300, lambda: self.iconbitmap(ico))
            self.after(450, lambda: set_window_icon(self))
        except Exception:
            pass

    def _build_header(self) -> None:
        f = ctk.CTkFrame(self, fg_color="transparent")
        f.grid(row=0, column=0, sticky="ew", padx=20, pady=(8, 2) if self.compact else (16, 6))
        f.grid_columnconfigure(1, weight=1)
        try:
            self._logo = ctk.CTkImage(light_image=Image.open(resource("logo_symbol_light.png")),
                                      dark_image=Image.open(resource("logo_symbol.png")), size=(56, 56))
            ctk.CTkLabel(f, text="", image=self._logo).grid(row=0, column=0, rowspan=2, padx=(0, 12))
        except Exception:
            pass
        name = ctk.CTkFrame(f, fg_color="transparent")
        name.grid(row=0, column=1, sticky="sw")
        title_font = ctk.CTkFont(size=26, weight="bold")
        ctk.CTkLabel(name, text="Carry", font=title_font).pack(side="left")
        ctk.CTkLabel(name, text="It", font=title_font, text_color=("#D98200", "#FFB300")).pack(side="left")
        ctk.CTkLabel(f, text=_("Descarga videos, audio o imágenes, en la calidad que quieras"), text_color=MUTED,
                     anchor="w").grid(row=1, column=1, sticky="nw")
        buttons = ctk.CTkFrame(f, fg_color="transparent")
        buttons.grid(row=0, column=2, rowspan=2, padx=(8, 0))
        outline_button(buttons, _("Historial"), self._open_history, width=96).pack(side="left")
        outline_button(buttons, _("Ajustes"), self._open_settings, width=90).pack(side="left", padx=(8, 0))

    def _build_url_bar(self) -> None:
        f = ctk.CTkFrame(self, fg_color="transparent")
        f.grid(row=1, column=0, sticky="ew", padx=20, pady=self._pad)
        f.grid_columnconfigure(0, weight=1)
        self.url_entry = ctk.CTkEntry(
            f, height=40, font=ctk.CTkFont(size=14),
            placeholder_text=_("Pega un enlace (YouTube, Facebook, TikTok, X…) o escribe qué quieres buscar"))
        self.url_entry.grid(row=0, column=0, sticky="ew")
        self.url_entry.bind("<Return>", lambda _e: self.analyze())
        # El botón dice «Buscar» si lo escrito no es un enlace.
        self.url_entry.bind("<KeyRelease>", lambda _e: self._update_action_label())
        ctk.CTkButton(f, text=_("Pegar"), width=80, height=40, fg_color="transparent", border_width=1,
                      text_color=("gray10", "gray90"), command=self._paste).grid(row=0, column=1, padx=(8, 0))
        self.analyze_btn = ctk.CTkButton(f, text=_("Analizar"), width=100, height=40, command=self.analyze)
        self.analyze_btn.grid(row=0, column=2, padx=(8, 0))

    def _build_info_card(self) -> None:
        card = ctk.CTkFrame(self, corner_radius=12)
        card.grid(row=2, column=0, sticky="ew", padx=20, pady=self._pad)
        card.grid_columnconfigure(1, weight=1)
        self.thumb_lbl = ctk.CTkLabel(card, text="", width=self.thumb_size[0], height=self.thumb_size[1],
                                      fg_color=("#D9D9DE", "#1F1F23"), corner_radius=8)
        self.thumb_lbl.grid(row=0, column=0, rowspan=3, padx=12, pady=8 if self.compact else 12)
        self.info_title = ctk.CTkLabel(card, text=_("Ningún enlace analizado"), anchor="w", justify="left",
                                       font=ctk.CTkFont(size=16, weight="bold"), wraplength=560)
        self.info_title.grid(row=0, column=1, sticky="sw", padx=(0, 12), pady=(14, 0))
        self.info_meta = ctk.CTkLabel(card, text=_("Pega un enlace o escribe el nombre de un video para buscarlo."),
                                      anchor="w", justify="left", text_color=MUTED, wraplength=560)
        self.info_meta.grid(row=1, column=1, sticky="nw", padx=(0, 12), pady=(2, 0))
        self.pick_btn = ctk.CTkButton(card, text=_("Elegir videos…"), width=150, command=self._open_picker)
        # Se muestra solo cuando el enlace analizado es una lista.
        self.tags_btn = outline_button(card, _("Editar título y artista…"), self._open_tags, width=190)
        # Se muestra solo en «Solo audio» con un video suelto analizado.

    def _open_picker(self) -> None:
        info = self._analyzed
        if not info or not info.is_playlist:
            return
        if not info.entries:
            messagebox.showinfo(APP_NAME, _("No se pudo obtener la lista de videos de este enlace."))
            return
        selected = self._selection if self._selection is not None else {i for i, _t, _d in info.entries}
        PlaylistDialog(self, info, selected, self._set_selection)

    def _set_selection(self, selected: set[int]) -> None:
        info = self._analyzed
        if not info:
            return
        everything = {i for i, _t, _d in info.entries}
        self._selection = None if selected == everything else selected
        self._update_pick_label()

    def _update_pick_label(self) -> None:
        info = self._analyzed
        if not info or not info.is_playlist:
            self.pick_btn.grid_remove()
            return
        total = len(info.entries) or info.count
        n = total if self._selection is None else len(self._selection)
        self.pick_btn.configure(text=_("Elegir videos ({n} de {total})…").format(n=n, total=total))
        self.pick_btn.grid(row=2, column=1, sticky="nw", padx=(0, 12), pady=(8, 12))

    def _build_options(self) -> None:
        card = ctk.CTkFrame(self, corner_radius=12)
        card.grid(row=3, column=0, sticky="ew", padx=20, pady=self._pad)
        card.grid_columnconfigure(5, weight=1)
        top = (8, 3) if self.compact else (12, 6)
        pad = {"padx": (12, 4), "pady": top}

        ctk.CTkLabel(card, text=_("Descargar como")).grid(row=0, column=0, sticky="w", **pad)
        self.mode_btn = SegmentToggle(card, values=MODE_LABELS, command=lambda _v: self._on_mode_change())
        self.mode_btn.set("audio" if self.settings.mode == "audio" else "video")
        self.mode_btn.grid(row=0, column=1, sticky="w", padx=4, pady=top)

        ctk.CTkLabel(card, text=_("Formato")).grid(row=0, column=2, sticky="e", padx=(16, 4), pady=top)
        self.format_menu = ctk.CTkOptionMenu(card, values=core.VIDEO_FORMATS, width=96,
                                             command=lambda _v: self._on_format_change())
        self.format_menu.grid(row=0, column=3, sticky="w", padx=4, pady=top)

        ctk.CTkLabel(card, text=_("Calidad")).grid(row=0, column=4, sticky="e", padx=(16, 4), pady=top)
        self.quality_menu = ctk.CTkOptionMenu(card, values=[BEST], width=250,
                                              command=lambda _v: self._save_choices())
        self.quality_menu.grid(row=0, column=5, sticky="w", padx=4, pady=top)

        extras = ctk.CTkFrame(card, fg_color="transparent")
        extras.grid(row=1, column=0, columnspan=6, sticky="ew", padx=12, pady=self._pad)
        extras.grid_columnconfigure(0, weight=1)
        self.playlist_var = ctk.BooleanVar(value=self.settings.playlist)
        self.playlist_check = ctk.CTkCheckBox(extras, text=_("Si el enlace es de una lista, descargarla completa"),
                                              variable=self.playlist_var, command=self._on_playlist_toggle)
        self.playlist_check.grid(row=0, column=0, sticky="w")
        # Subtítulos: solo en modo video.
        self.subs_frame = ctk.CTkFrame(extras, fg_color="transparent")
        self.subs_frame.grid(row=0, column=1, sticky="e")
        ctk.CTkLabel(self.subs_frame, text=_("Subtítulos")).pack(side="left", padx=(0, 6))
        self.subs_menu = ctk.CTkOptionMenu(self.subs_frame, values=list(SUBS_LABELS.values()), width=170,
                                           command=lambda _v: self._save_choices())
        self.subs_menu.set(SUBS_LABELS.get(self.settings.subtitles, SUBS_LABELS["none"]))
        self.subs_menu.pack(side="left")

        # Recortar: descargar solo una parte del video o del audio.
        trim = ctk.CTkFrame(card, fg_color="transparent")
        trim.grid(row=2, column=0, columnspan=6, sticky="ew", padx=12, pady=self._pad)
        self.trim_var = ctk.BooleanVar(value=False)
        self.trim_check = ctk.CTkCheckBox(trim, text=_("Solo una parte:"), variable=self.trim_var,
                                          command=self._on_trim_toggle)
        self.trim_check.pack(side="left")
        ctk.CTkLabel(trim, text=_("desde")).pack(side="left", padx=(10, 4))
        self.trim_from = ctk.CTkEntry(trim, width=80, placeholder_text="0:00")
        self.trim_from.pack(side="left")
        ctk.CTkLabel(trim, text=_("hasta")).pack(side="left", padx=(10, 4))
        self.trim_to = ctk.CTkEntry(trim, width=80, placeholder_text="1:30")
        self.trim_to.pack(side="left")
        self.trim_hint = ctk.CTkLabel(trim, text=_("minutos:segundos, por ejemplo 1:20"), text_color=MUTED)
        self.trim_hint.pack(side="left", padx=(10, 0))
        self._on_trim_toggle()

        folder = ctk.CTkFrame(card, fg_color="transparent")
        folder.grid(row=3, column=0, columnspan=6, sticky="ew", padx=12, pady=self._pad)
        folder.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(folder, text=_("Guardar en")).grid(row=0, column=0, padx=(0, 8))
        self.folder_lbl = ctk.CTkLabel(folder, text=" " + shorten_path(self.settings.output_dir), anchor="w",
                                       fg_color=("#D9D9DE", "#1F1F23"), corner_radius=6, height=30)
        self.folder_lbl.grid(row=0, column=1, sticky="ew")
        outline_button(folder, _("Cambiar…"), self._choose_folder, width=90).grid(row=0, column=2, padx=(8, 0))
        ctk.CTkButton(folder, text=_("Abrir"), width=70, fg_color="transparent", border_width=1,
                      text_color=("gray10", "gray90"),
                      command=lambda: open_path(self.settings.output_dir)).grid(row=0, column=3, padx=(8, 0))

        self.download_btn = ctk.CTkButton(card, text=_("Descargar"), height=38 if self.compact else 44, fg_color=ACCENT,
                                          hover_color=ACCENT_HOVER, text_color=ACCENT_TEXT,
                                          font=ctk.CTkFont(size=16, weight="bold"), command=self.download)
        self.download_btn.grid(row=4, column=0, columnspan=6, sticky="ew", padx=12,
                               pady=(4, 8) if self.compact else (8, 12))

    def _on_trim_toggle(self) -> None:
        state = "normal" if self.trim_var.get() else "disabled"
        self.trim_from.configure(state=state)
        self.trim_to.configure(state=state)

    def _read_section(self) -> tuple[float, float] | None | bool:
        """(inicio, fin) si «Solo una parte» está marcado y es válido; None si no; False si hay error."""
        if not self.trim_var.get():
            return None
        start = core.parse_time(self.trim_from.get() or "0")
        end = core.parse_time(self.trim_to.get())
        info = self._analyzed
        if end is None and info and info.duration:
            end = float(info.duration)
        if start is None or end is None or end <= start:
            messagebox.showwarning(APP_NAME, _("Revisa «Solo una parte»: escribe el inicio y el final como "
                                               "minutos:segundos (por ejemplo, desde 1:20 hasta 4:05)."))
            return False
        if info and info.duration and start >= info.duration:
            messagebox.showwarning(APP_NAME, _("El video dura {time}; el inicio tiene que ser menor.").format(
                time=core.fmt_clock(info.duration)))
            return False
        return (start, end)

    def _open_tags(self) -> None:
        from .dialogs import TagsDialog
        info = self._analyzed
        if not info:
            return
        current = self._tags or {"title": info.track or info.title, "artist": info.artist or info.uploader}
        TagsDialog(self, current, self._set_tags)

    def _set_tags(self, tags: dict | None) -> None:
        self._tags = tags
        self._update_tags_button()

    def _update_tags_button(self) -> None:
        info = self._analyzed
        if self.mode != "audio" or not info or info.is_playlist:
            self.tags_btn.grid_remove()
            return
        self.tags_btn.configure(text=_("Título y artista ✓") if self._tags else _("Editar título y artista…"))
        self.tags_btn.grid(row=2, column=1, sticky="nw", padx=(0, 12), pady=(8, 12))

    def _build_downloads(self) -> None:
        wrap = ctk.CTkFrame(self, fg_color="transparent")
        wrap.grid(row=4, column=0, sticky="nsew", padx=20, pady=(self._pad, 0))
        wrap.grid_columnconfigure(0, weight=1)
        wrap.grid_rowconfigure(1, weight=1)
        ctk.CTkLabel(wrap, text=_("Descargas"), font=ctk.CTkFont(size=16, weight="bold"),
                     anchor="w").grid(row=0, column=0, sticky="w")
        ctk.CTkButton(wrap, text=_("Limpiar terminadas"), width=140, height=26, fg_color="transparent",
                      border_width=1, text_color=("gray10", "gray90"),
                      command=self._clear_finished).grid(row=0, column=1, sticky="e")
        self.list_frame = ctk.CTkScrollableFrame(wrap, corner_radius=12)
        self.list_frame.grid(row=1, column=0, columnspan=2, sticky="nsew", pady=(6, 0))
        self.empty_lbl = ctk.CTkLabel(self.list_frame, text=_("Aún no hay descargas."), text_color=MUTED)
        self.empty_lbl.pack(pady=24)

    @staticmethod
    def _footer_text() -> str:
        ff = "FFmpeg OK" if core.find_ffmpeg() else \
            _("FFmpeg NO encontrado (no se podrá convertir a MP3 ni unir audio y video)")
        dn = "Deno OK" if core.find_deno() else _("Deno no encontrado (pueden faltar formatos)")
        from . import images
        return f"v{__version__} · yt-dlp {core.ytdlp_version()} · gallery-dl {images.version()} · {ff} · {dn}"

    def _build_footer(self) -> None:
        f = ctk.CTkFrame(self, fg_color="transparent")
        f.grid(row=5, column=0, sticky="ew", padx=20, pady=(4, 6) if self.compact else (4, 10))
        f.grid_columnconfigure(0, weight=1)
        small = ctk.CTkFont(size=11)
        self.footer_lbl = ctk.CTkLabel(f, text=self._footer_text(), text_color=MUTED, anchor="w", font=small)
        self.footer_lbl.grid(row=0, column=0, sticky="w")
        self.ffmpeg_btn = ctk.CTkButton(f, text=_("Instalar FFmpeg"), width=120, height=24, font=small,
                                        fg_color=ACCENT, hover_color=ACCENT_HOVER, text_color=ACCENT_TEXT,
                                        command=self._install_ffmpeg)
        if not core.find_ffmpeg() and os.name == "nt":
            self.ffmpeg_btn.grid(row=0, column=1, sticky="e", padx=(8, 0))
        # Aparece solo si hay una versión nueva de la app en GitHub.
        self.app_update_btn = ctk.CTkButton(f, text="", width=170, height=24, font=small,
                                            fg_color=OK_COLOR, hover_color=("#1B5E20", "#43A047"),
                                            text_color="white", command=self._open_app_release)
        self.update_btn = ctk.CTkButton(f, text=_("Actualizar motores"), width=140, height=24,
                                        fg_color="transparent", border_width=1,
                                        text_color=("gray10", "gray90"), font=small,
                                        command=self._on_update_button)
        self.update_btn.grid(row=0, column=3, sticky="e", padx=(8, 0))
        ctk.CTkButton(f, text=_("Acerca de"), width=80, height=24, fg_color="transparent", border_width=1,
                      text_color=("gray10", "gray90"), font=small,
                      command=self._show_about).grid(row=0, column=4, sticky="e", padx=(8, 0))

    # ------------------------------------------------------- acerca de / aviso --
    LEGAL = _("Descarga solo contenido del que tengas los derechos o cuyo autor permita descargarlo. "
              "Descargar videos de YouTube puede ir contra sus condiciones de servicio; "
              "tú eres responsable del uso que le des.")

    def _show_welcome(self) -> None:
        messagebox.showinfo(
            _("Bienvenido a {app}").format(app=APP_NAME),
            _("Pega el enlace de un video o escribe lo que quieres buscar, elige si quieres el video o solo "
              "el audio, y presiona Descargar.") + "\n\n" + self.LEGAL)
        self.settings.welcome_shown = True
        self.settings.save()

    def _show_about(self) -> None:
        text = (f"{APP_NAME} {__version__}\n"
                + _("Creado por {author}").format(author=AUTHOR) + "\n\n"
                + _("Motores de descarga: yt-dlp {ytdlp} (videos) y gallery-dl {gdl} (imágenes)").format(
                    ytdlp=core.ytdlp_version(), gdl=images.version()) + "\n"
                + _("Conversión: FFmpeg · Retos de YouTube: Deno · Interfaz: CustomTkinter") + "\n\n"
                + _("Software libre: el código de la app usa la licencia MIT y el programa completo se "
                    "distribuye bajo la GPL. Los detalles están en THIRD_PARTY_NOTICES.md, junto al "
                    "programa.") + "\n\n" + self.LEGAL)
        title = _("Acerca de {app}").format(app=APP_NAME)
        if GITHUB_REPO:
            if messagebox.askyesno(title, text + "\n\n" + _("¿Abrir la página del proyecto?")):
                webbrowser.open(f"https://github.com/{GITHUB_REPO}")
        else:
            messagebox.showinfo(title, text)

    def _open_app_release(self) -> None:
        if self._app_release:
            webbrowser.open(self._app_release["url"])

    # ------------------------------------------------------- opciones/estado --
    @property
    def mode(self) -> str:
        return self.mode_btn.get()

    def _video_quality_values(self) -> list[str]:
        heights = self._analyzed.heights if self._analyzed else core.DEFAULT_HEIGHTS
        first = [COMPAT, BEST] if self.format_menu.get() == "MP4" else [BEST]
        return first + [height_label(h) for h in heights]

    def _refresh_video_quality(self) -> None:
        values = self._video_quality_values()
        self.quality_menu.configure(values=values, state="normal")
        wanted = quality_label(self.settings.video_quality, self.format_menu.get())
        self.quality_menu.set(wanted if wanted in values else values[0])

    def _refresh_mode(self) -> None:
        if hasattr(self, "tags_btn"):
            self._update_tags_button()
        # «Solo una parte» y «lista completa» no aplican a imágenes (las galerías se bajan completas).
        if hasattr(self, "trim_check"):
            if self.mode == "images":
                self.trim_var.set(False)
                self._on_trim_toggle()
                self.trim_check.configure(state="disabled")
            else:
                self.trim_check.configure(state="normal")
        if hasattr(self, "playlist_check"):
            self.playlist_check.configure(state="disabled" if self.mode == "images" else "normal")
        if self.mode == "images":
            from . import images
            self.subs_frame.grid_remove()
            self.format_menu.configure(values=images.IMAGE_FORMATS)
            self.format_menu.set(self.settings.image_format if self.settings.image_format in images.IMAGE_FORMATS
                                 else images.IMAGE_FORMATS[0])
            self.quality_menu.configure(values=[IMAGE_QUALITY], state="disabled")
            self.quality_menu.set(IMAGE_QUALITY)
        elif self.mode == "audio":
            self.subs_frame.grid_remove()
            self.format_menu.configure(values=core.AUDIO_FORMATS)
            self.format_menu.set(self.settings.audio_format)
            self._refresh_audio_quality()
        else:
            self.subs_frame.grid()
            self.format_menu.configure(values=core.VIDEO_FORMATS)
            self.format_menu.set(self.settings.video_format)
            self._refresh_video_quality()

    def _refresh_audio_quality(self) -> None:
        if self.format_menu.get() in core.LOSSLESS_AUDIO:
            self.quality_menu.configure(values=[LOSSLESS_LABEL], state="disabled")
            self.quality_menu.set(LOSSLESS_LABEL)
        else:
            values = [f"{b} kbps" for b in core.AUDIO_BITRATES]
            self.quality_menu.configure(values=values, state="normal")
            self.quality_menu.set(self.settings.audio_quality if self.settings.audio_quality in values else values[0])

    def _on_mode_change(self) -> None:
        self.settings.mode = self.mode
        self._refresh_mode()
        self.settings.save()

    def _on_format_change(self) -> None:
        if self.mode == "images":
            pass
        elif self.mode == "audio":
            self._refresh_audio_quality()
        else:
            # «Compatible con todo» solo existe en MP4: al cambiar de formato se actualiza la lista.
            current = quality_code(self.quality_menu.get())
            self.settings.video_format = self.format_menu.get()
            self.settings.video_quality = current
            self._refresh_video_quality()
        self._save_choices()

    def _save_choices(self) -> None:
        s = self.settings
        s.mode = self.mode
        if self.mode == "images":
            s.image_format = self.format_menu.get()
        elif self.mode == "audio":
            s.audio_format = self.format_menu.get()
            if self.quality_menu.get() != LOSSLESS_LABEL:
                s.audio_quality = self.quality_menu.get()
        else:
            s.video_format = self.format_menu.get()
            s.video_quality = quality_code(self.quality_menu.get())
        s.playlist = bool(self.playlist_var.get())
        s.subtitles = next((k for k, v in SUBS_LABELS.items() if v == self.subs_menu.get()), "none")
        s.save()

    def _on_playlist_toggle(self) -> None:
        self._save_choices()
        if self._analyzed and self._analyzed.url == self.url_entry.get().strip():
            self.analyze()

    def _on_theme(self, value: str) -> None:
        mode = {"Claro": "Light", "Oscuro": "Dark"}.get(value, "System")
        ctk.set_appearance_mode(mode)
        self.settings.appearance = mode
        self.settings.save()

    def _choose_folder(self) -> None:
        path = filedialog.askdirectory(initialdir=self.settings.output_dir, title=_("Elige la carpeta de descargas"))
        if path:
            self.settings.output_dir = os.path.normpath(path)
            self.folder_lbl.configure(text=" " + shorten_path(self.settings.output_dir))
            self.settings.save()

    def _paste(self) -> None:
        try:
            text = self.clipboard_get().strip()
        except Exception:
            text = ""
        if not text:
            return
        self.url_entry.delete(0, "end")
        self.url_entry.insert(0, text)
        self.analyze()

    # ------------------------------------------------------- búsqueda / portapapeles --
    @staticmethod
    def _is_url(text: str) -> bool:
        return text.startswith(("http://", "https://", "www.", "youtube.com", "youtu.be"))

    @staticmethod
    def _normalize_url(text: str) -> str:
        return text if text.startswith(("http://", "https://")) else "https://" + text

    def _update_action_label(self) -> None:
        if str(self.analyze_btn.cget("state")) == "disabled":
            return
        text = self.url_entry.get().strip()
        self.analyze_btn.configure(text=_("Buscar") if text and not self._is_url(text) else _("Analizar"))

    def open_search(self, query: str) -> None:
        from .dialogs import SearchDialog

        def pick(url: str) -> None:
            self.url_entry.delete(0, "end")
            self.url_entry.insert(0, url)
            self.analyze()

        SearchDialog(self, query, pick)

    def ignore_clipboard(self, text: str) -> None:
        """Marca un texto del portapapeles como ya visto (p. ej. si lo copió la propia app)."""
        self._last_clip = text.strip()

    def _check_clipboard(self) -> None:
        """Si hay un enlace de YouTube recién copiado, lo pega y lo analiza."""
        if not self.settings.watch_clipboard:
            return
        try:
            clip = self.clipboard_get().strip()
        except Exception:
            return
        if not clip or clip == self._last_clip or not core.is_media_url(clip):
            return
        self._last_clip = clip
        current = self.url_entry.get().strip()
        if current == clip or (self._analyzed and self._analyzed.url == clip):
            return
        self.url_entry.delete(0, "end")
        self.url_entry.insert(0, clip)
        self.analyze()

    # -------------------------------------------------------------- análisis --
    def analyze(self) -> None:
        text = self.url_entry.get().strip()
        if not text:
            return
        if not self._is_url(text):
            self.open_search(text)
            return
        url = self._normalize_url(text)
        if url != text:
            self.url_entry.delete(0, "end")
            self.url_entry.insert(0, url)
        self._last_clip = url  # que el mismo enlace del portapapeles no se vuelva a pegar solo
        self._analyze_token += 1
        token = self._analyze_token
        playlist = bool(self.playlist_var.get())
        self.analyze_btn.configure(state="disabled", text=_("Analizando…"))
        self.info_title.configure(text=_("Analizando enlace…"))
        self.info_meta.configure(text=url)

        mode = self.mode

        def work():
            from . import images
            try:
                if mode == "images":
                    # Fotos con gallery-dl; si es un video (YouTube…), su portada.
                    info = images.probe(url) if images.supported(url) else images.probe_thumbnail(url)
                else:
                    try:
                        info = core.fetch_info(url, playlist)
                    except Exception as video_error:
                        # ¿No hay video? Si el sitio es de fotos (Instagram, X, Pinterest…), se prueban imágenes.
                        if not images.supported(url):
                            raise
                        try:
                            info = images.probe(url)
                        except Exception as image_error:
                            # El mensaje más útil: «inicia sesión» si el sitio lo pide; si no, el del video.
                            useful = image_error if str(image_error) == images.login_message() else video_error
                            raise RuntimeError(str(useful)) from None
                self.events.put(("info", token, info))
                if info.thumbnail:
                    self.events.put(("thumb", token, core.fetch_thumbnail(info.thumbnail)))
            except Exception as exc:
                self.events.put(("info_error", token, str(exc)))

        threading.Thread(target=work, daemon=True).start()

    def _show_info(self, info: core.MediaInfo) -> None:
        self._analyzed = info
        self.analyze_btn.configure(state="normal")
        self._update_action_label()
        self.info_title.configure(text=info.title)
        self._tags = None
        duration = _("Duración {time}").format(time=fmt_time(info.duration))
        if info.is_images and info.thumb_only:
            meta = f"{duration} · " + _("se descargará la portada del video")
        elif info.is_images:
            meta = _("1 imagen") if info.count == 1 else (
                _("{n} imágenes").format(n=info.count) if info.count < images_probe_limit()
                else _("más de {n} imágenes").format(n=info.count))
            if self.mode != "images":          # es una publicación de fotos: se cambia a «Imágenes»
                self.mode_btn.set("images")
                self._on_mode_change()
        elif info.is_playlist:
            meta = _("Lista de reproducción · {n} videos").format(n=info.count)
        elif info.audio_only:
            meta = f"{duration} · " + _("solo audio")
            if self.mode != "audio":           # no hay video que bajar: se cambia a «Solo audio»
                self.mode_btn.set("audio")
                self._on_mode_change()
        elif info.heights_known:
            meta = f"{duration} · " + _("hasta {quality}").format(quality=height_label(info.heights[0]))
        else:
            meta = f"{duration} · " + _("la mejor calidad disponible")
        if info.site and info.site.lower() not in ("youtube", "youtubetab"):
            meta = f"{info.site} · {meta}"
        if info.uploader:
            meta = f"{info.uploader} · {meta}"
        self.info_meta.configure(text=meta)
        self._update_tags_button()
        # Por omisión se marcan todos menos los privados/eliminados.
        self._selection = None
        if info.is_playlist and info.entries:
            available = {i for i, t, _d in info.entries if t not in core.UNAVAILABLE_TITLES}
            if len(available) < len(info.entries):
                self._selection = available
        self._update_pick_label()
        if self.mode == "video":
            self._refresh_mode()

    def _show_thumb(self, data: bytes | None) -> None:
        if not data:
            return
        try:
            img = Image.open(io.BytesIO(data)).convert("RGB")
            w, h = img.size
            target_h = int(w * 9 / 16)
            if h > target_h:  # recorta las franjas negras de las miniaturas 4:3
                top = (h - target_h) // 2
                img = img.crop((0, top, w, top + target_h))
            self._thumb_image = ctk.CTkImage(light_image=img, dark_image=img, size=self.thumb_size)
            self.thumb_lbl.configure(image=self._thumb_image)
        except Exception:
            pass

    def _reset_info(self) -> None:
        self._analyzed = None
        self._selection = None
        self._tags = None
        self._update_pick_label()
        self._update_tags_button()
        self.trim_var.set(False)
        for entry in (self.trim_from, self.trim_to):
            entry.configure(state="normal")
            entry.delete(0, "end")
        self._on_trim_toggle()
        self._thumb_image = None
        self.thumb_lbl.configure(image=None)
        self.info_title.configure(text=_("Ningún enlace analizado"))
        self.info_meta.configure(text=_("Pega otro enlace o escribe el nombre de un video para buscarlo."))
        if self.mode == "video":
            self._refresh_mode()

    # ------------------------------------------------------------- descargas --
    def _current_options(self, url: str) -> core.DownloadOptions:
        self._save_choices()
        s = self.settings
        out = s.output_dir
        if s.split_folders:
            out = os.path.join(out, {"audio": "Audio", "images": _("Imágenes")}.get(s.mode, "Videos"))
        return core.DownloadOptions(
            url=url,
            output_dir=out,
            mode=s.mode,
            video_format=s.video_format,
            height=label_height(s.video_quality),
            compat=s.video_quality == "compat" and s.video_format == "MP4",
            audio_format=s.audio_format,
            audio_bitrate=s.audio_quality.split()[0],
            playlist=s.playlist,
            filename_style=s.filename_style,
            subtitles=core.SUBTITLE_LANGS.get(s.subtitles, "") if s.mode == "video" else "",
            # (s.subtitles es un código: "none", "es", "en" o "es_en")
            keep_subtitle_files=s.keep_subtitle_files,
            rate_limit=s.rate_limit,
            image_format=s.image_format,
        )

    def download(self) -> None:
        text = self.url_entry.get().strip()
        if not text:
            return
        if not self._is_url(text):
            self.open_search(text)       # con texto normal, «Descargar» también busca
            return
        url = self._normalize_url(text)
        opts = self._current_options(url)
        info = self._analyzed if self._analyzed and self._analyzed.url == url else None
        title = info.title if info else url
        if info and info.is_playlist:
            opts.playlist = True
            if self._selection is not None:
                if not self._selection:
                    messagebox.showwarning(APP_NAME, _("No hay videos marcados en la lista."))
                    return
                opts.playlist_items = core.compress_indices(self._selection)
        section = self._read_section()
        if section is False:
            return
        if section and opts.playlist:
            messagebox.showwarning(APP_NAME, _("«Solo una parte» funciona con un video a la vez, no con listas."))
            return
        opts.section = section or None
        if opts.mode == "audio" and self._tags and info and not info.is_playlist:
            opts.tags = dict(self._tags)
            title = self._tags.get("title") or title
        if not self._confirm_repeat(opts, title):
            return
        self._start_task(opts, title)
        self.url_entry.delete(0, "end")
        self._analyze_token += 1  # descarta análisis en curso
        self.analyze_btn.configure(state="normal", text=_("Analizar"))
        self._reset_info()

    def _confirm_repeat(self, opts: core.DownloadOptions, title: str) -> bool:
        """Si ya se descargó lo mismo (y el archivo sigue ahí), pregunta antes de repetir."""
        from . import history
        prev = history.find(core.media_key(opts.url, opts.playlist, opts.mode))
        if not prev:
            return True
        when = time.strftime("%d/%m/%Y", time.localtime(prev.date))
        return messagebox.askyesno(
            APP_NAME, _("Ya descargaste «{title}» el {date} ({kind}).").format(
                title=shorten(prev.title, 60), date=when, kind=prev.kind)
            + "\n\n" + _("¿Quieres descargarlo de nuevo?"))

    def on_task_finished(self, row: DownloadRow, ev: dict) -> None:
        """Una descarga terminó (bien o con error): historial y aviso."""
        from . import history
        if ev["type"] == "done" and ev.get("files"):
            o = row.task.options
            files = ev["files"]
            title = row.title_lbl.cget("text")
            if not row._title_locked or title.startswith("http"):
                # El título no venía del análisis: se toma del archivo (sin la extensión).
                title = os.path.splitext(os.path.basename(files[0]))[0] if len(files) == 1 \
                    else os.path.basename(os.path.dirname(files[0]))
            history.add(history.HistoryEntry(
                key=core.media_key(o.url, o.playlist, o.mode), url=o.url, title=title,
                kind=self._badge(o), files=files, folder=os.path.dirname(files[0])))
        if self.settings.notify and self.focus_displayof() is None:
            notify_attention(self)

    def _open_history(self) -> None:
        from .dialogs import HistoryDialog
        HistoryDialog(self)

    def _open_settings(self) -> None:
        from .dialogs import SettingsDialog
        SettingsDialog(self)

    def apply_settings(self) -> None:
        """Aplica lo guardado en la ventana de Ajustes."""
        ctk.set_appearance_mode(self.settings.appearance)
        core.set_max_parallel(self.settings.max_parallel)
        core.set_cookies_browser(self.settings.cookies_browser or None)

    def resume(self, row: DownloadRow) -> None:
        """Reanuda una descarga pausada: yt-dlp continúa desde lo que ya había bajado."""
        title = row.title_lbl.cget("text")
        opts = row.task.options
        partial = row.task.partial_files
        self.remove_row(row)
        self._start_task(opts, title, resume_files=partial)

    def _badge(self, o: core.DownloadOptions) -> str:
        if o.mode == "images":
            return _("Imágenes") + (" JPG" if o.image_format == "JPG" else " · " + _("original"))
        if o.mode == "audio":
            q = "" if o.audio_format in core.LOSSLESS_AUDIO else f" {o.audio_bitrate}k"
            text = f"{o.audio_format}{q}"
        else:
            if o.compat:
                text = f"{o.video_format} " + _("compatible")
            else:
                text = f"{o.video_format} {f'{o.height}p' if o.height else _('máx.')}"
        if o.playlist_items:
            n = sum(int(b) - int(a) + 1 if "-" in part else 1
                    for part in o.playlist_items.split(",")
                    for a, _sep, b in [part.partition("-")])
            text += " · " + _("{n} videos").format(n=n)
        if o.section:
            text += f" · {core.fmt_clock(o.section[0])}–{core.fmt_clock(o.section[1])}"
        if o.subtitles:
            text += " · " + _("subtítulos")
        return text

    def _start_task(self, opts: core.DownloadOptions, title: str, resume_files: set[str] | None = None) -> None:
        if self.empty_lbl.winfo_ismapped():
            self.empty_lbl.pack_forget()
        task_id = next(self._ids)
        if opts.mode == "images":
            from .images import ImageTask
            task_cls = ImageTask
        else:
            task_cls = core.DownloadTask
        task = task_cls(opts, lambda ev, i=task_id: self.events.put(("task", i, ev)), resume_files)
        row = DownloadRow(self.list_frame, self, task, title, self._badge(opts))
        existing = [r for r in self.rows.values() if r.winfo_exists()]
        pack = {"fill": "x", "padx": 4, "pady": 4}
        if existing:
            pack["before"] = existing[-1]  # las más recientes arriba
        row.pack(**pack)
        self.rows[task_id] = row
        task.start()

    def retry(self, row: DownloadRow) -> None:
        title = row.title_lbl.cget("text")
        opts = row.task.options
        self.remove_row(row)
        self._start_task(opts, title)

    def remove_row(self, row: DownloadRow) -> None:
        for key, r in list(self.rows.items()):
            if r is row:
                del self.rows[key]
        row.destroy()
        if not self.rows:
            self.empty_lbl.pack(pady=24)

    def _clear_finished(self) -> None:
        for row in [r for r in self.rows.values() if r.state != "running"]:
            self.remove_row(row)

    # ------------------------------------------------------------ eventos --
    def _poll(self) -> None:
        try:
            while True:
                kind, key, payload = self.events.get_nowait()
                if kind == "task":
                    row = self.rows.get(key)
                    if row is not None:
                        row.handle(payload)
                elif kind == "update":
                    self._update_finished(payload)
                elif kind == "ffmpeg":
                    self._ffmpeg_finished(payload)
                elif kind == "app_release":
                    self._show_app_release(payload)
                elif key != self._analyze_token:
                    continue  # resultado de un análisis viejo
                elif kind == "info":
                    self._show_info(payload)
                elif kind == "thumb":
                    self._show_thumb(payload)
                elif kind == "info_error":
                    self.analyze_btn.configure(state="normal", text=_("Analizar"))
                    self.info_title.configure(text=_("No se pudo analizar el enlace"))
                    self.info_meta.configure(text=payload)
        except queue.Empty:
            pass
        self.after(80, self._poll)

    # -------------------------------------------------------- actualización --
    def _on_update_button(self) -> None:
        if self._pending_update:
            self._restart()
        else:
            self._check_updates(manual=True)

    def _check_updates(self, manual: bool) -> None:
        if self._pending_update:
            return
        self.update_btn.configure(state="disabled", text=_("Buscando actualización…"))
        def work():
            self.events.put(("update", None, (manual, updater.check_and_update())))
            release = updater.check_app_release()
            if release:
                self.events.put(("app_release", None, release))

        threading.Thread(target=work, daemon=True).start()

    def _show_app_release(self, release: dict) -> None:
        self._app_release = release
        self.app_update_btn.configure(text=_("Nueva versión {version} disponible").format(version=release["version"]))
        self.app_update_btn.grid(row=0, column=2, sticky="e", padx=(8, 0))

    def _update_finished(self, payload) -> None:
        manual, res = payload
        self.update_btn.configure(state="normal", text=_("Actualizar motores"))
        if res["status"] != "error":
            self.settings.last_update_check = time.time()
            self.settings.save()
        if res["status"] == "updated":
            self._pending_update = res["version"]
            self.update_btn.configure(text=_("Reiniciar para actualizar"),
                                      fg_color=ACCENT, hover_color=ACCENT_HOVER, text_color=ACCENT_TEXT,
                                      border_width=0, width=200)
            if manual and messagebox.askyesno(
                    APP_NAME, _("Se descargaron versiones nuevas: {version}.").format(version=res["version"]) + "\n\n"
                    + _("¿Reiniciar la app ahora para usarlo?")):
                self._restart()
        elif res["status"] == "current":
            if manual:
                messagebox.showinfo(APP_NAME, _("Ya tienes las versiones más recientes de los motores ({version}).")
                                    .format(version=res["version"]))
        else:
            core.log.warning("No se pudo actualizar yt-dlp: %s", res["message"])
            if manual:
                messagebox.showerror(APP_NAME, _("No se pudieron actualizar los motores:") + f"\n\n{res['message']}")

    def _restart(self) -> None:
        if any(r.state == "running" for r in self.rows.values()):
            messagebox.showinfo(APP_NAME, _("Hay descargas en curso. Reinicia cuando terminen."))
            return
        args = [sys.executable]
        if not getattr(sys, "frozen", False):
            args.append(os.path.abspath(sys.argv[0]))
        subprocess.Popen(args, cwd=core.app_dir())
        self.destroy()

    def _install_ffmpeg(self) -> None:
        if not messagebox.askyesno(APP_NAME, _("Se instalará FFmpeg con winget (Gyan.FFmpeg, unos 200 MB).")
                                   + "\n\n" + _("¿Continuar?")):
            return
        self.ffmpeg_btn.configure(state="disabled", text=_("Instalando FFmpeg…"))

        def work():
            try:
                res = subprocess.run(
                    ["winget", "install", "--id", "Gyan.FFmpeg", "-e", "--silent",
                     "--accept-source-agreements", "--accept-package-agreements"],
                    capture_output=True, text=True, timeout=900,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                msg = (res.stdout or "") + (res.stderr or "")
            except Exception as exc:
                msg = str(exc)
            self.events.put(("ffmpeg", None, msg))

        threading.Thread(target=work, daemon=True).start()

    def _ffmpeg_finished(self, msg: str) -> None:
        self.footer_lbl.configure(text=self._footer_text())
        if core.find_ffmpeg():
            self.ffmpeg_btn.grid_remove()
            messagebox.showinfo(APP_NAME, _("FFmpeg quedó instalado."))
        else:
            self.ffmpeg_btn.configure(state="normal", text=_("Instalar FFmpeg"))
            core.log.warning("Instalación de FFmpeg fallida: %s", msg[-800:])
            messagebox.showerror(APP_NAME, _("No se pudo instalar FFmpeg automáticamente.") + "\n\n"
                                 + _("Instálalo con: winget install Gyan.FFmpeg"))

    # ---------------------------------------------------------------- cierre --
    def _on_close(self) -> None:
        running = [r for r in self.rows.values() if r.state == "running"]
        if running and not messagebox.askyesno(
                APP_NAME, _("Hay {n} descarga(s) en curso. ¿Cancelarlas y salir?").format(n=len(running))):
            return
        for r in running:
            r.task.cancel()
        self.destroy()


def close_splash() -> None:
    """Cierra la pantalla de carga del .exe (solo existe en la versión compilada con --splash)."""
    try:
        import pyi_splash  # type: ignore[import-not-found]
        pyi_splash.close()
    except Exception:
        pass


def run() -> None:
    app = App()
    app.after(200, close_splash)
    app.mainloop()
