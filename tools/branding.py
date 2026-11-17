"""Genera toda la identidad visual de CarryIt a partir de los diseños originales.

Entrada (diseños hechos a mano, en branding/fuente/):
    logo-principal-original.webp   símbolo completo + nombre CarryIt
    icono-original.webp            ícono de la app

Salida:
    branding/svg/      logo principal, ícono y símbolo en SVG (vectorizados)
    branding/png/      PNG 256 y 512 (y 1024) de cada pieza, con fondo transparente
    branding/ico/      carryit.ico para Windows (16 a 256 px)
    carryit/resources/ archivos que usa la app (ícono, logo del encabezado, tema de colores)
    installer/         imágenes del asistente de instalación
    branding/splash.png  pantalla de carga del .exe

Cómo funciona: las formas se separan por color (plateado / dorado), se vectorizan con potrace
y se rellenan con los mismos degradados del diseño. Para pasar SVG a PNG se usa Microsoft Edge
en modo sin ventana (viene con Windows), que dibuja degradados y brillos igual que un navegador.

Uso:  .venv\\Scripts\\python.exe tools\\branding.py      (requiere: pip install potracer numpy)
"""
from __future__ import annotations

import copy
import json
import os
import shutil
import subprocess
import tempfile

import numpy as np
import potrace
from PIL import Image, ImageFilter

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "branding", "fuente")
OUT_SVG = os.path.join(ROOT, "branding", "svg")
OUT_PNG = os.path.join(ROOT, "branding", "png")
OUT_ICO = os.path.join(ROOT, "branding", "ico")
RES = os.path.join(ROOT, "carryit", "resources")
INSTALLER = os.path.join(ROOT, "installer")

BLACK = "#0B0B0C"
UPSCALE = 4  # se vectoriza a 4x para que las curvas salgan suaves


# --------------------------------------------------------------------------- #
# 1. Separar por color y vectorizar
# --------------------------------------------------------------------------- #
def load_masks(name: str):
    a = np.asarray(Image.open(os.path.join(SRC, name)).convert("RGB")).astype(np.float32) / 255
    v = a.max(axis=2)
    s = np.where(v > 0, (v - a.min(axis=2)) / np.maximum(v, 1e-6), 0)
    silver = (v > 0.45) & (s < 0.18)
    gold = (v > 0.55) & (s > 0.55)
    return silver, gold


def region(mask: np.ndarray, x0, y0, x1, y1) -> np.ndarray:
    out = np.zeros_like(mask)
    out[y0:y1, x0:x1] = mask[y0:y1, x0:x1]
    return out


def trace(mask: np.ndarray) -> str:
    """Máscara booleana -> atributo d de un <path> (coordenadas de la imagen original)."""
    if not mask.any():
        return ""
    x0, y0, x1, y1 = bbox(mask)
    x0, y0 = max(x0 - 6, 0), max(y0 - 6, 0)
    x1, y1 = min(x1 + 7, mask.shape[1]), min(y1 + 7, mask.shape[0])
    img = Image.fromarray((mask[y0:y1, x0:x1] * 255).astype(np.uint8))
    big = img.resize((img.width * UPSCALE, img.height * UPSCALE), Image.LANCZOS)
    big = big.filter(ImageFilter.GaussianBlur(UPSCALE * 0.6))
    # potracer rellena lo "oscuro" (como en una imagen en blanco y negro): se le pasa la forma en negro.
    bm = potrace.Bitmap(np.asarray(big) <= 127)
    plist = bm.trace(turdsize=40 * UPSCALE, alphamax=1.0, opticurve=True, opttolerance=0.25)

    def p(pt) -> str:
        return f"{x0 + pt.x / UPSCALE:.2f} {y0 + pt.y / UPSCALE:.2f}"

    parts = []
    for curve in plist:
        parts.append(f"M{p(curve.start_point)}")
        for seg in curve.segments:
            if seg.is_corner:
                parts.append(f"L{p(seg.c)}L{p(seg.end_point)}")
            else:
                parts.append(f"C{p(seg.c1)} {p(seg.c2)} {p(seg.end_point)}")
        parts.append("Z")
    return "".join(parts)


