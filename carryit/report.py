"""Informe de diagnóstico que el usuario puede copiar y enviar cuando algo falla."""
from __future__ import annotations

import os
import platform
import sys
import time

from . import APP_NAME, GITHUB_REPO, __version__, core
from .i18n import _
from .settings import data_dir


def _log_tail(lines: int = 40) -> str:
    try:
        with open(os.path.join(data_dir(), "app.log"), encoding="utf-8", errors="replace") as fh:
            return "".join(fh.readlines()[-lines:]).strip()
    except OSError:
        return _("(sin registro)")


def _hide_user(text: str) -> str:
    """Quita el nombre de usuario de Windows de las rutas, por privacidad."""
    home = os.path.expanduser("~")
    return text.replace(home, "%USERPROFILE%") if home and home != "~" else text


def build(error: str = "", options: core.DownloadOptions | None = None) -> str:
    yes, no = _("sí"), _("NO")
    parts = [
        "## " + _("Informe de {app}").format(app=APP_NAME),
        "- " + _("Fecha") + f": {time.strftime('%Y-%m-%d %H:%M')}",
        f"- {APP_NAME}: {__version__} ("
        + (_("instalado") if getattr(sys, "frozen", False) else _("código fuente")) + ")",
        f"- yt-dlp: {core.ytdlp_version()}",
        f"- Windows: {platform.platform()}",
        f"- Python: {platform.python_version()}",
        f"- FFmpeg: {yes if core.find_ffmpeg() else no} · Deno: {yes if core.find_deno() else no}",
    ]
    if options is not None:
        if options.mode == "audio":
            rate = _("original") if options.audio_bitrate == "orig" else f"{options.audio_bitrate} kbps"
            what = f"audio {options.audio_format} {rate}"
        else:
            what = f"video {options.video_format} {options.height or _('máx.')}"
        parts += ["- " + _("Enlace") + f": {options.url}",
                  "- " + _("Descarga") + f": {what}" + (" · " + _("lista") if options.playlist else "")]
    if error:
        parts += ["", "### " + _("Error"), error]
    parts += ["", "### " + _("Registro (últimas líneas)"), "```", _log_tail(), "```"]
    if GITHUB_REPO:
        parts += ["", _("Repórtalo en:") + f" https://github.com/{GITHUB_REPO}/issues"]
    return _hide_user("\n".join(parts))
