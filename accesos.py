"""Crea los accesos directos «CarryIt» en el Escritorio y en el menú Inicio (versión de desarrollo).

Apuntan a pythonw.exe del entorno .venv (firmado por la Python Software Foundation), así la app
abre sin consola y Smart App Control de Windows 11 no la bloquea. También borra los accesos con
el nombre anterior de la app.

Uso:  .venv\\Scripts\\python.exe accesos.py
"""
from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
NAME = "CarryIt"
OLD_NAMES = ["Descargador YT"]


def icon_copy() -> str:
    """Copia el ícono con un nombre que cambia cuando cambia el diseño.

    Windows guarda en caché el ícono de cada acceso directo según la ruta del archivo. Si el
    archivo se llama siempre igual, sigue mostrando el ícono viejo; con un nombre nuevo no puede.
    """
    src = os.path.join(ROOT, "carryit", "resources", "icon.ico")
    with open(src, "rb") as fh:
        digest = hashlib.sha1(fh.read()).hexdigest()[:10]
    folder = os.path.join(ROOT, "assets")   # carpeta local, fuera de Git (.gitignore)
    os.makedirs(folder, exist_ok=True)
    dest = os.path.join(folder, f"carryit-{digest}.ico")
    for old in os.listdir(folder):
        if old.endswith(".ico") and os.path.join(folder, old) != dest:
            try:
                os.remove(os.path.join(folder, old))
            except OSError:
                pass
    shutil.copy2(src, dest)
    return dest


def main() -> None:
    pythonw = os.path.join(ROOT, ".venv", "Scripts", "pythonw.exe")
    if not os.path.isfile(pythonw):
        sys.exit("No existe .venv\\Scripts\\pythonw.exe. Ejecuta primero instalar.bat.")
    icon = icon_copy()
    main_py = os.path.join(ROOT, "main.py")
    old = ",".join(f"'{n}.lnk'" for n in OLD_NAMES)
    ps = f"""
$sh = New-Object -ComObject WScript.Shell
foreach ($dir in @([Environment]::GetFolderPath('Desktop'), [Environment]::GetFolderPath('Programs'))) {{
    foreach ($o in @({old})) {{
        $p = Join-Path $dir $o
        if (Test-Path $p) {{ Remove-Item $p; Write-Output "Acceso anterior borrado: $p" }}
    }}
    $lnk = $sh.CreateShortcut((Join-Path $dir '{NAME}.lnk'))
    $lnk.TargetPath = '{pythonw}'
    $lnk.Arguments = '"{main_py}"'
    $lnk.WorkingDirectory = '{ROOT}'
    $lnk.IconLocation = '{icon},0'
    $lnk.Description = 'Descarga videos o solo el audio'
    $lnk.Save()
    Write-Output "Acceso directo creado: $($lnk.FullName)"
}}
"""
    subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps], check=True)


if __name__ == "__main__":
    main()
