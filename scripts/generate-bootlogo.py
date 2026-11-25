#!/usr/bin/env python3
"""Gera as logos de boot (U-Boot da Rockchip) da Unicontrol em bootlogo/.

É a imagem exibida pelo bootloader ao ligar o tablet, antes da bootanimation
do Android. No TPA08 ela fica na partição `logo` (/dev/block/by-name/logo).

Formato exigido pelo U-Boot, copiado da logo de fábrica:
  - BMP 24 bits, sem compressão, linhas de baixo para cima (altura positiva);
  - 260 x 500 (em pé): o U-Boot desenha direto no painel, que é retrato,
    então a arte deitada (500 x 260) é girada 90° no sentido horário;
  - fundo preto, que se funde com o resto da tela.

Todas as variantes têm o símbolo, a marca UNICONTROL e o slogan
AMBIENTES INTELIGENTES; o que muda é a composição e as cores.

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


FONT = "Roboto, 'Helvetica Neue', Arial, sans-serif"
NAME = "UNICONTROL"
TAGLINE = "AMBIENTES INTELIGENTES"
WHITE = "#FFFFFF"
GREY = "#AEB8C2"


def text(x, y, content, size, color, width, weight=700, anchor="start"):
    """Texto em caixa alta com largura fixa (`textLength`).

    Fixar a largura deixa marca e slogan alinhados nas duas pontas,
    independente da fonte que o Chrome encontrar no sistema.
    `y` é o centro vertical das maiúsculas.
    """
    baseline = y + size * 0.36  # altura de maiúscula ≈ 0.72 em
    return (
        f'<text x="{x:.2f}" y="{baseline:.2f}" text-anchor="{anchor}" fill="{color}" '
        f'font-family="{FONT}" font-weight="{weight}" font-size="{size:.2f}" '
        f'textLength="{width:.2f}" lengthAdjust="spacingAndGlyphs">{content}</text>'
    )


def lockup_side(cx, size, name_color, tag_color, **sym):
    """Símbolo à esquerda; marca e slogan empilhados à direita."""
    cy = H / 2
    x = cx + size / 2 + 24
    width = W - x - 32
    return [
        wp.symbol(cx, cy, size, **sym),
        text(x, cy - 13, NAME, 40, name_color, width),
        text(x, cy + 25, TAGLINE, 15, tag_color, width, weight=500),
    ]


def lockup_stacked(size, name_color, tag_color, **sym):
    """Símbolo no centro; marca e slogan centralizados embaixo."""
    cx = W / 2
    cy = 18 + size / 2
    name_y = cy + size / 2 + 32
    width = 230
    return [
        wp.symbol(cx, cy, size, **sym),
        text(cx, name_y, NAME, 32, name_color, width, anchor="middle"),
        text(cx, name_y + 31, TAGLINE, 12.5, tag_color, width, weight=500, anchor="middle"),
    ]


# ---------------------------------------------------------------- variantes


def horizontal():
    """Símbolo à esquerda, marca em branco e slogan em cinza à direita."""
    return wp.svg(W, H, "", "\n".join([background(), *lockup_side(82, 116, WHITE, GREY)]))


def stacked():
    """Símbolo no centro, marca e slogan embaixo."""
    return wp.svg(W, H, "", "\n".join([background(), *lockup_stacked(132, WHITE, GREY)]))


def accent():
    """Como a stacked, mas com o slogan na cor da marca."""
    return wp.svg(W, H, "", "\n".join([background(), *lockup_stacked(132, WHITE, TEAL)]))


def gradient():
    """Anéis em degradê teal → azul, marca e slogan embaixo."""
    ring = {"outer": "url(#ring)", "inner": "url(#ring)", "dot": BLUE}
    body = [background(), *lockup_stacked(132, WHITE, GREY, **ring)]
    return wp.svg(W, H, GRADIENT, "\n".join(body))


def mono():
    """Tudo em branco: discreto, bom para painéis de parede."""
    white = {"outer": WHITE, "inner": WHITE, "dot": WHITE}
    body = [background(), *lockup_side(82, 116, WHITE, WHITE, **white)]
    return wp.svg(W, H, "", "\n".join(body))


VARIANTS = {
    "horizontal": horizontal,
    "stacked": stacked,
    "accent": accent,
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
