"""Ventanas secundarias: resultados de búsqueda, historial, título y artista, y ajustes.

Se importan desde gui.py solo cuando se abren (así no hay importación circular).
"""
from __future__ import annotations

import io
import os
import queue
import threading
import time
from tkinter import messagebox

import customtkinter as ctk
from PIL import Image

from . import APP_NAME, core, history, i18n, report
from .gui import (ACCENT, ACCENT_HOVER, ACCENT_TEXT, ERR_COLOR, MUTED, fmt_time, open_path,
                  fit_window, outline_button, set_window_icon, shorten)
from .i18n import _

SEARCH_THUMB = (144, 81)


class _Dialog(ctk.CTkToplevel):
    """Base: ventana modal sobre la principal, con el ícono de CarryIt."""

    def __init__(self, app, title: str, size: str, min_size: tuple[int, int] = (420, 220)) -> None:
        super().__init__(app)
        self.app = app
        self.title(title)
        # Se ajusta al espacio libre de la pantalla (escala de Windows incluida) y se centra sobre la app.
        width, height = (int(n) for n in size.split("x"))
        fit_window(self, width, height, parent=app, min_size=min_size)
        self.transient(app)
        self.after(100, self._grab)
        self.after(300, lambda: set_window_icon(self))

    def _grab(self) -> None:
        try:
            self.lift()
            self.focus_force()
            self.grab_set()
        except Exception:
            pass


# --------------------------------------------------------------------------- #
class SearchDialog(_Dialog):
    """Busca en YouTube y muestra resultados con miniatura; «Elegir» pasa el enlace a la ventana principal."""

    def __init__(self, app, query: str, on_pick) -> None:
        super().__init__(app, _("Buscar") + f" · {shorten(query, 50)}", "720x640")
        self.minsize(560, 420)
        self.on_pick = on_pick
        self.events: queue.Queue = queue.Queue()
        self._images: list = []
        self._thumb_labels: dict[str, ctk.CTkLabel] = {}

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)
        top = ctk.CTkFrame(self, fg_color="transparent")
        top.grid(row=0, column=0, sticky="ew", padx=16, pady=(16, 8))
        top.grid_columnconfigure(0, weight=1)
        self.entry = ctk.CTkEntry(top, height=36, placeholder_text=_("¿Qué quieres buscar?"))
        self.entry.insert(0, query)
        self.entry.grid(row=0, column=0, sticky="ew")
        self.entry.bind("<Return>", lambda _e: self.search())
        self.search_btn = ctk.CTkButton(top, text=_("Buscar"), width=100, height=36, command=self.search)
        self.search_btn.grid(row=0, column=1, padx=(8, 0))

        self.list = ctk.CTkScrollableFrame(self, corner_radius=10)
        self.list.grid(row=1, column=0, sticky="nsew", padx=16, pady=(0, 12))
        self.status = ctk.CTkLabel(self.list, text="", text_color=MUTED)
        self.status.pack(pady=24)

        self.after(60, self._poll)
        self.search()

    def search(self) -> None:
        query = self.entry.get().strip()
        if not query:
            return
        for w in list(self.list.winfo_children()):
            if w is not self.status:
                w.destroy()
        self._images.clear()
        self._thumb_labels.clear()
        self.status.configure(text=_("Buscando…"), text_color=MUTED)
        self.status.pack(pady=24)
        self.search_btn.configure(state="disabled")

        def work():
            try:
                self.events.put(("results", core.search(query)))
            except Exception as exc:
                self.events.put(("error", str(exc)))

        threading.Thread(target=work, daemon=True).start()

    def _show(self, results: list[core.SearchResult]) -> None:
        self.search_btn.configure(state="normal")
        if not results:
            self.status.configure(text=_("No se encontraron videos. Prueba con otras palabras."))
            return
        self.status.pack_forget()
        for r in results:
            row = ctk.CTkFrame(self.list, corner_radius=8)
            row.pack(fill="x", padx=4, pady=4)
            row.grid_columnconfigure(1, weight=1)
            thumb = ctk.CTkLabel(row, text="", width=SEARCH_THUMB[0], height=SEARCH_THUMB[1],
                                 fg_color=("#D9D9DE", "#1F1F23"), corner_radius=6)
            thumb.grid(row=0, column=0, rowspan=2, padx=8, pady=8)
            self._thumb_labels[r.video_id] = thumb
            ctk.CTkLabel(row, text=shorten(r.title, 90), anchor="w", justify="left", wraplength=380,
                         font=ctk.CTkFont(size=13, weight="bold")).grid(row=0, column=1, sticky="sw", pady=(10, 0))
            meta = " · ".join(x for x in (r.channel, fmt_time(r.duration) if r.duration else "") if x)
            ctk.CTkLabel(row, text=meta, anchor="w", text_color=MUTED).grid(row=1, column=1, sticky="nw")
            ctk.CTkButton(row, text=_("Elegir"), width=80, command=lambda r=r: self._pick(r)).grid(
                row=0, column=2, rowspan=2, padx=10)
            for w in (row, thumb):
                w.bind("<Double-Button-1>", lambda _e, r=r: self._pick(r))
        threading.Thread(target=self._load_thumbs, args=(results,), daemon=True).start()

    def _load_thumbs(self, results) -> None:
        for r in results:
            data = core.fetch_thumbnail(r.thumbnail)
            if data:
                self.events.put(("thumb", (r.video_id, data)))

    def _set_thumb(self, video_id: str, data: bytes) -> None:
        label = self._thumb_labels.get(video_id)
        if label is None or not label.winfo_exists():
            return
        try:
            img = Image.open(io.BytesIO(data)).convert("RGB")
            ctk_img = ctk.CTkImage(light_image=img, dark_image=img, size=SEARCH_THUMB)
            self._images.append(ctk_img)
            label.configure(image=ctk_img)
        except Exception:
            pass

    def _poll(self) -> None:
        if not self.winfo_exists():
            return
        try:
            while True:
                kind, payload = self.events.get_nowait()
                if kind == "results":
                    self._show(payload)
                elif kind == "thumb":
                    self._set_thumb(*payload)
                elif kind == "error":
                    self.search_btn.configure(state="normal")
                    self.status.configure(text=_("No se pudo buscar:") + f" {payload}", text_color=ERR_COLOR)
        except queue.Empty:
            pass
        self.after(80, self._poll)

    def _pick(self, r: core.SearchResult) -> None:
        self.on_pick(r.url)
        self.destroy()


