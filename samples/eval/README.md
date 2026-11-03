# Local floor plan evaluation set

Run `python scripts/eval_plans.py --mode opencv` from the project root. The
script reads `expected.json` for rough room/area checks and for manually known
story splits. It creates per-plan mask, opening, and final-scene overlays under
`out/debug/`.

These three prepared images are regression fixtures, not a representative
benchmark of arbitrary uploads. Add 6–8 real plans with confirmed floor counts,
room counts, and approximate areas before treating the evaluation as a quality
score. Keep private or licensed plans out of Git unless permission allows it.

The two-story fixture has two plan drawings side by side; its vertical split at
50% is recorded explicitly. The application itself never guesses the floor
count or split position for an uploaded image.
