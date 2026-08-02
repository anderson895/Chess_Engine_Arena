# ═══════════════════════════════════════════════════════════
#  tools/make_nav_masters.py — build assets/ui/nav_masters.png
#
#  The Chess_packs sprite sheet ships six nav cards (RANKINGS,
#  STATISTICS, OPENINGS, TOURNAMENTS, HISTORY, ENGINE) and none of them
#  says "masters", so the Masters DB entry had no card and sat in the
#  header as a plain button among four image cards.
#
#  This composes a matching one: the geometry, fill and label band are
#  measured off nav_statistics.png, and the artwork is the app's own
#  white king sprite — the piece already reads as "top-level player".
#
#  Run:  venv/Scripts/python.exe -X utf8 tools/make_nav_masters.py
# ═══════════════════════════════════════════════════════════

import os

from PIL import Image, ImageDraw, ImageFilter, ImageFont

REFERENCE = os.path.join("assets", "ui", "nav_statistics.png")
PIECE = os.path.join("assets", "pieces", "wK.png")
OUT = os.path.join("assets", "ui", "nav_masters.png")

SIZE = 192
# Measured from the reference card: body spans x 9..181, y 0..189,
# the label sits on rows 156..170, corner radius is about 12.
INSET_X, TOP, BOTTOM = 9, 0, 190
RADIUS = 12
DIVIDER_Y = 138
LABEL_BASE = 170
LABEL = "MASTERS"

FILL_TOP = (14, 21, 28)
FILL_BOTTOM = (8, 13, 18)
EDGE = (30, 38, 48)
DIVIDER = (92, 104, 118)
TEXT = (238, 238, 240)

FONT_SIZE = 20
TRACKING = 2      # px between glyphs; the reference labels are lightly spaced

FONT_CANDIDATES = [
    r"C:\Windows\Fonts\timesbd.ttf",
    r"C:\Windows\Fonts\georgiab.ttf",
    r"C:\Windows\Fonts\constanb.ttf",
]


def load_font(size):
    for path in FONT_CANDIDATES:
        if os.path.isfile(path):
            return ImageFont.truetype(path, size)
    return ImageFont.load_default()


def rounded_mask(box, radius, size=SIZE):
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).rounded_rectangle(box, radius=radius, fill=255)
    return mask


def main():
    if not os.path.isfile(PIECE):
        raise SystemExit(f"missing {PIECE}")

    box = (INSET_X, TOP, SIZE - INSET_X - 1, BOTTOM)

    # Body: vertical gradient clipped to the rounded card shape
    gradient = Image.new("RGB", (1, SIZE))
    for y in range(SIZE):
        t = y / (SIZE - 1)
        gradient.putpixel((0, y), tuple(
            round(a + (b - a) * t) for a, b in zip(FILL_TOP, FILL_BOTTOM)))
    body = gradient.resize((SIZE, SIZE)).convert("RGBA")

    card = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    card.paste(body, (0, 0), rounded_mask(box, RADIUS))

    draw = ImageDraw.Draw(card)
    draw.rounded_rectangle(box, radius=RADIUS, outline=EDGE + (120,), width=1)

    # Divider under the artwork, faded at both ends like the reference
    line = Image.new("RGBA", (SIZE, 3), (0, 0, 0, 0))
    ImageDraw.Draw(line).line([(26, 1), (SIZE - 27, 1)],
                              fill=DIVIDER + (150,), width=1)
    fade = Image.new("L", (SIZE, 3), 0)
    fdraw = ImageDraw.Draw(fade)
    span = SIZE - 52
    for x in range(26, SIZE - 26):
        t = (x - 26) / span
        edge = min(t, 1 - t) * 4          # 0 at the ends, 1 by 25% in
        fdraw.line([(x, 0), (x, 2)], fill=int(255 * min(1.0, edge)))
    line.putalpha(Image.composite(line.getchannel("A"), fade,
                                  Image.new("L", (SIZE, 3), 0)))
    line.putalpha(fade)
    card.alpha_composite(line, (0, DIVIDER_Y))

    # Artwork: the white king, fitted into the space above the divider
    piece = Image.open(PIECE).convert("RGBA")
    piece = piece.crop(piece.getbbox())
    avail_w, avail_h = 124, DIVIDER_Y - 22
    scale = min(avail_w / piece.width, avail_h / piece.height)
    piece = piece.resize((max(1, round(piece.width * scale)),
                          max(1, round(piece.height * scale))), Image.LANCZOS)
    px = (SIZE - piece.width) // 2
    py = 14 + (avail_h - piece.height) // 2

    # Soft glow so the piece separates from the near-black card
    glow = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    glow.paste(piece, (px, py), piece)
    glow = glow.filter(ImageFilter.GaussianBlur(7))
    card.alpha_composite(Image.merge("RGBA", (
        *[c.point(lambda v: int(v * 0.35)) for c in glow.split()[:3]],
        glow.split()[3].point(lambda v: int(v * 0.55)))))
    card.alpha_composite(piece, (px, py))

    # Label. Drawn glyph by glyph: the reference labels carry a couple of
    # pixels of tracking, and a plain space between letters is far too wide.
    font = load_font(FONT_SIZE)
    widths = [draw.textlength(ch, font=font) for ch in LABEL]
    total = sum(widths) + TRACKING * (len(LABEL) - 1)
    x = (SIZE - total) / 2
    for ch, cw in zip(LABEL, widths):
        draw.text((x, LABEL_BASE + 1), ch, font=font, fill=(0, 0, 0, 200),
                  anchor="ls")
        draw.text((x, LABEL_BASE), ch, font=font, fill=TEXT + (255,),
                  anchor="ls")
        x += cw + TRACKING

    card.save(OUT)
    print(f"wrote {OUT}  {card.size[0]}x{card.size[1]}")


if __name__ == "__main__":
    main()