# --------------------------------------------------------------------------- #
class HistoryDialog(_Dialog):
    """Descargas anteriores (se conservan al cerrar la app)."""

    BATCH = 40

    def __init__(self, app) -> None:
        super().__init__(app, _("Historial de descargas"), "760x600")
        self.minsize(560, 400)
        self.entries = history.load()

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)
        top = ctk.CTkFrame(self, fg_color="transparent")
        top.grid(row=0, column=0, sticky="ew", padx=16, pady=(16, 8))
        top.grid_columnconfigure(0, weight=1)
        self.search = ctk.CTkEntry(top, placeholder_text=_("Buscar en el historial…"))
        self.search.grid(row=0, column=0, sticky="ew")
        self.search.bind("<KeyRelease>", lambda _e: self._rebuild())

        self.list = ctk.CTkScrollableFrame(self, corner_radius=10)
        self.list.grid(row=1, column=0, sticky="nsew", padx=16)

        bottom = ctk.CTkFrame(self, fg_color="transparent")
        bottom.grid(row=2, column=0, sticky="ew", padx=16, pady=12)
        bottom.grid_columnconfigure(0, weight=1)
        self.count_lbl = ctk.CTkLabel(bottom, text="", text_color=MUTED, anchor="w")
        self.count_lbl.grid(row=0, column=0, sticky="w")
        outline_button(bottom, _("Borrar historial"), self._clear, width=130).grid(row=0, column=1, padx=(8, 0))
        ctk.CTkButton(bottom, text=_("Cerrar"), width=100, command=self.destroy).grid(row=0, column=2, padx=(8, 0))
        self._rebuild()

    def _matches(self, e: history.HistoryEntry) -> bool:
        q = self.search.get().strip().lower()
        return not q or q in e.title.lower()

    def _rebuild(self) -> None:
        for w in self.list.winfo_children():
            w.destroy()
        shown = [e for e in self.entries if self._matches(e)]
        n = len(self.entries)
        self.count_lbl.configure(text=_("1 descarga guardada") if n == 1
                                 else _("{n} descargas guardadas").format(n=n))
        if not shown:
            ctk.CTkLabel(self.list, text=_("Aún no hay descargas en el historial.") if not self.entries
                         else _("Nada coincide con la búsqueda."), text_color=MUTED).pack(pady=24)
            return
        self._build_batch(shown, 0)

    def _build_batch(self, shown, start: int) -> None:
        if not self.winfo_exists():
            return
        for e in shown[start:start + self.BATCH]:
            row = ctk.CTkFrame(self.list, corner_radius=8)
            row.pack(fill="x", padx=4, pady=3)
            row.grid_columnconfigure(0, weight=1)
            ctk.CTkLabel(row, text=shorten(e.title, 80), anchor="w",
                         font=ctk.CTkFont(size=13, weight="bold")).grid(row=0, column=0, sticky="w", padx=10, pady=(8, 0))
            when = time.strftime("%d/%m/%Y %H:%M", time.localtime(e.date))
            exists = e.exists
            meta = f"{e.kind} · {when}" + ("" if exists else " · " + _("el archivo ya no está en su carpeta"))
            ctk.CTkLabel(row, text=meta, anchor="w", text_color=MUTED).grid(row=1, column=0, sticky="w", padx=10, pady=(0, 8))
            actions = ctk.CTkFrame(row, fg_color="transparent")
            actions.grid(row=0, column=1, rowspan=2, padx=8)
            if exists:
                files = [f for f in e.files if f and os.path.isfile(f)]
                outline_button(actions, _("Mostrar"), lambda f=files: self._show(f), width=80, height=28).pack(side="left")
            outline_button(actions, _("Copiar enlace"), lambda u=e.url: self._copy(u), width=110,
                           height=28).pack(side="left", padx=(6, 0))
        if start + self.BATCH < len(shown):
            self.after(10, lambda: self._build_batch(shown, start + self.BATCH))

    @staticmethod
    def _show(files: list[str]) -> None:
        if len(files) == 1:
            open_path(files[0], select=True)
        else:
            open_path(os.path.dirname(files[0]))

    def _copy(self, url: str) -> None:
        self.clipboard_clear()
        self.clipboard_append(url)
        self.app.ignore_clipboard(url)

    def _clear(self) -> None:
        if not self.entries:
            return
        if messagebox.askyesno(APP_NAME, _("¿Borrar todo el historial?") + "\n\n"
                               + _("Los archivos descargados no se borran."), parent=self):
            history.clear()
            self.entries = []
            self._rebuild()


