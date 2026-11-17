"""Actualiza yt-dlp sin pip, para que funcione igual en el .exe y en el entorno de Python.

Descarga la rueda (.whl) oficial desde PyPI, verifica su SHA-256 y la descomprime en
%APPDATA%\\CarryIt\\lib. Un buscador de módulos hace que `import yt_dlp` use esa
copia si es más nueva que la incluida en la app. Este módulo NO importa yt_dlp al cargarse.
"""
from __future__ import annotations

import hashlib
import importlib.machinery
import importlib.metadata
import json
import os
import re
import shutil
import sys
import tempfile
import urllib.request
import zipfile

from . import APP_ID, GITHUB_REPO, __version__
from .i18n import _
from .settings import data_dir

PACKAGES = ("yt_dlp", "yt_dlp_ejs")
CHECK_INTERVAL = 24 * 3600  # revisar como máximo una vez al día
_UA = f"{APP_ID}/{__version__}"


def lib_dir() -> str:
    return os.path.join(data_dir(), "lib")


def _vt(version: str) -> tuple[int, ...]:
    return tuple(int(x) for x in re.findall(r"\d+", version or "0"))


def bundled_version() -> str:
    """Versión de yt-dlp incluida en la app (sin la copia actualizada)."""
    try:
        return importlib.metadata.version("yt-dlp")
    except importlib.metadata.PackageNotFoundError:
        return "0"


def user_version() -> str | None:
    try:
        with open(os.path.join(lib_dir(), "yt_dlp", "version.py"), encoding="utf-8") as fh:
            m = re.search(r"__version__\s*=\s*['\"]([^'\"]+)", fh.read())
        return m.group(1) if m else None
    except OSError:
        return None


# --------------------------------------------------------------------------- #
# Buscador de módulos
# --------------------------------------------------------------------------- #
class _UserLibFinder:
    def find_spec(self, name, path=None, target=None):
        if name.split(".")[0] not in PACKAGES:
            return None
        return importlib.machinery.PathFinder.find_spec(name, list(path) if path else [lib_dir()])


_finder = _UserLibFinder()


def activate() -> str | None:
    """Llamar antes de importar yt_dlp. Devuelve la versión activada o None."""
    uv = user_version()
    if not uv:
        return None
    if _vt(uv) <= _vt(bundled_version()):
        # La app trae una versión igual o más nueva: la copia descargada sobra.
        shutil.rmtree(lib_dir(), ignore_errors=True)
        return None
    if _finder not in sys.meta_path:
        sys.meta_path.insert(0, _finder)
    return uv


def deactivate(remove: bool = False) -> None:
    """Vuelve a la versión incluida (por ejemplo si la descargada no carga)."""
    if _finder in sys.meta_path:
        sys.meta_path.remove(_finder)
    for mod in [m for m in sys.modules if m.split(".")[0] in PACKAGES]:
        del sys.modules[mod]
    if remove:
        shutil.rmtree(lib_dir(), ignore_errors=True)


# --------------------------------------------------------------------------- #
# Consulta e instalación
# --------------------------------------------------------------------------- #
def _get(url: str, timeout: int = 30) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": _UA})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def _wheel(data: dict) -> dict:
    for u in data["urls"]:
        if u["packagetype"] == "bdist_wheel" and u["filename"].endswith("-py3-none-any.whl"):
            return u
    raise RuntimeError(_("PyPI no tiene una versión compatible."))


def latest_release() -> tuple[str, list[dict]]:
    """(versión más reciente, [ruedas de yt-dlp y yt-dlp-ejs])."""
    data = json.loads(_get("https://pypi.org/pypi/yt-dlp/json"))
    version = data["info"]["version"]
    wheels = [_wheel(data)]
    for req in data["info"].get("requires_dist") or []:
        m = re.match(r"yt-dlp-ejs\s*==\s*([\w.]+)", req)
        if m:
            ejs = json.loads(_get(f"https://pypi.org/pypi/yt-dlp-ejs/{m.group(1)}/json"))
            wheels.append(_wheel(ejs))
            break
    return version, wheels


def _install(wheels: list[dict]) -> None:
    target = lib_dir()
    new, old = target + ".new", target + ".old"
    shutil.rmtree(new, ignore_errors=True)
    os.makedirs(new)
    root = os.path.realpath(new)
    with tempfile.TemporaryDirectory(prefix="dyt-") as tmp:
        for w in wheels:
            blob = _get(w["url"], timeout=120)
            if hashlib.sha256(blob).hexdigest() != w["digests"]["sha256"]:
                raise RuntimeError(_("La descarga de {file} está dañada (SHA-256 no coincide).").format(
                    file=w["filename"]))
            path = os.path.join(tmp, w["filename"])
            with open(path, "wb") as fh:
                fh.write(blob)
            with zipfile.ZipFile(path) as zf:
                for name in zf.namelist():
                    dest = os.path.realpath(os.path.join(new, name))
                    if not dest.startswith(root + os.sep):
                        raise RuntimeError(_("La actualización descargada contiene un archivo sospechoso."))
                zf.extractall(new)
    if not os.path.isfile(os.path.join(new, "yt_dlp", "__init__.py")):
        raise RuntimeError(_("La actualización descargada no contiene yt-dlp."))
    shutil.rmtree(old, ignore_errors=True)
    if os.path.exists(target):
        os.replace(target, old)
    os.replace(new, target)
    shutil.rmtree(old, ignore_errors=True)


def check_app_release() -> dict | None:
    """Busca una versión nueva de la app en GitHub Releases.

    No descarga ni instala nada: devuelve {"version", "url"} para que el usuario la baje desde la página.
    """
    if not GITHUB_REPO:
        return None
    try:
        data = json.loads(_get(f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"))
    except Exception:
        return None
    tag = (data.get("tag_name") or "").lstrip("vV")
    if tag and _vt(tag) > _vt(__version__) and not data.get("draft") and not data.get("prerelease"):
        return {"version": tag, "url": data.get("html_url") or f"https://github.com/{GITHUB_REPO}/releases/latest"}
    return None


def check_and_update(current: str) -> dict:
    """Busca una versión nueva y la instala. No cambia el yt-dlp ya cargado en memoria.

    Devuelve {"status": "updated" | "current" | "error", "version": str, "message": str}.
    """
    try:
        latest, wheels = latest_release()
        if _vt(latest) <= _vt(current):
            return {"status": "current", "version": current, "message": ""}
        if user_version() == latest:  # ya descargada, falta reiniciar
            return {"status": "updated", "version": latest, "message": ""}
        _install(wheels)
        return {"status": "updated", "version": latest, "message": ""}
    except Exception as exc:
        shutil.rmtree(lib_dir() + ".new", ignore_errors=True)
        return {"status": "error", "version": current, "message": str(exc)}