def components(mask: np.ndarray, min_px: int = 300) -> list[np.ndarray]:
    """Separa una máscara en piezas sueltas (relleno por inundación, sin dependencias extra)."""
    h, w = mask.shape
    seen = np.zeros_like(mask)
    pieces = []
    ys, xs = np.nonzero(mask)
    for y, x in zip(ys, xs):
        if seen[y, x]:
            continue
        stack, pix = [(y, x)], []
        seen[y, x] = True
        while stack:
            cy, cx = stack.pop()
            pix.append((cy, cx))
            for ny, nx in ((cy + 1, cx), (cy - 1, cx), (cy, cx + 1), (cy, cx - 1)):
                if 0 <= ny < h and 0 <= nx < w and mask[ny, nx] and not seen[ny, nx]:
                    seen[ny, nx] = True
                    stack.append((ny, nx))
        if len(pix) >= min_px:
            piece = np.zeros_like(mask)
            py, px = zip(*pix)
            piece[list(py), list(px)] = True
            pieces.append(piece)
    return pieces


def solid_rows(mask: np.ndarray) -> np.ndarray:
    """Rellena cada fila entre su primer y último píxel: convierte trazos borrosos en barras sólidas.

    Se ignoran las filas muy cortas de los bordes (restos del desenfoque de movimiento).
    """
    out = np.zeros_like(mask)
    ys = np.nonzero(mask.any(axis=1))[0]
    widths = {y: np.nonzero(mask[y])[0] for y in ys}
    longest = max(len(x) for x in widths.values())
    for y, xs in widths.items():
        if xs.max() - xs.min() > longest * 0.35:
            out[y, xs.min():xs.max() + 1] = True
    return out


def bbox(mask: np.ndarray):
    ys, xs = np.nonzero(mask)
    return xs.min(), ys.min(), xs.max(), ys.max()


# --------------------------------------------------------------------------- #
# 2. Piezas del diseño
# --------------------------------------------------------------------------- #
def logo_parts() -> dict:
    silver, gold = load_masks("logo-principal-original.webp")
    parts = {
        "c": trace(region(silver, 520, 90, 1110, 500)),          # la «C»
        "tray": trace(region(silver, 620, 490, 1010, 600)),      # la bandeja
        "carry": trace(region(silver, 220, 595, 1110, 860)),     # "Carry"
        "it": trace(region(gold, 1050, 595, 1330, 800)),         # "It"
        "swoosh": trace(region(gold, 220, 795, 900, 885)),       # subrayado
        "play": trace(region(gold, 740, 200, 945, 395)),
        "arrow": trace(region(gold, 700, 395, 935, 585)),
        "lines": [trace(solid_rows(m)) for m in components(region(gold, 340, 180, 600, 440))],
    }
    return parts


def icon_parts() -> dict:
    silver, gold = load_masks("icono-original.webp")
    return {
        "c": trace(region(silver, 300, 170, 1080, 800)),
        "play": trace(region(gold, 560, 360, 850, 640)),
        "arrow": trace(region(gold, 480, 640, 850, 980)),
        "bbox": (325, 185, 1062, 968),  # caja de C + play + flecha en la imagen original
    }


# --------------------------------------------------------------------------- #
# 3. SVG
# --------------------------------------------------------------------------- #
def defs(light: bool = False) -> str:
    """Degradados del diseño. light=True: versión para fondos claros (plateado -> grafito)."""
    if light:
        silver = ('<stop offset="0" stop-color="#4A4A50"/><stop offset=".55" stop-color="#2A2A2F"/>'
                  '<stop offset="1" stop-color="#141416"/>')
    else:
        silver = ('<stop offset="0" stop-color="#FFFFFF"/><stop offset=".55" stop-color="#E2E2E2"/>'
                  '<stop offset="1" stop-color="#A9A9A9"/>')
    return f"""<defs>
  <linearGradient id="silver" x1="0" y1="0" x2="0" y2="1">{silver}</linearGradient>
  <linearGradient id="gold" x1="0" y1="0" x2="1" y2="1">
    <stop offset="0" stop-color="#FFE81A"/><stop offset=".5" stop-color="#FFB800"/><stop offset="1" stop-color="#FF7A00"/>
  </linearGradient>
  <linearGradient id="goldV" x1="0" y1="0" x2="0" y2="1">
    <stop offset="0" stop-color="#FFE81A"/><stop offset=".55" stop-color="#FFB800"/><stop offset="1" stop-color="#FF7A00"/>
  </linearGradient>
  <linearGradient id="speed" x1="0" y1="0" x2="1" y2="0">
    <stop offset="0" stop-color="#FFB800" stop-opacity="0"/><stop offset=".45" stop-color="#FFC400" stop-opacity=".95"/>
    <stop offset="1" stop-color="#FF8A00"/>
  </linearGradient>
  <linearGradient id="swoosh" x1="0" y1="0" x2="1" y2="0">
    <stop offset="0" stop-color="#FF8A00" stop-opacity=".15"/><stop offset=".55" stop-color="#FFB800"/>
    <stop offset="1" stop-color="#FFE81A"/>
  </linearGradient>
  <radialGradient id="glow" cx=".5" cy=".5" r=".5">
    <stop offset="0" stop-color="#FF9A00" stop-opacity=".55"/><stop offset="1" stop-color="#FF9A00" stop-opacity="0"/>
  </radialGradient>
  <linearGradient id="frame" x1="0" y1="0" x2="1" y2="1">
    <stop offset="0" stop-color="#FFD000"/><stop offset=".38" stop-color="#3A3A3E"/>
    <stop offset=".62" stop-color="#3A3A3E"/><stop offset="1" stop-color="#FF8A00"/>
  </linearGradient>
  <filter id="soft" x="-20%" y="-20%" width="140%" height="140%"><feGaussianBlur stdDeviation="14"/></filter>
</defs>"""