# --------------------------------------------------------------------------- #
class TagsDialog(_Dialog):
    """Título y artista con que se guarda un audio (etiquetas del archivo y nombre del archivo)."""

    def __init__(self, app, current: dict, on_accept) -> None:
        super().__init__(app, _("Título y artista"), "520x236")
        self.resizable(False, False)
        self.on_accept = on_accept
        self.grid_columnconfigure(0, weight=1)
        body = ctk.CTkFrame(self, corner_radius=12)
        body.grid(row=0, column=0, sticky="ew", padx=16, pady=16)
        body.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(body, text=_("Así se verá en tu celular, el estéreo del carro o tu reproductor de música."),
                     text_color=MUTED, wraplength=450, justify="left").grid(
            row=0, column=0, columnspan=2, sticky="w", padx=16, pady=(14, 8))
        ctk.CTkLabel(body, text=_("Título")).grid(row=1, column=0, sticky="w", padx=16, pady=6)
        self.title_entry = ctk.CTkEntry(body)
        self.title_entry.insert(0, current.get("title", ""))
        self.title_entry.grid(row=1, column=1, sticky="ew", padx=16, pady=6)
        ctk.CTkLabel(body, text=_("Artista")).grid(row=2, column=0, sticky="w", padx=16, pady=(6, 16))
        self.artist_entry = ctk.CTkEntry(body)
        self.artist_entry.insert(0, current.get("artist", ""))
        self.artist_entry.grid(row=2, column=1, sticky="ew", padx=16, pady=(6, 16))

        bottom = ctk.CTkFrame(self, fg_color="transparent")
        bottom.grid(row=1, column=0, sticky="ew", padx=16, pady=(0, 16))
        bottom.grid_columnconfigure(0, weight=1)
        outline_button(bottom, _("Usar los originales"), self._reset, width=150).grid(row=0, column=0, sticky="w")
        outline_button(bottom, _("Cancelar"), self.destroy, width=100).grid(row=0, column=1, padx=(8, 0))
        ctk.CTkButton(bottom, text=_("Aceptar"), width=100, fg_color=ACCENT, hover_color=ACCENT_HOVER,
                      text_color=ACCENT_TEXT, command=self._accept).grid(row=0, column=2, padx=(8, 0))
        self.title_entry.bind("<Return>", lambda _e: self._accept())
        self.artist_entry.bind("<Return>", lambda _e: self._accept())

    def _reset(self) -> None:
        self.on_accept(None)
        self.destroy()

    def _accept(self) -> None:
        title, artist = self.title_entry.get().strip(), self.artist_entry.get().strip()
        if not title:
            messagebox.showwarning(APP_NAME, _("Escribe un título."), parent=self)
            return
        self.on_accept({"title": title, "artist": artist})
        self.destroy()


