#!/usr/bin/env bash
# Package the game for the browser with pygbag.
#
# pygbag bundles every file it finds under the app directory, so the build
# runs out of a staging copy holding only what the browser needs. That keeps
# the training-only files out of the download -- torch, gymnasium and the
# .zip checkpoints have no WebAssembly build and would only be dead weight
# next to ai/policy.json, which is what actually drives AI mode.
#
#   ./tools/build_web.sh          -> build/web/, ready to serve
#   ./tools/build_web.sh --serve  -> build it, then serve on :8000
set -euo pipefail

cd "$(dirname "$0")/.."
ROOT=$PWD
APP=super-mario-bros-ai
STAGE=$ROOT/build/$APP
OUT=$ROOT/build/web

# Everything the browser build imports, loads or reads.
FILES=(
  main.py
  mario.py
  mario_ai.py
  goomba.py
  level_loader.py
  sprite_manager.py
  smb_physics.py
  tileset.json
  pygbag.ini
  favicon.png
)
DIRS=(ai levels sprites sfx)

rm -rf "$STAGE" "$OUT"
mkdir -p "$STAGE"

for f in "${FILES[@]}"; do cp "$ROOT/$f" "$STAGE/$f"; done
for d in "${DIRS[@]}"; do cp -R "$ROOT/$d" "$STAGE/$d"; done

# Audio: ogg only. The wasm SDL_mixer has no mp3 decoder.
mkdir -p "$STAGE/music"
cp "$ROOT/music/overworld1_mario.ogg" "$STAGE/music/"
cp "$ROOT/music/deathsound.ogg" "$STAGE/music/"

find "$STAGE" \( -name '__pycache__' -o -name '.DS_Store' \) -exec rm -rf {} + 2>/dev/null || true

if [ ! -f "$STAGE/ai/policy.json" ]; then
  echo "error: ai/policy.json is missing -- run 'python3 tools/export_policy.py' first" >&2
  exit 1
fi

echo "staged $(find "$STAGE" -type f | wc -l | tr -d ' ') files, $(du -sh "$STAGE" | cut -f1)"

# 768x720 is the game's native 256x240 at 3x, which is what main.py opens.
ARGS=(--build --width 768 --height 720 --app_name "$APP"
      --title "Super Mario Bros — AI" --icon favicon.png)
[ "${1:-}" = "--serve" ] && ARGS=("${ARGS[@]:1}")   # drop --build, pygbag serves

python3 -m pygbag "${ARGS[@]}" "$STAGE"

if [ "${1:-}" != "--serve" ]; then
  mkdir -p "$(dirname "$OUT")"
  rm -rf "$OUT"
  mv "$STAGE/build/web" "$OUT"
  echo
  echo "built -> build/web  ($(du -sh "$OUT" | cut -f1))"
  ls -la "$OUT"
fi
