# ═══════════════════════════════════════════════════════════
#  tools/slice_pieces.py — one-off sprite-sheet slicer
#
#  Cuts assets/chess_pcs_collection.png (3 designs stacked in rows;
#  each row = 6 white pieces then 6 black pieces, order P R N B Q K,
#  true alpha background) into transparent 88×88 sprites compatible
#  with assets/pieces/, written to assets/pieces_<n>/.
#
#  Run:  venv/Scripts/python.exe -X utf8 tools/slice_pieces.py [--probe]
#        --probe only writes numbered crops for identifying the
#        piece order.
# ═══════════════════════════════════════════════════════════

import os
import sys

from PIL import Image

SHEET = os.path.join("assets", "chess_pcs_collection.png")
PROBE_DIR = os.path.join("build", "piece_probe")

# Left→right piece order inside each 6-piece group (verified w/ --probe)
ORDER = ["P", "R", "N", "B", "Q", "K"]

ALPHA_T = 64         # pixels with alpha above this count as foreground
SPRITE = 88          # output canvas (matches assets/pieces/*.png)
MAX_H = 80           # tallest piece height inside the canvas
MIN_BAND = 40        # minimum sprite band height (px)
MIN_COL = 12         # minimum sprite width (px)


def find_bands(fg_rows):
    """Contiguous True runs → [(start, end), …]."""
    bands, start = [], None
    for i, fg in enumerate(fg_rows):
        if fg and start is None:
            start = i
        elif not fg and start is not None:
            bands.append((start, i))
            start = None
    if start is not None:
        bands.append((start, len(fg_rows)))
    return bands


def main():
    probe = "--probe" in sys.argv
    im = Image.open(SHEET).convert("RGBA")
    w, h = im.size
    alpha = im.getchannel("A").load()
    print(f"sheet: {w}x{h}")

    def col_fg(x, y0, y1):
        return any(alpha[x, y] > ALPHA_T for y in range(y0, y1))

    def row_fg(y):
        return any(alpha[x, y] > ALPHA_T for x in range(w))

    rows = find_bands([row_fg(y) for y in range(h)])
    rows = [b for b in rows if b[1] - b[0] >= MIN_BAND]
    print("row bands:", rows)
    assert len(rows) == 3, f"expected 3 design rows, got {len(rows)}"

    designs = []
    for y0, y1 in rows:
        cols = find_bands([col_fg(x, y0, y1) for x in range(w)])
        cols = [c for c in cols if c[1] - c[0] >= MIN_COL]
        boxes = []
        for x0, x1 in cols:
            ys = [y for y in range(y0, y1)
                  if any(alpha[x, y] > ALPHA_T for x in range(x0, x1))]
            boxes.append((x0, min(ys), x1, max(ys) + 1))
        print(f"row y={y0}-{y1}: {len(boxes)} sprites",
              [(x1 - x0, yb1 - yb0) for x0, yb0, x1, yb1 in boxes])
        designs.append(boxes)

    if probe:
        os.makedirs(PROBE_DIR, exist_ok=True)
        for d, boxes in enumerate(designs, 1):
            for i, box in enumerate(boxes):
                im.crop(box).save(
                    os.path.join(PROBE_DIR, f"set{d}_{i}.png"))
        print(f"probe crops -> {PROBE_DIR}")
        return

    for d, boxes in enumerate(designs, 1):
        assert len(boxes) == 12, \
            f"design {d}: expected 12 sprites, got {len(boxes)}"
        out_dir = os.path.join("assets", f"pieces_{d}")
        os.makedirs(out_dir, exist_ok=True)

        # Per-design scale so relative piece heights survive
        tallest = max(y1 - y0 for _, y0, _, y1 in boxes)
        scale = MAX_H / tallest

        for i, box in enumerate(boxes):
            color = "w" if i < 6 else "b"
            code = ORDER[i % 6]
            crop = im.crop(box)
            nw = max(1, round(crop.width * scale))
            nh = max(1, round(crop.height * scale))
            crop = crop.resize((nw, nh), Image.LANCZOS)
            canvas = Image.new("RGBA", (SPRITE, SPRITE), (0, 0, 0, 0))
            canvas.paste(crop, ((SPRITE - nw) // 2, SPRITE - 4 - nh), crop)
            out = os.path.join(out_dir, f"{color}{code}.png")
            canvas.save(out)
        print(f"design {d} -> {out_dir} (12 sprites)")


if __name__ == "__main__":
    main()