# --------------------------------------------------------------------------- #
class SettingsDialog(_Dialog):
    def __init__(self, app) -> None:
        super().__init__(app, _("Ajustes"), "600x880")
        self.minsize(560, 480)
        # Texto en pantalla -> valor que se guarda.
        self.themes = {_("Oscuro"): "Dark", _("Claro"): "Light", _("Igual que Windows"): "System"}
        self.languages = {_("Automático (idioma de Windows)"): "auto", "Español": "es", "English": "en"}
        self.names = {_("Título"): "title", _("Título - Canal"): "title_channel",
                      _("Canal - Título"): "channel_title"}
        self.rates = {_("Sin límite"): "", "500 KB/s": "500K", "1 MB/s": "1M", "2 MB/s": "2M",
                      "5 MB/s": "5M", "10 MB/s": "10M"}
        self.browsers = {_("No usar"): "", **{v: k for k, v in core.BROWSERS.items()}}
        s = app.settings
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=1)

        body = ctk.CTkScrollableFrame(self, corner_radius=12)
        body.grid(row=0, column=0, sticky="nsew", padx=16, pady=16)
        body.grid_columnconfigure(1, weight=1)
        title_font = ctk.CTkFont(size=15, weight="bold")

        def section(row: int, text: str) -> None:
            ctk.CTkLabel(body, text=text, font=title_font, anchor="w").grid(
                row=row, column=0, columnspan=2, sticky="w", padx=16, pady=(14, 4))

        def option(row: int, label: str, choices: dict[str, str], current_value: str) -> ctk.CTkOptionMenu:
            ctk.CTkLabel(body, text=label, anchor="w").grid(row=row, column=0, sticky="w", padx=16, pady=6)
            menu = ctk.CTkOptionMenu(body, values=list(choices), width=220)
            menu.set(next((k for k, v in choices.items() if v == current_value), next(iter(choices))))
            menu.grid(row=row, column=1, sticky="e", padx=16, pady=6)
            return menu

        def check(row: int, label: str, value: bool) -> ctk.BooleanVar:
            var = ctk.BooleanVar(value=value)
            ctk.CTkCheckBox(body, text=label, variable=var).grid(
                row=row, column=0, columnspan=2, sticky="w", padx=16, pady=6)
            return var

        section(0, _("Apariencia"))
        self.theme = option(1, _("Tema"), self.themes, s.appearance)
        self.language = option(2, _("Idioma"), self.languages, s.language)

        section(3, _("Descargas"))
        self.parallel = option(4, _("Descargas al mismo tiempo"), {str(n): str(n) for n in range(1, 6)},
                               str(s.max_parallel))
        self.name_style = option(5, _("Nombre de los archivos"), self.names, s.filename_style)
        self.split = check(6, _("Guardar videos y audios en carpetas separadas («Videos» y «Audio»)"),
                           s.split_folders)
        self.rate = option(7, _("Velocidad máxima"), self.rates, s.rate_limit)
        self.keep_subs = check(8, _("Guardar los subtítulos también como archivo .srt aparte"),
                               s.keep_subtitle_files)

        section(9, _("Sitios que piden iniciar sesión"))
        ctk.CTkLabel(body, text=_("Para Instagram, Vimeo, Reddit y otros: usa la sesión que ya tienes abierta en "
                                  "tu navegador. Firefox es el más compatible."), text_color=MUTED,
                     wraplength=470, justify="left", anchor="w").grid(row=10, column=0, columnspan=2,
                                                                      sticky="w", padx=16)
        self.browser = option(11, _("Navegador"), self.browsers, s.cookies_browser)

        section(12, _("Comodidad"))
        self.clip = check(13, _("Detectar enlaces copiados (YouTube, Facebook, TikTok…)"), s.watch_clipboard)
        self.notify = check(14, _("Avisar cuando termine una descarga (si la ventana no está al frente)"),
                            s.notify)
        self.auto = check(15, _("Buscar actualizaciones automáticamente"), s.auto_update)

        section(16, _("Ayuda"))
        outline_button(body, _("Copiar informe de diagnóstico"), self._copy_report, width=230).grid(
            row=17, column=0, columnspan=2, sticky="w", padx=16, pady=(4, 16))

        bottom = ctk.CTkFrame(self, fg_color="transparent")
        bottom.grid(row=1, column=0, sticky="ew", padx=16, pady=(0, 16))
        bottom.grid_columnconfigure(0, weight=1)
        outline_button(bottom, _("Cancelar"), self.destroy, width=100).grid(row=0, column=1, padx=(8, 0))
        ctk.CTkButton(bottom, text=_("Guardar"), width=100, fg_color=ACCENT, hover_color=ACCENT_HOVER,
                      text_color=ACCENT_TEXT, command=self._save).grid(row=0, column=2, padx=(8, 0))

    def _copy_report(self) -> None:
        self.clipboard_clear()
        self.clipboard_append(report.build())
        messagebox.showinfo(APP_NAME, _("Informe copiado.") + "\n\n"
                            + _("Pégalo (Ctrl+V) en un mensaje para quien te ayuda o al reportar el problema."),
                            parent=self)

    def _save(self) -> None:
        s = self.app.settings
        old_language = s.language
        s.appearance = self.themes[self.theme.get()]
        s.language = self.languages[self.language.get()]
        s.max_parallel = int(self.parallel.get())
        s.filename_style = self.names[self.name_style.get()]
        s.split_folders = bool(self.split.get())
        s.rate_limit = self.rates[self.rate.get()]
        s.keep_subtitle_files = bool(self.keep_subs.get())
        s.cookies_browser = self.browsers[self.browser.get()]
        s.watch_clipboard = bool(self.clip.get())
        s.notify = bool(self.notify.get())
        s.auto_update = bool(self.auto.get())
        s.save()
        self.app.apply_settings()
        self.destroy()
        # El idioma se aplica al volver a abrir la app.
        if s.language != old_language and i18n.resolve(s.language) != i18n.current():
            if messagebox.askyesno(APP_NAME, _("El idioma cambiará al reiniciar CarryIt.") + "\n\n"
                                   + _("¿Reiniciar ahora?")):
                self.app._restart()
