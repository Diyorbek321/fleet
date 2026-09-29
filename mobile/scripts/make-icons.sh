#!/usr/bin/env bash
# Regenerate every app icon from the two SVGs in assets/brand/.
#
#   scripts/make-icons.sh
#
# The android/ folder is kept by hand (no `expo prebuild`, see BUILD.md), so
# Expo's own icon generation never runs — the PNGs below are what the build
# uses. Needs inkscape and python3 with Pillow. Outputs are committed; run this
# again only when the SVGs change.
set -euo pipefail

cd "$(dirname "$0")/.."
BRAND=assets/brand
RES=android/app/src/main/res
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT

render() { # svg size out
  inkscape "$1" -w "$2" -h "$2" -o "$3" >/dev/null 2>&1
}

# Glyph-only SVGs: navy for the adaptive foreground, white for notifications.
# The adaptive foreground is a 108-unit canvas of which launchers show roughly
# the middle 72; a 36-unit glyph there matches the legacy icon's proportions.
glyph_svg() { # color scale out
  local off
  off=$(python3 -c "print(54 - 12 * $2)")
  cat >"$3" <<SVG
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 108 108">
  <g transform="translate($off $off) scale($2)">$(sed -n '/<path\|<circle/p' "$BRAND/glyph.svg" | sed "s/^/    /")
  </g>
</svg>
SVG
  sed -i "s/<svg xmlns=\"http:\/\/www.w3.org\/2000\/svg\" viewBox=\"0 0 108 108\">/<svg xmlns=\"http:\/\/www.w3.org\/2000\/svg\" viewBox=\"0 0 108 108\" fill=\"none\" stroke=\"$1\" stroke-width=\"2\" stroke-linecap=\"round\" stroke-linejoin=\"round\">/" "$3"
}
glyph_svg '#0f172a' 1.8 "$TMP/foreground.svg"
glyph_svg '#ffffff' 4.0 "$TMP/notification.svg"

# density name, launcher px (48dp), adaptive layer px (108dp), notification px (24dp)
DENSITIES="mdpi:48:108:24 hdpi:72:162:36 xhdpi:96:216:48 xxhdpi:144:324:72 xxxhdpi:192:432:96"

render "$BRAND/icon.svg" 1024 "$TMP/full.png"

for entry in $DENSITIES; do
  IFS=: read -r name launcher layer notif <<<"$entry"
  mkdir -p "$RES/mipmap-$name" "$RES/drawable-$name"
  python3 - "$TMP/full.png" "$launcher" "$RES/mipmap-$name" <<'PY'
import sys
from PIL import Image, ImageDraw
src, size, outdir = sys.argv[1], int(sys.argv[2]), sys.argv[3]
full = Image.open(src).convert("RGBA").resize((size, size), Image.LANCZOS)
def masked(draw_mask):
    mask = Image.new("L", (size * 4, size * 4), 0)
    draw_mask(ImageDraw.Draw(mask), size * 4)
    out = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    out.paste(full, (0, 0), mask.resize((size, size), Image.LANCZOS))
    return out
# Legacy (pre-Android 8) launchers: a rounded square and a circle.
masked(lambda d, s: d.rounded_rectangle((0, 0, s - 1, s - 1), radius=s * 0.22, fill=255)).save(f"{outdir}/ic_launcher.png")
masked(lambda d, s: d.ellipse((0, 0, s - 1, s - 1), fill=255)).save(f"{outdir}/ic_launcher_round.png")
PY
  render "$TMP/foreground.svg" "$layer" "$RES/mipmap-$name/ic_launcher_foreground.png"
  render "$TMP/notification.svg" "$notif" "$RES/drawable-$name/notification_icon.png"
  rm -f "$RES/mipmap-$name/ic_launcher.webp" "$RES/mipmap-$name/ic_launcher_round.webp"
done

# Expo-side copies, so app.json describes the same icon the native build ships.
cp "$TMP/full.png" assets/icon.png
render "$TMP/foreground.svg" 1024 assets/adaptive-icon.png
render "$TMP/notification.svg" 96 assets/notification-icon.png
# Play Console asks for a 512x512 PNG, uploaded by hand.
render "$BRAND/icon.svg" 512 "$BRAND/play-store-icon-512.png"

echo "icons written"
