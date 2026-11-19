"""Revisa las traducciones de CarryIt.

1. Textos marcados con _("...") que no tienen traducción al inglés en carryit/i18n.py.
2. Traducciones que ya no se usan.
3. Textos en español que parecen visibles y no están marcados con _() (para revisar a mano).

Uso:  .venv\\Scripts\\python.exe tools\\i18n_check.py      (código de salida 1 si falta algo)
"""
from __future__ import annotations

import ast
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from carryit.i18n import EN  # noqa: E402

FILES = ["gui.py", "dialogs.py", "core.py", "report.py", "updater.py", "images.py", "sessions.py"]
SPANISH = re.compile(r"[áéíóúñ¿¡]|\b(el|la|los|las|de|del|para|con|una?|que|no|se|en)\b", re.I)
IGNORE_CALLS = {"warning", "error", "exception", "info", "debug"}  # mensajes del registro (para soporte)


def scan(path: str):
    tree = ast.parse(open(path, encoding="utf-8").read())
    marked, inside_mark, loose = set(), set(), []
    docstrings = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)) and node.body:
            first = node.body[0]
            if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant):
                docstrings.add(id(first.value))
        if isinstance(node, ast.Call):
            name = node.func.id if isinstance(node.func, ast.Name) else (
                node.func.attr if isinstance(node.func, ast.Attribute) else "")
            if name == "_" and node.args and isinstance(node.args[0], ast.Constant):
                marked.add(node.args[0].value)
                inside_mark.add(id(node.args[0]))
            if name in IGNORE_CALLS:
                for sub in ast.walk(node):
                    inside_mark.add(id(sub))
    for node in ast.walk(tree):
        if (isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in inside_mark
                and id(node) not in docstrings and SPANISH.search(node.value) and len(node.value) > 3):
            loose.append((node.lineno, node.value))
    return marked, loose


def main() -> int:
    all_marked: set[str] = set()
    problems = 0
    for name in FILES:
        marked, loose = scan(os.path.join(ROOT, "carryit", name))
        all_marked |= marked
        for line, text in loose:
            print(f"SIN MARCAR  {name}:{line}  {text[:90]!r}")
    missing = sorted(all_marked - set(EN))
    for text in missing:
        print(f"SIN TRADUCIR  {text!r}")
    unused = sorted(set(EN) - all_marked)
    for text in unused:
        print(f"SOBRANTE  {text!r}")
    print(f"\nTextos marcados: {len(all_marked)} · traducidos: {len(all_marked & set(EN))} · "
          f"faltan: {len(missing)} · sobrantes: {len(unused)}")
    problems = len(missing)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
