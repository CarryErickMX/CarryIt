"""Sesiones iniciadas dentro de CarryIt para sitios que piden cuenta (Instagram, Facebook, X…).

Chrome y Edge no dejan que otros programas lean sus cookies (cifrado «App-Bound» desde 2024), así que
CarryIt abre Microsoft Edge (viene con Windows) en una ventana propia, con un perfil aparte en
%APPDATA%\\CarryIt\\navegador. La persona entra a su cuenta como siempre y, en cuanto el sitio da la
cookie de sesión, CarryIt la lee por el protocolo de depuración de Edge (solo en 127.0.0.1), la guarda en
%APPDATA%\\CarryIt\\sesiones.txt (formato Netscape, el que entienden yt-dlp y gallery-dl) y cierra la ventana.
"""
from __future__ import annotations

import atexit
import json
import os
import re
import shutil
import sqlite3
import subprocess
import tempfile
import threading
import time
import urllib.parse
from dataclasses import dataclass

from .i18n import _
from .settings import data_dir

LOGIN_TIMEOUT = 15 * 60          # segundos que se espera a que la persona entre a su cuenta


@dataclass(frozen=True)
class Site:
    name: str
    domains: tuple[str, ...]
    cookie: str                  # cookie que solo existe con la sesión iniciada
    login_url: str
    value: str | None = None     # valor que debe tener (si importa)


SITES: dict[str, Site] = {
    "instagram": Site("Instagram", ("instagram.com",), "sessionid", "https://www.instagram.com/accounts/login/"),
    "facebook": Site("Facebook", ("facebook.com", "fb.watch"), "c_user", "https://www.facebook.com/login/"),
    "x": Site("X (Twitter)", ("x.com", "twitter.com"), "auth_token", "https://x.com/i/flow/login"),
    "tiktok": Site("TikTok", ("tiktok.com",), "sessionid", "https://www.tiktok.com/login"),
    "reddit": Site("Reddit", ("reddit.com",), "reddit_session", "https://www.reddit.com/login/"),
    "pinterest": Site("Pinterest", ("pinterest.com", "pin.it"), "_auth", "https://www.pinterest.com/login/", "1"),
}

_lock = threading.Lock()


def cookies_file() -> str:
    return os.path.join(data_dir(), "sesiones.txt")


def profile_dir() -> str:
    return os.path.join(data_dir(), "navegador")


def _matches(domain: str, site: Site) -> bool:
    domain = domain.lower().lstrip(".")
    return any(domain == d or domain.endswith("." + d) for d in site.domains)


def site_for_url(url: str) -> str | None:
    """Clave del sitio (de SITES) al que pertenece el enlace, si CarryIt sabe iniciar sesión en él."""
    host = (urllib.parse.urlparse(url.strip()).hostname or "").lower()
    if not host:
        return None
    for key, site in SITES.items():
        if _matches(host, site):
            return key
    # Dominios de país (pinterest.com.mx, pinterest.es…)
    if re.search(r"(^|\.)pinterest\.[a-z.]+$", host):
        return "pinterest"
    return None


# --------------------------------------------------------------------------- #
# Archivo de cookies (formato Netscape)
# --------------------------------------------------------------------------- #
def _load() -> list[dict]:
    cookies = []
    try:
        with open(cookies_file(), encoding="utf-8") as fh:
            for line in fh:
                line = line.rstrip("\n")
                if line.startswith("#HttpOnly_"):
                    line = line[len("#HttpOnly_"):]
                elif not line or line.startswith("#"):
                    continue
                parts = line.split("\t")
                if len(parts) != 7:
                    continue
                domain, _flag, path, secure, expires, name, value = parts
                cookies.append({"domain": domain, "path": path, "secure": secure == "TRUE",
                                "expires": int(expires or 0), "name": name, "value": value})
    except (OSError, ValueError):
        pass
    return cookies