def svg_doc(view: str, body: str, w: int, h: int, light: bool = False, title: str = "CarryIt") -> str:
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{view}" width="{w}" height="{h}">\n'
            f"<title>{title}</title>\n{defs(light)}\n{body}\n</svg>\n")


def gold_shape(d: str, grad: str = "gold") -> str:
    # El contorno negro separa el dorado del plateado, como en el diseño.
    return (f'<path d="{d}" fill="url(#{grad})" stroke="{BLACK}" stroke-width="7" '
            f'paint-order="stroke" stroke-linejoin="round" fill-rule="evenodd"/>')


def logo_svg(p: dict, light: bool = False, background: bool = False) -> str:
    x0, y0, x1, y1 = 200, 80, 1340, 900          # recorte del lienzo original
    w, h = x1 - x0, y1 - y0
    body = []
    if background:
        body.append(f'<rect x="{x0}" y="{y0}" width="{w}" height="{h}" fill="{BLACK}"/>')
    body.append('<ellipse cx="820" cy="600" rx="190" ry="26" fill="url(#glow)"/>')
    body += [f'<path d="{d}" fill="url(#speed)" fill-rule="evenodd"/>' for d in p["lines"]]
    body.append(f'<path d="{p["c"]}" fill="url(#silver)" fill-rule="evenodd"/>')
    body.append(f'<path d="{p["tray"]}" fill="url(#silver)" fill-rule="evenodd"/>')
    body.append(gold_shape(p["play"]))
    body.append(gold_shape(p["arrow"], "goldV"))
    body.append(f'<path d="{p["swoosh"]}" fill="url(#swoosh)" fill-rule="evenodd"/>')
    body.append(f'<path d="{p["carry"]}" fill="url(#silver)" fill-rule="evenodd"/>')
    body.append(f'<path d="{p["it"]}" fill="url(#goldV)" fill-rule="evenodd"/>')
    return svg_doc(f"{x0} {y0} {w} {h}", "\n".join(body), w, h, light, "CarryIt")


def symbol_group(p: dict, size: float, cx: float, cy: float) -> str:
    """C + play + flecha del ícono, escalado para caber en un cuadro de `size` centrado en (cx, cy)."""
    bx0, by0, bx1, by1 = p["bbox"]
    s = size / max(bx1 - bx0, by1 - by0)
    tx, ty = cx - s * (bx0 + bx1) / 2, cy - s * (by0 + by1) / 2
    return (f'<g transform="translate({tx:.2f} {ty:.2f}) scale({s:.5f})">'
            f'<path d="{p["c"]}" fill="url(#silver)" fill-rule="evenodd"/>'
            f'{gold_shape(p["play"])}{gold_shape(p["arrow"], "goldV")}</g>')


def icon_small_svg(p: dict) -> str:
    """Versión para 16–64 px (barra de tareas, explorador): sin margen ni brillo, borde dorado grueso
    para que destaque en barras oscuras, y el símbolo más grande."""
    body = [
        f'<rect x="20" y="20" width="984" height="984" rx="210" fill="{BLACK}" '
        f'stroke="url(#goldV)" stroke-width="40"/>',
        symbol_group(p, 800, 512, 512),
    ]
    return svg_doc("0 0 1024 1024", "\n".join(body), 1024, 1024, title="CarryIt")


