#!/usr/bin/env python3
"""Gera os papéis de parede da Unicontrol em wallpaper/.

O símbolo é redesenhado em vetor a partir da geometria medida em
integrations/unicontrol/logo.png (anel externo aberto em cima, anel interno
aberto à direita e ponto central), para escalar sem perda até 4K.

Uso:
    python3 scripts/generate-wallpapers.py            # gera SVG + PNG
    python3 scripts/generate-wallpapers.py --svg-only # só SVG

O PNG é renderizado com o Google Chrome em modo headless (CHROME_BIN para
apontar outro binário).
"""

import math
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "wallpaper"

TEAL = "#37CAB8"
BLUE = "#468DD2"

SIZES = {
    "desktop": (3840, 2160),
    "tablet": (2560, 1600),
    "phone": (1290, 2796),
}

# Geometria do símbolo em unidades do logo.png (raio externo total = 104).
STROKE = 25
OUTER_R = 91.5
OUTER_GAP = (54, 129)  # graus (matemático, anti-horário), pontas incluídas
INNER_R = 49.5
INNER_GAP = (-33, 30)
DOT_R = 20.5
EXTENT = OUTER_R + STROKE / 2  # 104


def _pt(cx, cy, r, deg):
    a = math.radians(deg)
    return cx + r * math.cos(a), cy - r * math.sin(a)


def arc(cx, cy, r, gap, stroke, color, opacity=1.0, extra=""):
    """Arco com pontas arredondadas cobrindo tudo menos `gap` (em graus)."""
    cap = math.degrees((stroke / 2) / r)
    start = gap[1] + cap
    end = gap[0] - cap + 360
    span = end - start
    x1, y1 = _pt(cx, cy, r, start)
    x2, y2 = _pt(cx, cy, r, end)
    large = 1 if span % 360 > 180 else 0
    return (
        f'<path d="M {x1:.2f} {y1:.2f} A {r:.2f} {r:.2f} 0 {large} 0 {x2:.2f} {y2:.2f}" '
        f'fill="none" stroke="{color}" stroke-width="{stroke:.2f}" '
        f'stroke-linecap="round" opacity="{opacity}" {extra}/>'
    )


def symbol(cx, cy, size, outer=TEAL, inner=TEAL, dot=BLUE, opacity=1.0, extra=""):
    """Símbolo com diâmetro total `size`, centrado em (cx, cy)."""
    k = size / (2 * EXTENT)
    return "\n".join(
        [
            arc(cx, cy, OUTER_R * k, OUTER_GAP, STROKE * k, outer, opacity, extra),
            arc(cx, cy, INNER_R * k, INNER_GAP, STROKE * k, inner, opacity, extra),
            f'<circle cx="{cx:.2f}" cy="{cy:.2f}" r="{DOT_R * k:.2f}" fill="{dot}" opacity="{opacity}"/>',
        ]
    )


def ripples(cx, cy, size, color, count, base_opacity, step=42, fade=True):
    """Anéis concêntricos que ecoam o anel externo (abertura em cima)."""
    k = size / (2 * EXTENT)
    out = []
    for i in range(1, count + 1):
        r = (OUTER_R + i * step) * k
        op = base_opacity * ((count - i + 1) / count if fade else 1)
        # alterna a abertura entre cima e direita, como os dois anéis do símbolo
        gap = OUTER_GAP if i % 2 else INNER_GAP
        out.append(arc(cx, cy, r, gap, STROKE * k * 0.55, color, f"{op:.3f}"))
    return "\n".join(out)


def wordmark(cx, y, height, color):
    return (
        f'<text x="{cx:.2f}" y="{y:.2f}" text-anchor="middle" fill="{color}" '
        f'font-family="Roboto, \'Helvetica Neue\', Arial, sans-serif" font-weight="700" '
        f'font-size="{height:.2f}" letter-spacing="{height * 0.04:.2f}">UNICONTROL</text>'
    )


def portrait_boost(w, h):
    """No retrato a menor dimensão é a largura; aumenta o símbolo para não sumir."""
    return 1.4 if h > w else 1.0


def svg(w, h, defs, body):
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}">\n'
        f"<defs>\n{defs}\n</defs>\n{body}\n</svg>\n"
    )


# ---------------------------------------------------------------- variantes


def midnight(w, h):
    """Azul-noite com ondas concêntricas, símbolo e marca no centro."""
    m = min(w, h)
    size = m * 0.26 * portrait_boost(w, h)
    cx, cy = w / 2, h / 2 - m * 0.05
    defs = f"""
<radialGradient id="bg" cx="50%" cy="45%" r="75%">
  <stop offset="0" stop-color="#0F2A44"/>
  <stop offset="1" stop-color="#050B14"/>
</radialGradient>
<radialGradient id="glow" cx="50%" cy="50%" r="50%">
  <stop offset="0" stop-color="{TEAL}" stop-opacity="0.22"/>
  <stop offset="1" stop-color="{TEAL}" stop-opacity="0"/>
</radialGradient>"""
    body = "\n".join(
        [
            f'<rect width="{w}" height="{h}" fill="url(#bg)"/>',
            f'<circle cx="{cx}" cy="{cy}" r="{size * 1.6}" fill="url(#glow)"/>',
            ripples(cx, cy, size, TEAL, 14, 0.10),
            symbol(cx, cy, size),
            wordmark(cx, cy + size * 0.5 + size * 0.42, size * 0.21, "#FFFFFF"),
        ]
    )
    return svg(w, h, defs, body)