def _save(cookies: list[dict]) -> None:
    path = cookies_file()
    if not cookies:
        try:
            os.remove(path)
        except OSError:
            pass
        return
    lines = ["# Netscape HTTP Cookie File", "# Sesiones iniciadas en CarryIt. No compartas este archivo.", ""]
    for c in cookies:
        domain = c["domain"]
        lines.append("\t".join((domain, "TRUE" if domain.startswith(".") else "FALSE", c.get("path") or "/",
                                "TRUE" if c.get("secure") else "FALSE", str(max(0, int(c.get("expires") or 0))),
                                c["name"], c["value"])))
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as fh:
        fh.write("\n".join(lines) + "\n")
    os.replace(tmp, path)


def _is_logged(cookies: list[dict], site: Site) -> bool:
    now = time.time()
    for c in cookies:
        if c["name"] == site.cookie and _matches(c["domain"], site) and c["value"] \
                and (site.value is None or c["value"] == site.value) \
                and (not c.get("expires") or c["expires"] <= 0 or c["expires"] > now):
            return True
    return False


def logged_in(key: str) -> bool:
    return _is_logged(_load(), SITES[key])


def has_session_for(url: str) -> bool:
    key = site_for_url(url)
    return bool(key) and logged_in(key)


def has_any() -> bool:
    cookies = _load()
    return any(_is_logged(cookies, s) for s in SITES.values())


def logout(key: str) -> None:
    """Borra la sesión del sitio: del archivo de CarryIt y del perfil de Edge (para poder entrar con otra
    cuenta)."""
    site = SITES[key]
    with _lock:
        _save([c for c in _load() if not _matches(c["domain"], site)])
    for db in (os.path.join(profile_dir(), "Default", "Network", "Cookies"),
               os.path.join(profile_dir(), "Default", "Cookies")):
        if os.path.isfile(db):
            try:
                con = sqlite3.connect(db, timeout=2)
                with con:
                    for d in site.domains:
                        con.execute("DELETE FROM cookies WHERE host_key = ? OR host_key LIKE ?", (d, "%." + d))
                con.close()
            except sqlite3.Error:
                pass


# --------------------------------------------------------------------------- #
# Copias temporales para los motores (yt-dlp reescribe el archivo de cookies al terminar)
# --------------------------------------------------------------------------- #
_tmp_dir: str | None = None


def _cleanup() -> None:
    if _tmp_dir:
        shutil.rmtree(_tmp_dir, ignore_errors=True)


def cookie_copy() -> str | None:
    """Copia privada del archivo de sesiones para una descarga, o None si no hay sesiones."""
    global _tmp_dir
    src = cookies_file()
    if not os.path.isfile(src):
        return None
    with _lock:
        if _tmp_dir is None:
            _tmp_dir = tempfile.mkdtemp(prefix="carryit-sesiones-")
            atexit.register(_cleanup)
        fd, path = tempfile.mkstemp(suffix=".txt", dir=_tmp_dir)
        os.close(fd)
        shutil.copyfile(src, path)
    return path


# --------------------------------------------------------------------------- #
# Inicio de sesión con Edge
# --------------------------------------------------------------------------- #
def find_browser() -> str | None:
    """Edge (incluido en Windows 10 y 11); si no está, Chrome."""
    candidates = []
    for base in (os.environ.get("ProgramFiles(x86)"), os.environ.get("ProgramFiles"),
                 os.environ.get("LOCALAPPDATA")):
        if base:
            candidates.append(os.path.join(base, "Microsoft", "Edge", "Application", "msedge.exe"))
    try:
        import winreg
        for exe in ("msedge.exe", "chrome.exe"):
            for hive in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
                try:
                    with winreg.OpenKey(hive, rf"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\{exe}") as k:
                        candidates.append(winreg.QueryValue(k, None))
                except OSError:
                    pass
    except ImportError:
        pass
    for base in (os.environ.get("ProgramFiles"), os.environ.get("ProgramFiles(x86)"),
                 os.environ.get("LOCALAPPDATA")):
        if base:
            candidates.append(os.path.join(base, "Google", "Chrome", "Application", "chrome.exe"))
    for path in candidates:
        if path and os.path.isfile(path.strip('"')):
            return path.strip('"')
    return None


class LoginError(Exception):
    pass