def icon_svg(p: dict) -> str:
    body = [
        '<rect x="64" y="64" width="896" height="896" rx="200" fill="none" stroke="#FFA000" '
        'stroke-opacity=".45" stroke-width="26" filter="url(#soft)"/>',
        f'<rect x="64" y="64" width="896" height="896" rx="200" fill="{BLACK}" stroke="url(#frame)" stroke-width="14"/>',
        symbol_group(p, 640, 512, 512),
    ]
    return svg_doc("0 0 1024 1024", "\n".join(body), 1024, 1024, title="CarryIt")


def symbol_svg(p: dict, light: bool = False) -> str:
    return svg_doc("0 0 1024 1024", symbol_group(p, 900, 512, 512), 1024, 1024, light, "CarryIt")


# --------------------------------------------------------------------------- #
# 4. SVG -> PNG con Edge sin ventana
# --------------------------------------------------------------------------- #
def find_edge() -> str:
    for c in (r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
              r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"):
        if os.path.isfile(c):
            return c
    raise SystemExit("No se encontró Microsoft Edge para convertir SVG a PNG.")


def render(svg_path: str, png_path: str, w: int, h: int, background: str = "transparent") -> None:
    # Edge no maneja bien ventanas diminutas: se dibuja en una de al menos 400 px y luego se recorta.
    win_w, win_h = max(w, 400), max(h, 400)
    with tempfile.TemporaryDirectory(prefix="carryit-render-") as tmp:
        html = os.path.join(tmp, "page.html")
        shot = os.path.join(tmp, "shot.png")
        uri = "file:///" + svg_path.replace("\\", "/")
        with open(html, "w", encoding="utf-8") as fh:
            fh.write(f'<!doctype html><html><body style="margin:0;background:transparent">'
                     f'<div style="width:{w}px;height:{h}px;background:{background}">'
                     f'<img src="{uri}" style="display:block;width:{w}px;height:{h}px"></div></body></html>')
        subprocess.run([
            find_edge(), "--headless=new", "--disable-gpu", "--hide-scrollbars", "--no-first-run",
            "--force-device-scale-factor=1", "--default-background-color=00000000",
            f"--user-data-dir={os.path.join(tmp, 'perfil')}", f"--window-size={win_w},{win_h}",
            f"--screenshot={shot}", "file:///" + html.replace("\\", "/"),
        ], check=True, capture_output=True, timeout=120)
        Image.open(shot).convert("RGBA").crop((0, 0, w, h)).save(png_path)


def write_ico(frames: list[Image.Image], path: str) -> None:
    """Escribe un .ico en el formato clásico, el más compatible con Windows (Escritorio, Explorador,
    accesos directos): tamaños chicos como mapa de bits de 32 bits con transparencia y 256 px en PNG.
    """
    import io
    import struct
    entries, blobs = [], []
    for im in sorted(frames, key=lambda f: f.width):
        im = im.convert("RGBA")
        w, h = im.size
        if w >= 256:
            buf = io.BytesIO()
            im.save(buf, format="PNG")
            data = buf.getvalue()
        else:
            header = struct.pack("<IiiHHIIiiII", 40, w, h * 2, 1, 32, 0, 0, 0, 0, 0, 0)
            r, g, b, a = im.split()
            bgra = Image.merge("RGBA", (b, g, r, a)).transpose(Image.FLIP_TOP_BOTTOM).tobytes()
            mask_row = ((w + 31) // 32) * 4           # máscara AND de 1 bit, filas alineadas a 4 bytes
            data = header + bgra + b"\x00" * (mask_row * h)
        entries.append((w, h, data))
        blobs.append(data)
    offset = 6 + 16 * len(entries)
    out = struct.pack("<HHH", 0, 1, len(entries))
    for w, h, data in entries:
        out += struct.pack("<BBBBHHII", w % 256, h % 256, 0, 0, 1, 32, len(data), offset)
        offset += len(data)
    with open(path, "wb") as fh:
        fh.write(out + b"".join(blobs))


def fit_square(src: str, dst: str, size: int) -> None:
    """Coloca una imagen apaisada dentro de un lienzo cuadrado transparente."""
    im = Image.open(src).convert("RGBA")
    im.thumbnail((size, size), Image.LANCZOS)
    canvas = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    canvas.alpha_composite(im, ((size - im.width) // 2, (size - im.height) // 2))
    canvas.save(dst)


# --------------------------------------------------------------------------- #
# 5. Tema de colores de la interfaz (negro + dorado)
# --------------------------------------------------------------------------- #
def make_theme() -> None:
    import customtkinter
    base = os.path.join(os.path.dirname(customtkinter.__file__), "assets", "themes", "blue.json")
    with open(base, encoding="utf-8") as fh:
        t = copy.deepcopy(json.load(fh))
    gold, gold_hover, ink = "#FFB300", "#FF9100", "#111111"
    text = ["gray10", "#ECECEC"]
    t["CTk"]["fg_color"] = ["#F2F2F4", "#0E0E10"]
    t["CTkToplevel"]["fg_color"] = ["#F2F2F4", "#0E0E10"]
    t["CTkFrame"].update(fg_color=["#E4E4E8", "#17171A"], top_fg_color=["#D9D9DE", "#1F1F23"],
                         border_color=["#B8B8BE", "#34343A"])
    t["CTkButton"].update(fg_color=[gold, gold], hover_color=[gold_hover, gold_hover], text_color=[ink, ink],
                          border_color=["#8A8A92", "#55555C"], text_color_disabled=["gray55", "gray45"])
    t["CTkLabel"]["text_color"] = text
    t["CTkEntry"].update(fg_color=["#FFFFFF", "#1F1F23"], border_color=["#B8B8BE", "#34343A"], text_color=text)
    t["CTkCheckBox"].update(fg_color=[gold, gold], hover_color=[gold_hover, gold_hover],
                            checkmark_color=[ink, ink], border_color=["#6E6E76", "#8A8A92"], text_color=text)
    t["CTkSwitch"]["progress_color"] = [gold, gold]
    t["CTkRadioButton"].update(fg_color=[gold, gold], hover_color=[gold_hover, gold_hover], text_color=text)
    t["CTkProgressBar"].update(fg_color=["#CFCFD4", "#2A2A2F"], progress_color=[gold, gold])
    t["CTkSlider"].update(button_color=[gold, gold], button_hover_color=[gold_hover, gold_hover])
    t["CTkOptionMenu"].update(fg_color=["#D9D9DE", "#26262B"], button_color=["#CBCBD1", "#303036"],
                              button_hover_color=["#BDBDC4", "#3A3A41"], text_color=text)
    t["CTkComboBox"].update(fg_color=["#FFFFFF", "#1F1F23"], border_color=["#B8B8BE", "#34343A"],
                            button_color=["#B8B8BE", "#34343A"], text_color=text)
    t["CTkScrollbar"].update(button_color=["#B8B8BE", "#3A3A41"], button_hover_color=["#9A9AA2", "#4A4A52"])
    t["CTkSegmentedButton"].update(fg_color=["#D9D9DE", "#26262B"], selected_color=[gold, gold],
                                   selected_hover_color=[gold_hover, gold_hover],
                                   unselected_color=["#D9D9DE", "#26262B"],
                                   unselected_hover_color=["#CBCBD1", "#303036"])
    t["CTkTextbox"].update(fg_color=["#FFFFFF", "#17171A"], text_color=text)
    t["CTkScrollableFrame"]["label_fg_color"] = ["#D9D9DE", "#1F1F23"]
    t["DropdownMenu"].update(fg_color=["#F2F2F4", "#1F1F23"], hover_color=["#E0E0E4", "#2E2E33"], text_color=text)
    with open(os.path.join(RES, "theme.json"), "w", encoding="utf-8") as fh:
        json.dump(t, fh, indent=2)


# --------------------------------------------------------------------------- #
def main() -> None:
    for d in (OUT_SVG, OUT_PNG, OUT_ICO, RES):
        os.makedirs(d, exist_ok=True)

    print("Vectorizando…")
    lp, ip = logo_parts(), icon_parts()
    svgs = {
        "carryit-logo.svg": logo_svg(lp),                         # para fondos oscuros (transparente)
        "carryit-logo-claro.svg": logo_svg(lp, light=True),       # para fondos claros
        "carryit-logo-fondo-negro.svg": logo_svg(lp, background=True),
        "carryit-icono.svg": icon_svg(ip),                        # ícono de la app (Windows)
        "carryit-icono-chico.svg": icon_small_svg(ip),            # el mismo, optimizado para 16–64 px
        "carryit-simbolo.svg": symbol_svg(ip),                    # solo C + play + flecha, sin fondo
        "carryit-simbolo-claro.svg": symbol_svg(ip, light=True),
    }
    for name, text in svgs.items():
        with open(os.path.join(OUT_SVG, name), "w", encoding="utf-8") as fh:
            fh.write(text)

    print("Exportando PNG…")
    svg = lambda n: os.path.join(OUT_SVG, n)  # noqa: E731
    png = lambda n: os.path.join(OUT_PNG, n)  # noqa: E731
    for size in (256, 512, 1024):
        render(svg("carryit-icono.svg"), png(f"carryit-icono-{size}.png"), size, size)
        render(svg("carryit-simbolo.svg"), png(f"carryit-simbolo-{size}.png"), size, size)
    # Logo principal: tamaño completo (1140 x 820) y versiones cuadradas 256 / 512.
    render(svg("carryit-logo.svg"), png("carryit-logo.png"), 1140, 820)
    render(svg("carryit-logo-claro.svg"), png("carryit-logo-claro.png"), 1140, 820)
    render(svg("carryit-logo-fondo-negro.svg"), png("carryit-logo-fondo-negro.png"), 1140, 820)
    for size in (256, 512):
        fit_square(png("carryit-logo.png"), png(f"carryit-logo-{size}.png"), size)
        fit_square(png("carryit-logo-claro.png"), png(f"carryit-logo-claro-{size}.png"), size)

    print("Creando ICO…")
    sizes = [16, 20, 24, 32, 40, 48, 64, 128, 256]
    with tempfile.TemporaryDirectory() as tmp:
        frames = []
        for s in sizes:
            path = os.path.join(tmp, f"{s}.png")
            render(svg("carryit-icono-chico.svg" if s <= 64 else "carryit-icono.svg"), path, s, s)
            frames.append(Image.open(path).convert("RGBA"))
        write_ico(frames, os.path.join(OUT_ICO, "carryit.ico"))

    print("Recursos de la app e instalador…")
    shutil.copy2(os.path.join(OUT_ICO, "carryit.ico"), os.path.join(RES, "icon.ico"))
    shutil.copy2(png("carryit-icono-512.png"), os.path.join(RES, "icon.png"))
    Image.open(png("carryit-simbolo-256.png")).save(os.path.join(RES, "logo_symbol.png"))
    render(svg("carryit-simbolo-claro.svg"), os.path.join(RES, "logo_symbol_light.png"), 256, 256)
    for old in ("logo_symbol_dark.png",):
        if os.path.exists(os.path.join(RES, old)):
            os.remove(os.path.join(RES, old))

    # Pantalla de carga del .exe: logo con margen sobre negro.
    splash = Image.new("RGBA", (600, 420), (11, 11, 12, 255))
    logo = Image.open(png("carryit-logo.png")).convert("RGBA")
    logo.thumbnail((450, 320), Image.LANCZOS)
    splash.alpha_composite(logo, ((600 - logo.width) // 2, (420 - logo.height) // 2))
    splash.convert("RGB").save(os.path.join(ROOT, "branding", "splash.png"))
    # Asistente de instalación: imagen lateral (164x314 y 2x) e ícono pequeño (55x55 y 2x).
    for scale in (1, 2):
        w, h = 164 * scale, 314 * scale
        side = Image.new("RGB", (w, h), (11, 11, 12))
        logo = Image.open(png("carryit-logo-512.png")).convert("RGBA")
        logo.thumbnail((int(w * 0.92), int(w * 0.92)), Image.LANCZOS)
        side.paste(logo, ((w - logo.width) // 2, int(h * 0.30)), logo)
        side.save(os.path.join(INSTALLER, f"wizard-{scale}x.bmp"))
        s = 55 * scale
        small = Image.new("RGB", (s, s), (255, 255, 255))
        ic = Image.open(png("carryit-icono-256.png")).convert("RGBA").resize((s, s), Image.LANCZOS)
        small.paste(ic, (0, 0), ic)
        small.save(os.path.join(INSTALLER, f"wizard-small-{scale}x.bmp"))

    make_theme()
    print("Listo.")


if __name__ == "__main__":
    main()