def aurora(w, h):
    """Gradiente teal → azul da marca com o símbolo em branco."""
    m = min(w, h)
    size = m * 0.30 * portrait_boost(w, h)
    cx, cy = w / 2, h / 2
    defs = f"""
<linearGradient id="bg" x1="0" y1="0" x2="1" y2="1">
  <stop offset="0" stop-color="{TEAL}"/>
  <stop offset="0.55" stop-color="{BLUE}"/>
  <stop offset="1" stop-color="#1B3556"/>
</linearGradient>"""
    body = "\n".join(
        [
            f'<rect width="{w}" height="{h}" fill="url(#bg)"/>',
            ripples(cx, cy, size, "#FFFFFF", 12, 0.12),
            symbol(cx, cy, size, outer="#FFFFFF", inner="#FFFFFF", dot="#FFFFFF"),
        ]
    )
    return svg(w, h, defs, body)


def light(w, h):
    """Fundo claro, logo colorido e marca escura."""
    m = min(w, h)
    size = m * 0.24 * portrait_boost(w, h)
    cx, cy = w / 2, h / 2 - m * 0.05
    defs = """
<linearGradient id="bg" x1="0" y1="0" x2="0" y2="1">
  <stop offset="0" stop-color="#F7FAFC"/>
  <stop offset="1" stop-color="#E3ECF2"/>
</linearGradient>"""
    body = "\n".join(
        [
            f'<rect width="{w}" height="{h}" fill="url(#bg)"/>',
            ripples(cx, cy, size, TEAL, 14, 0.12),
            symbol(cx, cy, size),
            wordmark(cx, cy + size * 0.5 + size * 0.42, size * 0.21, "#0B0F14"),
        ]
    )
    return svg(w, h, defs, body)


def orbit(w, h):
    """Abstrato: símbolo gigante cortado no canto, sem texto."""
    m = min(w, h)
    if w >= h:
        big = w * 1.05
        cx, cy = w * 0.78, h * 0.62
    else:
        big = w * 1.5
        cx, cy = w * 0.62, h * 0.66
    defs = f"""
<linearGradient id="bg" x1="0" y1="0" x2="1" y2="1">
  <stop offset="0" stop-color="#07121F"/>
  <stop offset="1" stop-color="#0D2236"/>
</linearGradient>
<linearGradient id="ring" x1="0" y1="0" x2="1" y2="1">
  <stop offset="0" stop-color="{TEAL}"/>
  <stop offset="1" stop-color="{BLUE}"/>
</linearGradient>"""
    body = "\n".join(
        [
            f'<rect width="{w}" height="{h}" fill="url(#bg)"/>',
            ripples(cx, cy, big, TEAL, 6, 0.08, fade=False),
            symbol(cx, cy, big, outer="url(#ring)", inner="url(#ring)", dot=BLUE, opacity=0.9),
            symbol(w * 0.5 if w < h else m * 0.16, m * 0.16, m * 0.10),
        ]
    )
    return svg(w, h, defs, body)


def amoled(w, h):
    """Preto puro com símbolo pequeno — bom para OLED e tablets de parede."""
    m = min(w, h)
    size = m * 0.16 * portrait_boost(w, h)
    body = "\n".join(
        [
            f'<rect width="{w}" height="{h}" fill="#000000"/>',
            symbol(w / 2, h / 2, size),
        ]
    )
    return svg(w, h, "", body)


VARIANTS = {
    "midnight": midnight,
    "aurora": aurora,
    "light": light,
    "orbit": orbit,
    "amoled": amoled,
}


def chrome_bin():
    env = os.environ.get("CHROME_BIN")
    if env:
        return env
    for c in [
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        "google-chrome",
        "chromium",
    ]:
        if Path(c).exists() or subprocess.run(["which", c], capture_output=True).returncode == 0:
            return c
    raise SystemExit("Chrome não encontrado; defina CHROME_BIN")


def render_png(svg_path, png_path, w, h, chrome):
    subprocess.run(
        [
            chrome,
            "--headless=new",
            "--disable-gpu",
            "--hide-scrollbars",
            "--force-device-scale-factor=1",
            f"--window-size={w},{h}",
            f"--screenshot={png_path}",
            svg_path.as_uri(),
        ],
        check=True,
        capture_output=True,
    )


def main():
    svg_only = "--svg-only" in sys.argv
    chrome = None if svg_only else chrome_bin()
    for name, fn in VARIANTS.items():
        folder = OUT / name
        folder.mkdir(parents=True, exist_ok=True)
        for label, (w, h) in SIZES.items():
            base = f"{name}-{label}-{w}x{h}"
            svg_path = folder / f"{base}.svg"
            svg_path.write_text(fn(w, h))
            if chrome:
                render_png(svg_path, folder / f"{base}.png", w, h, chrome)
            print(f"ok {svg_path.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
