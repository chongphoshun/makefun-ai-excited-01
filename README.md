# make.fun ai-excited-01 — "LIFTOFF"

A rocket launches from a neon city at golden hour, under a huge low sun,
with a crowd watching from below and a bold `LIFTOFF` headline.

## Run

```sh
mkdir -p out && MAKEFUN_OUTPUT_DIR=out python3 main.py
# writes out/entry.png (1024x1024, ~350 KB)
```

## How it works

`main.py` is Python 3.13 standard library only (`zlib` + `struct` write the
PNG by hand — no PIL/numpy). It renders procedurally:

- sky: vertical indigo → magenta → orange gradient, radial sun glow, and a
  deterministic value-noise (fbm) nebula tint, with vignette;
- neon city: two seeded skyline layers, lit windows, neon strips, rooftop
  beacons, and a crowd of tiny silhouettes (raised arms, phone lights);
- rocket: vector nose/body/fins/window with rim light, smooth three-layer
  teardrop flame, billowing smoke, speed streaks, god rays, birds;
- headline: crisp hand-built 5x7 block font with an orange glow halo.

Everything is seeded (`random.Random` with fixed seeds); there are no
timestamps and no dict-order dependence, so two runs write identical bytes.

## Verified locally

- Two runs to different dirs: identical SHA-256
  `c8b774cf7959136a5fe5aaa0ddc15ea01fa8f17b7a9dcf4dff609eaaf2c4689f`
- Runtime ~5 s (limit 60 s), 349,817 bytes (limit 1 MiB), 1024×1024 PNG,
  decodes cleanly (PIL), still reads clearly at 300 px.

## Concepts considered

Three concepts were rendered and compared by eye; the rocket won (see
`~/workspace/makefun/ai-excited-01-concepts/`):

1. **LIFTOFF rocket (winner)** — most exciting at one look, clearest at
   small size, crisp headline.
2. Cosmic whale over a mountain lake — rejected: the whale read as a
   glowing sausage, too calm for criterion 1.
3. Golden koi leaping toward the moon — rejected: strong diagonal, but the
   disc-chain body showed visible segmentation rings and the head/fins
   never read cleanly.
