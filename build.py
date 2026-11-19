"""Genera los archivos para publicar una versión: el instalador y la versión portátil (ZIP).

Uso:
    .venv\\Scripts\\python.exe build.py --ffmpeg RUTA\\A\\ffmpeg\\bin [--sin-instalador]

Resultado en dist\\:
    CarryIt\\                              la app lista (exe + _internal + deno + ffmpeg + licencias)
    CarryIt-Setup-X.Y.Z.exe                instalador (Inno Setup)
    CarryIt-X.Y.Z-portable.zip             versión portátil
    SHA256SUMS.txt                          huellas para verificar las descargas

Requisitos: pip install pyinstaller, Inno Setup 6 (ISCC.exe) y una carpeta de FFmpeg con
ffmpeg.exe y ffprobe.exe (y sus .dll si es una compilación "shared").

Firma digital (opcional): si la variable de entorno SIGN_COMMAND existe, se ejecuta para cada
archivo a firmar, reemplazando {file}. Ejemplo con un certificado instalado:
    set SIGN_COMMAND=signtool sign /fd sha256 /tr http://timestamp.digicert.com /td sha256 /a "{file}"
Sin firma, Windows mostrará advertencias (SmartScreen) y Smart App Control puede bloquear la app.
"""
from __future__ import annotations

import argparse
import glob
import hashlib
import os
import shlex
import shutil
import subprocess
import sys
import zipfile

ROOT = os.path.dirname(os.path.abspath(__file__))
NAME = "CarryIt"
DIST = os.path.join(ROOT, "dist")
APP_DIR = os.path.join(DIST, NAME)
EXE = os.path.join(APP_DIR, f"{NAME}.exe")
BUILD = os.path.join(ROOT, "build")

sys.path.insert(0, ROOT)
from carryit import __version__ as VERSION, resource  # noqa: E402


def step(msg: str) -> None:
    print(f"\n=== {msg} ===", flush=True)


def clean() -> None:
    for path in (APP_DIR, os.path.join(BUILD, "pyinstaller")):
        if os.path.exists(path):
            try:
                shutil.rmtree(path)
            except PermissionError:
                sys.exit(f"No se puede borrar «{path}». Cierra «{NAME}» y vuelve a intentarlo.")
    os.makedirs(BUILD, exist_ok=True)


def make_icon() -> str:
    """El ícono ya viene hecho en carryit/resources (lo genera tools/branding.py)."""
    return resource("icon.ico")


def write_version_file() -> str:
    nums = tuple(([int(x) for x in VERSION.split(".")] + [0, 0, 0, 0])[:4])
    path = os.path.join(BUILD, "version.txt")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(f"""VSVersionInfo(
  ffi=FixedFileInfo(filevers={nums}, prodvers={nums}),
  kids=[StringFileInfo([StringTable('040A04B0', [
    StringStruct('FileDescription', '{NAME}'),
    StringStruct('ProductName', '{NAME}'),
    StringStruct('FileVersion', '{VERSION}'),
    StringStruct('ProductVersion', '{VERSION}'),
    StringStruct('LegalCopyright', 'Licencia MIT'),
    StringStruct('OriginalFilename', '{NAME}.exe')])]),
    VarFileInfo([VarStruct('Translation', [0x040A, 1200])])]
)
""")
    return path


def run_pyinstaller(icon: str) -> None:
    import PyInstaller.__main__
    PyInstaller.__main__.run([
        os.path.join(ROOT, "main.py"),
        "--name", NAME,
        "--windowed",
        "--onedir",
        "--noconfirm",
        "--clean",
        "--icon", icon,
        "--splash", os.path.join(ROOT, "branding", "splash.png"),   # logo mientras carga el .exe
        "--version-file", write_version_file(),
        "--distpath", DIST,
        "--workpath", os.path.join(BUILD, "pyinstaller"),
        "--specpath", BUILD,
        "--paths", ROOT,
        "--add-data", f"{os.path.join(ROOT, 'carryit', 'resources')}{os.pathsep}carryit/resources",
        "--collect-all", "customtkinter",   # temas y fuentes de la interfaz
        "--collect-all", "yt_dlp_ejs",      # scripts JS para resolver los retos de YouTube
        "--copy-metadata", "yt-dlp",        # el actualizador compara contra esta versión
        "--collect-submodules", "gallery_dl",  # extractores de imágenes (se cargan por nombre)
        "--copy-metadata", "gallery-dl",    # el actualizador compara contra esta versión
        "--exclude-module", "deno",         # el binario de Deno se copia aparte
    ])


