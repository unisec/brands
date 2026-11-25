#!/usr/bin/env python3
"""Gera as logos de boot (U-Boot da Rockchip) da Unicontrol em bootlogo/.

É a imagem exibida pelo bootloader ao ligar o tablet, antes da bootanimation
do Android. No TPA08 ela fica na partição `logo` (/dev/block/by-name/logo).

Formato exigido pelo U-Boot, copiado da logo de fábrica:
  - BMP 24 bits, sem compressão, linhas de baixo para cima (altura positiva);
  - 260 x 500 (em pé): o U-Boot desenha direto no painel, que é retrato,
    então a arte deitada (500 x 260) é girada 90° no sentido horário;
  - fundo preto, que se funde com o resto da tela.

Para cada variante são gerados:
  <nome>.svg          arte deitada, em vetor
  <nome>-preview.png  arte deitada, 500 x 260, para ver como fica no tablet
  logo.bmp            arquivo pronto para gravar na partição `logo`

Uso:
    python3 scripts/generate-bootlogo.py

Depende do Google Chrome (CHROME_BIN para outro binário) e do `sips` (macOS).
"""

import importlib.util
import struct
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "bootlogo"

_spec = importlib.util.spec_from_file_location(
    "wallpapers", ROOT / "scripts" / "generate-wallpapers.py"
)
wp = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(wp)

TEAL, BLUE = wp.TEAL, wp.BLUE
W, H = 500, 260  # arte deitada; o BMP final é H x W
MAX_BMP = 1024 * 1024  # tamanho da partição `logo` no TPA08

GRADIENT = f"""
<linearGradient id="ring" x1="0" y1="0" x2="1" y2="1">
  <stop offset="0" stop-color="{TEAL}"/>
  <stop offset="1" stop-color="{BLUE}"/>
</linearGradient>"""


def background():
    return f'<rect width="{W}" height="{H}" fill="#000000"/>'


def wordmark_left(x, y, height, color):
    return (
        f'<text x="{x:.2f}" y="{y:.2f}" text-anchor="start" dominant-baseline="central" '
        f'fill="{color}" font-family="Roboto, \'Helvetica Neue\', Arial, sans-serif" '
        f'font-weight="700" font-size="{height:.2f}" '
        f'letter-spacing="{height * 0.04:.2f}">UNICONTROL</text>'
    )


# ---------------------------------------------------------------- variantes


def horizontal():
    """Símbolo à esquerda e marca em branco à direita, como o logo.png."""
    size = 110
    cx, cy = 85, H / 2
    body = [
        background(),
        wp.symbol(cx, cy, size),
        wordmark_left(cx + size / 2 + 22, cy, 42, "#FFFFFF"),
    ]
    return wp.svg(W, H, "", "\n".join(body))


def stacked():
    """Símbolo no centro com a marca embaixo."""
    size = 140
    cx, cy = W / 2, H / 2 - 22
    body = [
        background(),
        wp.symbol(cx, cy, size),
        wp.wordmark(cx, cy + size / 2 + 44, 30, "#FFFFFF"),
    ]
    return wp.svg(W, H, "", "\n".join(body))


def symbol():
    """Só o símbolo, nas cores da marca."""
    body = [background(), wp.symbol(W / 2, H / 2, 180)]
    return wp.svg(W, H, "", "\n".join(body))


def gradient():
    """Símbolo com anéis em degradê teal → azul e marca embaixo."""
    size = 140
    cx, cy = W / 2, H / 2 - 22
    body = [
        background(),
        wp.symbol(cx, cy, size, outer="url(#ring)", inner="url(#ring)", dot=BLUE),
        wp.wordmark(cx, cy + size / 2 + 44, 30, "#FFFFFF"),
    ]
    return wp.svg(W, H, GRADIENT, "\n".join(body))


def mono():
    """Tudo em branco: discreto, bom para painéis de parede."""
    size = 110
    cx, cy = 85, H / 2
    white = "#FFFFFF"
    body = [
        background(),
        wp.symbol(cx, cy, size, outer=white, inner=white, dot=white),
        wordmark_left(cx + size / 2 + 22, cy, 42, white),
    ]
    return wp.svg(W, H, "", "\n".join(body))


VARIANTS = {
    "horizontal": horizontal,
    "stacked": stacked,
    "symbol": symbol,
    "gradient": gradient,
    "mono": mono,
}


# ---------------------------------------------------------------- BMP


def to_uboot_bmp(png, bmp):
    """Gira 90° horário e grava BMP 24 bits de baixo para cima.

    O `sips` grava o BMP de cima para baixo (altura negativa), formato que o
    U-Boot da Rockchip não garante ler; por isso as linhas são reordenadas.
    """
    with tempfile.TemporaryDirectory() as tmp:
        rotated = Path(tmp) / "rot.png"
        raw = Path(tmp) / "raw.bmp"
        subprocess.run(["sips", "-r", "90", str(png), "--out", str(rotated)],
                       check=True, capture_output=True)
        subprocess.run(["sips", "-s", "format", "bmp", str(rotated), "--out", str(raw)],
                       check=True, capture_output=True)
        data = raw.read_bytes()

    offset = struct.unpack_from("<I", data, 10)[0]
    width, height = struct.unpack_from("<ii", data, 18)
    bpp = struct.unpack_from("<H", data, 28)[0]
    if bpp == 32:
        src_stride = width * 4
    elif bpp == 24:
        src_stride = (width * 3 + 3) & ~3
    else:
        raise SystemExit(f"BMP inesperado: {bpp} bits")

    rows = []
    for y in range(abs(height)):
        line = data[offset + y * src_stride: offset + (y + 1) * src_stride]
        if bpp == 32:
            line = b"".join(line[i:i + 3] for i in range(0, width * 4, 4))
        else:
            line = line[: width * 3]
        rows.append(line)
    if height < 0:  # de cima para baixo → inverte para o formato clássico
        rows.reverse()

    stride = (width * 3 + 3) & ~3
    pad = b"\0" * (stride - width * 3)
    pixels = b"".join(r + pad for r in rows)
    header = struct.pack(
        "<2sIHHIIiiHHIIiiII",
        b"BM", 54 + len(pixels), 0, 0, 54,
        40, width, abs(height), 1, 24, 0, len(pixels), 2835, 2835, 0, 0,
    )
    bmp.write_bytes(header + pixels)
    if bmp.stat().st_size > MAX_BMP:
        raise SystemExit(f"{bmp} passa de 1 MB")


def main():
    chrome = wp.chrome_bin()
    for name, fn in VARIANTS.items():
        folder = OUT / name
        folder.mkdir(parents=True, exist_ok=True)
        svg_path = folder / f"{name}.svg"
        png_path = folder / f"{name}-preview.png"
        svg_path.write_text(fn())
        wp.render_png(svg_path, png_path, W, H, chrome)
        to_uboot_bmp(png_path, folder / "logo.bmp")
        print(f"ok {folder.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
