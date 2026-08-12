# ═══════════════════════════════════════════════════════════
#  scale.py — Where this app's rating numbers sit, and why
#
#  Ratings here are computed from this database and nothing else. They
#  are relative by nature: a pool rated against itself fixes differences
#  between engines, never an absolute level, so the origin is a choice.
#  ARENA_ORIGIN is that choice and it is cosmetic — moving it shifts
#  every engine by the same amount and changes no ranking, no gap, and
#  no prediction. It is set so the numbers land in the range people
#  expect to see engines quoted in, and for no other reason.
#
#  ── Why there are no imported ratings here ─────────────────
#
#  Anchoring to CCRL Blitz was tried on 2026-08-12: eighteen engines in
#  this collection were pinned to their published ratings so the rest
#  would be measured against a known scale. It was wrong, and the data
#  says so plainly.
#
#  For its pinned 3649 to hold, Ethereal 14.00 would have to score 83.5%
#  against this field. It scores 44.1%. Stockfish 11, pinned at 3564,
#  needed 73.9% and scores 43.8%. The pinning put an engine with a
#  losing record at the top of the rankings.
#
#  A single offset was tried instead, which would have preserved every
#  measured difference. The shift each anchor needed ranged from +826 to
#  +2095 — a 1269-point disagreement about where one line sits.
#
#  The reason neither works is not scale but order. CCRL has Ethereal
#  14.00 481 points above Halogen 9; here Halogen scores 55.4% and
#  Ethereal 44.1%. No offset and no stretch can reverse a ranking.
#
#  That is a real difference in what is being measured, not an error.
#  CCRL runs 2min+1s on its own hardware; a Classic game here gives both
#  sides a fixed think time per move and Bullet is 1+0 on this machine.
#  At a short fixed think time a modern NNUE engine beats a pre-NNUE
#  search that would hold up given depth. Both measurements are honest
#  and they are measurements of different things.
#
#  So: no external numbers. If this scale is ever to be compared with a
#  published list, the way is to play the games at that list's control,
#  not to import its answers.
# ═══════════════════════════════════════════════════════════

# The origin, and what an engine's two virtual prior draws are played
# against. Chosen so a rated field lands roughly between 1800 and 3200.
ARENA_ORIGIN = 2700

SCALE_NOTE = ("Arena Elo — computed only from games in this database. "
              "Relative to this collection, so it is not comparable with "
              "CCRL or any published list.")
