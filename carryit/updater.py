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

# Motores que se actualizan solos: paquete de Python -> nombre en PyPI.
ENGINES = {"yt_dlp": "yt-dlp", "gallery_dl": "gallery-dl"}
COMPANIONS = {"yt_dlp": ("yt_dlp_ejs",)}          # paquetes que acompañan a un motor
PACKAGES = ("yt_dlp", "yt_dlp_ejs", "gallery_dl")
CHECK_INTERVAL = 24 * 3600  # revisar como máximo una vez al día
_UA = f"{APP_ID}/{__version__}"
_active: set[str] = set()     # paquetes que se cargan desde la copia actualizada


def lib_dir() -> str:
    return os.path.join(data_dir(), "lib")


def _vt(version: str) -> tuple[int, ...]:
    return tuple(int(x) for x in re.findall(r"\d+", version or "0"))


def bundled_version(dist: str = "yt-dlp") -> str:
    """Versión del motor incluida en la app (sin la copia actualizada)."""
    try:
        return importlib.metadata.version(dist)
    except importlib.metadata.PackageNotFoundError:
        return "0"


def user_version(pkg: str = "yt_dlp") -> str | None:
    """Versión del motor descargado en la carpeta lib de los datos de CarryIt (None si no hay)."""
    try:
        with open(os.path.join(lib_dir(), pkg, "version.py"), encoding="utf-8") as fh:
            m = re.search(r"__version__\s*=\s*['\"]([^'\"]+)", fh.read())
        return m.group(1) if m else None
    except OSError:
        return None


# --------------------------------------------------------------------------- #
# Buscador de módulos
# --------------------------------------------------------------------------- #
class _UserLibFinder:
    def find_spec(self, name, path=None, target=None):
        if name.split(".")[0] not in _active:
            return None
        return importlib.machinery.PathFinder.find_spec(name, list(path) if path else [lib_dir()])


_finder = _UserLibFinder()


def activate() -> dict[str, str]:
    """Llamar antes de importar los motores. Usa la copia descargada de cada motor solo si es más
    nueva que la incluida. Devuelve {motor: versión activada}."""
    activated = {}
    _active.clear()
    for pkg, dist in ENGINES.items():
        uv = user_version(pkg)
        if uv and _vt(uv) > _vt(bundled_version(dist)):
            _active.add(pkg)
            _active.update(COMPANIONS.get(pkg, ()))
            activated[dist] = uv
    if not _active:
        # La app trae versiones iguales o más nuevas: la copia descargada sobra.
        shutil.rmtree(lib_dir(), ignore_errors=True)
    elif _finder not in sys.meta_path:
        sys.meta_path.insert(0, _finder)
    return activated


def deactivate(remove: bool = False) -> None:
    """Vuelve a las versiones incluidas (por ejemplo si la descargada no carga)."""
    _active.clear()
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


def latest_release() -> dict[str, tuple[str, list[dict]]]:
    """{motor: (versión más reciente, [ruedas a instalar])} de yt-dlp (con yt-dlp-ejs) y gallery-dl."""
    out = {}
    data = json.loads(_get("https://pypi.org/pypi/yt-dlp/json"))
    wheels = [_wheel(data)]
    for req in data["info"].get("requires_dist") or []:
        m = re.match(r"yt-dlp-ejs\s*==\s*([\w.]+)", req)
        if m:
            ejs = json.loads(_get(f"https://pypi.org/pypi/yt-dlp-ejs/{m.group(1)}/json"))
            wheels.append(_wheel(ejs))
            break
    out["yt-dlp"] = (data["info"]["version"], wheels)
    data = json.loads(_get("https://pypi.org/pypi/gallery-dl/json"))
    out["gallery-dl"] = (data["info"]["version"], [_wheel(data)])
    return out


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


def current_versions() -> dict[str, str]:
    """Versiones de los motores que la app está usando ahora (incluidas o actualizadas)."""
    versions = {}
    try:
        import yt_dlp.version
        versions["yt-dlp"] = yt_dlp.version.__version__
    except Exception:
        versions["yt-dlp"] = "0"
    try:
        import gallery_dl.version
        versions["gallery-dl"] = gallery_dl.version.__version__
    except Exception:
        versions["gallery-dl"] = "0"
    return versions


def check_and_update() -> dict:
    """Busca versiones nuevas de los motores y las instala. No cambia lo ya cargado en memoria
    (se usan al reiniciar la app).

    Devuelve {"status": "updated" | "current" | "error", "version": str, "message": str}; en "version"
    va la lista de motores actualizados, p. ej. "yt-dlp 2026.11.20, gallery-dl 1.33.0".
    """
    current = current_versions()
    try:
        latest = latest_release()
        newer = {dist: ver for dist, (ver, _w) in latest.items() if _vt(ver) > _vt(current.get(dist, "0"))}
        if not newer:
            return {"status": "current", "message": "",
                    "version": ", ".join(f"{dist} {ver}" for dist, ver in current.items())}
        label = ", ".join(f"{dist} {ver}" for dist, ver in newer.items())
        pkgs = {v: k for k, v in ENGINES.items()}
        if all(user_version(pkgs[dist]) == ver for dist, ver in newer.items()):
            return {"status": "updated", "version": label, "message": ""}   # ya descargado; falta reiniciar
        _install([w for _ver, wheels in latest.values() for w in wheels])
        return {"status": "updated", "version": label, "message": ""}
    except Exception as exc:
        shutil.rmtree(lib_dir() + ".new", ignore_errors=True)
        return {"status": "error", "version": "", "message": str(exc)}