def copy_deno() -> None:
    from carryit.core import find_deno
    deno = find_deno()
    if not deno:
        sys.exit("No se encontró deno.exe (pip install deno).")
    shutil.copy2(deno, APP_DIR)


def copy_ffmpeg(src: str | None) -> None:
    if not src:
        print("AVISO: sin --ffmpeg; la app ofrecerá instalar FFmpeg con winget en cada PC.")
        return
    if not os.path.isfile(os.path.join(src, "ffmpeg.exe")) or not os.path.isfile(os.path.join(src, "ffprobe.exe")):
        sys.exit(f"«{src}» no contiene ffmpeg.exe y ffprobe.exe.")
    dest = os.path.join(APP_DIR, "ffmpeg", "bin")
    os.makedirs(dest, exist_ok=True)
    for pattern in ("ffmpeg.exe", "ffprobe.exe", "*.dll"):
        for f in glob.glob(os.path.join(src, pattern)):
            shutil.copy2(f, dest)
    lic = os.path.join(os.path.dirname(src.rstrip("\\/")), "LICENSE.txt")
    if os.path.isfile(lic):
        shutil.copy2(lic, os.path.join(APP_DIR, "ffmpeg", "LICENSE.txt"))


def copy_docs() -> None:
    for name in ("LICENSE", "THIRD_PARTY_NOTICES.md"):
        shutil.copy2(os.path.join(ROOT, name), APP_DIR)


def sign(path: str) -> None:
    cmd = os.environ.get("SIGN_COMMAND")
    if not cmd:
        return
    print(f"Firmando {os.path.basename(path)}…")
    subprocess.run(shlex.split(cmd.replace("{file}", path), posix=False), check=True)


def find_iscc() -> str:
    candidates = [
        os.environ.get("ISCC", ""),
        shutil.which("ISCC") or "",
        os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs", "Inno Setup 6", "ISCC.exe"),
        r"C:\Program Files (x86)\Inno Setup 6\ISCC.exe",
        r"C:\Program Files\Inno Setup 6\ISCC.exe",
    ]
    for c in candidates:
        if c and os.path.isfile(c):
            return c
    sys.exit("No se encontró Inno Setup 6 (ISCC.exe). Instálalo con: winget install JRSoftware.InnoSetup")


def build_installer(icon: str) -> str:
    subprocess.run([
        find_iscc(), "/Q",
        f"/DAppVersion={VERSION}",
        f"/DSourceDir={APP_DIR}",
        f"/DOutputDir={DIST}",
        f"/DIconFile={icon}",
        os.path.join(ROOT, "installer", "CarryIt.iss"),
    ], check=True)
    return os.path.join(DIST, f"CarryIt-Setup-{VERSION}.exe")


def build_zip() -> str:
    path = os.path.join(DIST, f"CarryIt-{VERSION}-portable.zip")
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        for root, _dirs, files in os.walk(APP_DIR):
            for f in files:
                full = os.path.join(root, f)
                zf.write(full, os.path.join(NAME, os.path.relpath(full, APP_DIR)))
    return path


def sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--ffmpeg", help="carpeta con ffmpeg.exe y ffprobe.exe para incluir")
    ap.add_argument("--sin-instalador", action="store_true", help="no generar el instalador")
    args = ap.parse_args()

    step(f"Compilando {NAME} {VERSION}")
    clean()
    for old in glob.glob(os.path.join(DIST, "CarryIt-*")) + glob.glob(os.path.join(DIST, "SHA256SUMS.txt")):
        os.remove(old)
    icon = make_icon()
    run_pyinstaller(icon)

    step("Agregando Deno, FFmpeg y licencias")
    copy_deno()
    copy_ffmpeg(args.ffmpeg)
    copy_docs()
    sign(EXE)

    outputs = []
    step("Creando ZIP portátil")
    outputs.append(build_zip())
    if not args.sin_instalador:
        step("Creando instalador")
        setup = build_installer(icon)
        sign(setup)
        outputs.append(setup)

    with open(os.path.join(DIST, "SHA256SUMS.txt"), "w", encoding="utf-8") as fh:
        for out in outputs:
            fh.write(f"{sha256(out)}  {os.path.basename(out)}\n")

    step("Listo")
    for out in outputs:
        print(f"{os.path.getsize(out) / 1024 / 1024:7.1f} MB  {out}")
    if not os.environ.get("SIGN_COMMAND"):
        print("\nAVISO: los archivos NO están firmados; Windows mostrará advertencias al abrirlos.")


if __name__ == "__main__":
    main()