class Login:
    """Abre la ventana para entrar a la cuenta y espera la sesión. `run()` bloquea (usar en un hilo).

    Devuelve True si se guardó la sesión, False si la persona cerró la ventana o canceló.
    """

    def __init__(self, key: str) -> None:
        self.key = key
        self.site = SITES[key]
        self._proc: subprocess.Popen | None = None
        self._cancel = threading.Event()

    def cancel(self) -> None:
        """Cierra la ventana (en el siguiente segundo) y termina sin guardar nada."""
        self._cancel.set()

    def run(self) -> bool:
        from websockets.sync.client import connect
        browser = find_browser()
        if not browser:
            raise LoginError(_("No se encontró Microsoft Edge ni Google Chrome, que se usan para iniciar sesión."))
        profile = profile_dir()
        os.makedirs(profile, exist_ok=True)
        port_file = os.path.join(profile, "DevToolsActivePort")
        try:
            os.remove(port_file)
        except OSError:
            pass
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        self._proc = subprocess.Popen(
            [browser, f"--user-data-dir={profile}", "--remote-debugging-port=0", "--no-first-run",
             "--no-default-browser-check", f"--app={self.site.login_url}", "--window-size=560,820"],
            creationflags=flags)
        try:
            url = self._debugger_url(port_file)
            if url is None:
                return False
            with connect(url, max_size=None, open_timeout=10) as ws:
                return self._wait_for_session(ws)
        finally:
            if self._proc.poll() is None:
                try:
                    self._proc.wait(5)
                except subprocess.TimeoutExpired:
                    self._proc.kill()

    def _debugger_url(self, port_file: str) -> str | None:
        """Dirección local del protocolo de depuración de Edge (Edge la escribe en el perfil al abrir)."""
        start = time.time()
        while True:
            if self._cancel.is_set():
                self._proc.kill()
                return None
            if os.path.isfile(port_file):
                try:
                    with open(port_file, encoding="utf-8") as fh:
                        port, path = fh.read().split()[:2]
                    return f"ws://127.0.0.1:{int(port)}{path}"
                except (OSError, ValueError):
                    pass                     # Edge aún lo está escribiendo
            if self._proc.poll() is not None and time.time() - start > 3:
                raise LoginError(_("La ventana para iniciar sesión se cerró antes de abrir. Si Edge ya estaba "
                                   "abierto con esta ventana, ciérrala y vuelve a intentarlo."))
            if time.time() - start > 25:
                raise LoginError(_("No se pudo abrir la ventana para iniciar sesión (Edge no respondió)."))
            time.sleep(0.2)

    def _wait_for_session(self, ws) -> bool:
        msg_id = 0

        def call(method: str, **params):
            nonlocal msg_id
            msg_id += 1
            ws.send(json.dumps({"id": msg_id, "method": method, "params": params}))
            while True:
                reply = json.loads(ws.recv(timeout=15))
                if reply.get("id") == msg_id:
                    if "error" in reply:
                        raise LoginError(str(reply["error"].get("message")))
                    return reply.get("result") or {}

        def site_cookies() -> list[dict]:
            raw = call("Storage.getCookies").get("cookies", [])
            return [{"domain": c["domain"], "path": c.get("path") or "/", "secure": bool(c.get("secure")),
                     "expires": int(c["expires"]) if (c.get("expires") or 0) > 0 else 0,
                     "name": c["name"], "value": c.get("value", "")}
                    for c in raw if _matches(c.get("domain", ""), self.site)]

        start = time.time()
        while not self._cancel.is_set() and time.time() - start < LOGIN_TIMEOUT:
            try:
                cookies = site_cookies()
            except Exception:
                return False                 # la persona cerró la ventana
            if _is_logged(cookies, self.site):
                time.sleep(1.5)              # que el sitio termine de poner el resto de sus cookies
                try:
                    cookies = site_cookies() or cookies
                except Exception:
                    pass
                with _lock:
                    others = [c for c in _load() if not _matches(c["domain"], self.site)]
                    _save(others + cookies)
                try:
                    call("Browser.close")
                except Exception:
                    pass
                return True
            if self._proc.poll() is not None:
                return False
            time.sleep(1)
        try:
            call("Browser.close")
        except Exception:
            pass
        return False
