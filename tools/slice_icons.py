# ═══════════════════════════════════════════════════════════
#  tools/slice_icons.py — UI icon sprite-sheet slicer
#
#  Cuts art_src/Chess_packs.png into assets/ui/*.png.
#
#  The sheet holds four bands:
#    0  six nav cards      RANKINGS STATISTICS OPENINGS TOURNAMENTS
#                          HISTORY ENGINE
#    1  thirteen glyphs    home user search filter star download export
#                          settings bell flag calendar trophy chart
#    2  chess pieces and status badges  (not used here)
#    3  thirteen glyphs    play pause stop forward rewind refresh database
#                          book scales announce info help power
#
#  An earlier slice of this sheet was off by several positions, so
#  ic_play held a refresh arrow, ic_stop held a book, ic_pause held a
#  database and so on. Re-running this puts every glyph under its own
#  name and upscales it — the originals were 16-21 px and looked soft.
#
#  Run:  venv/Scripts/python.exe -X utf8 tools/slice_icons.py [--probe]
# ═══════════════════════════════════════════════════════════

import os
import shutil
import sys

from PIL import Image

SHEET = os.path.join("art_src", "Chess_packs.png")
OUT_DIR = os.path.join("assets", "ui")
BACKUP_DIR = os.path.join("build", "icon_backup")
PROBE_DIR = os.path.join("build", "icon_probe")

ALPHA_T = 40      # alpha above this counts as foreground
CANVAS = 64       # output canvas; the sheet glyphs are ~20 px
MIN_ROW = 8
MIN_COL = 6

# Row 1, left to right
GLYPH_ROW_1 = ["ic_home", "ic_user", "ic_search", "ic_filter", "ic_star",
               "ic_download", "ic_export", "ic_settings", "ic_bell",
               "ic_flag", "ic_calendar", "ic_trophy", "ic_chart"]

# Row 3, left to right, after merging the two pause bars
GLYPH_ROW_3 = ["ic_play", "ic_pause", "ic_stop", "ic_forward", "ic_rewind",
               "ic_refresh", "ic_database", "ic_book", "ic_scales",
               "ic_announce", "ic_info", "ic_help", "ic_power"]

# The pause glyph is two separate bars; column detection splits it.
PAUSE_MERGE = (1, 2)

# Nav cards. nav_tournaments is a bespoke 1024px image in the repo, so it
# is deliberately absent here — re-slicing would downgrade it.
NAV_ROW_0 = ["nav_rankings", "nav_statistics", "nav_openings", None,
             "nav_history", "nav_engine"]

# Kept so existing call sites do not break: old name -> new glyph
ALIASES = {"ic_play_rev": "ic_rewind"}


def bands(flags, minimum):
    """Contiguous True runs → [(start, end), …], short runs dropped."""
    out, start = [], None
    for i, flag in enumerate(flags):
        if flag and start is None:
            start = i
        elif not flag and start is not None:
            if i - start >= minimum:
                out.append((start, i))
            start = None
    if start is not None and len(flags) - start >= minimum:
        out.append((start, len(flags)))
    return out


def row_boxes(im, alpha, y0, y1):
    """Tight bounding boxes for every sprite in one horizontal band."""
    w = im.width
    cols = bands([any(alpha[x, y] > ALPHA_T for y in range(y0, y1))
                  for x in range(w)], MIN_COL)
    boxes = []
    for x0, x1 in cols:
        ys = [y for y in range(y0, y1)
              if any(alpha[x, y] > ALPHA_T for x in range(x0, x1))]
        boxes.append((x0, min(ys), x1, max(ys) + 1))
    return boxes


def merge(boxes, i, j):
    a, b = boxes[i], boxes[j]
    merged = (min(a[0], b[0]), min(a[1], b[1]),
              max(a[2], b[2]), max(a[3], b[3]))
    return boxes[:i] + [merged] + boxes[j + 1:]


def save(im, box, name, canvas=CANVAS):
    """Crop, scale to fit *canvas* keeping aspect, centre on transparency."""
    crop = im.crop(box)
    scale = min(canvas / crop.width, canvas / crop.height)
    size = (max(1, round(crop.width * scale)),
            max(1, round(crop.height * scale)))
    crop = crop.resize(size, Image.LANCZOS)
    out = Image.new("RGBA", (canvas, canvas), (0, 0, 0, 0))
    out.paste(crop, ((canvas - size[0]) // 2, (canvas - size[1]) // 2), crop)
    path = os.path.join(OUT_DIR, f"{name}.png")
    out.save(path)
    return path


def main():
    probe = "--probe" in sys.argv
    im = Image.open(SHEET).convert("RGBA")
    alpha = im.getchannel("A").load()
    w, h = im.size
    print(f"sheet: {w}x{h}")

    rows = bands([any(alpha[x, y] > ALPHA_T for x in range(w))
                  for y in range(h)], MIN_ROW)
    if len(rows) != 4:
        raise SystemExit(f"expected 4 bands in the sheet, found {len(rows)}")

    nav = row_boxes(im, alpha, *rows[0])
    glyphs1 = row_boxes(im, alpha, *rows[1])
    glyphs3 = merge(row_boxes(im, alpha, *rows[3]), *PAUSE_MERGE)

    if probe:
        os.makedirs(PROBE_DIR, exist_ok=True)
        for tag, boxes in (("nav", nav), ("g1", glyphs1), ("g3", glyphs3)):
            for i, box in enumerate(boxes):
                im.crop(box).save(os.path.join(PROBE_DIR, f"{tag}_{i}.png"))
        print(f"probe crops -> {PROBE_DIR} "
              f"(nav={len(nav)} g1={len(glyphs1)} g3={len(glyphs3)})")
        return

    for label, boxes, names in (("row 1", glyphs1, GLYPH_ROW_1),
                                ("row 3", glyphs3, GLYPH_ROW_3),
                                ("nav", nav, NAV_ROW_0)):
        if len(boxes) != len(names):
            raise SystemExit(
                f"{label}: sheet has {len(boxes)} sprites but "
                f"{len(names)} names are configured — the sheet changed")

    # Keep the originals; a bad slice should never be unrecoverable.
    os.makedirs(BACKUP_DIR, exist_ok=True)
    for fname in os.listdir(OUT_DIR):
        if fname.endswith(".png"):
            shutil.copy2(os.path.join(OUT_DIR, fname),
                         os.path.join(BACKUP_DIR, fname))
    print(f"backed up {OUT_DIR} -> {BACKUP_DIR}")

    written = 0
    for boxes, names in ((glyphs1, GLYPH_ROW_1), (glyphs3, GLYPH_ROW_3)):
        for box, name in zip(boxes, names):
            save(im, box, name)
            written += 1
    for box, name in zip(nav, NAV_ROW_0):
        if name:
            save(im, box, name, canvas=192)
            written += 1
    for alias, source in ALIASES.items():
        shutil.copy2(os.path.join(OUT_DIR, f"{source}.png"),
                     os.path.join(OUT_DIR, f"{alias}.png"))
        written += 1

    print(f"wrote {written} icons -> {OUT_DIR}")


if __name__ == "__main__":
    main()
