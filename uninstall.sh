#!/usr/bin/env bash
# Remove Frame Inbox: process, code, launchers, menu/desktop entries, icons,
# the ntfy topic, and (unless --keep-data) your saved links.
#
#   ./uninstall.sh                 # show what will go, then ask
#   ./uninstall.sh --dry-run       # show only
#   ./uninstall.sh --yes           # no prompt
#   ./uninstall.sh --yes --keep-data
#
# A sideloaded copy under ~/devkit-game is removed too, along with its Steam
# library entry. That last part needs Steam running; if it isn't, the script says
# so and leaves the entry for you to remove from the library.
set -euo pipefail

BASE="${FRAME_INBOX_HOME:-${XDG_DATA_HOME:-$HOME/.local/share}/frame-inbox}"
BIN="${BIN_DIR:-$HOME/.local/bin}"
DATA="${XDG_DATA_HOME:-$HOME/.local/share}"
APPS="$DATA/applications"
ICONS="$DATA/icons/hicolor"
DEVDIR="$HOME/devkit-game"
UTILS="$HOME/devkit-utils"

DRY=0
ASSUME_YES=0
KEEP_DATA=0

for arg in "$@"; do
  case "$arg" in
    --dry-run) DRY=1 ;;
    --yes|-y) ASSUME_YES=1 ;;
    --keep-data) KEEP_DATA=1 ;;
    -h|--help) sed -n '2,11p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "unknown option: $arg" >&2; exit 2 ;;
  esac
done

# ---- find the installs ------------------------------------------------------
sideloads=()
for d in "$DEVDIR"/*/; do
  [ -f "${d}control.py" ] && sideloads+=("${d%/}")
done

targets=()
[ -d "$BASE" ] && targets+=("$BASE")
[ -f "$BIN/frame-inbox" ] && targets+=("$BIN/frame-inbox")
[ -f "$BIN/sendlink" ] && targets+=("$BIN/sendlink")
[ -f "$APPS/frame-inbox.desktop" ] && targets+=("$APPS/frame-inbox.desktop")
[ -L "$HOME/Desktop/frame-inbox.desktop" ] && targets+=("$HOME/Desktop/frame-inbox.desktop")
for size in 48x48 64x64 128x128 256x256 scalable; do
  for ext in png svg; do
    p="$ICONS/$size/apps/frame-inbox.$ext"
    [ -f "$p" ] && targets+=("$p")
  done
done
[ -d "$HOME/.config/sendlink" ] && targets+=("$HOME/.config/sendlink")
for d in "${sideloads[@]:-}"; do
  [ -n "$d" ] && targets+=("$d")
done

if [ ${#targets[@]} -eq 0 ]; then
  echo "Nothing to remove - Frame Inbox does not look installed here."
  exit 0
fi

echo "Frame Inbox will be removed:"
for t in "${targets[@]}"; do
  if [ "$KEEP_DATA" = "1" ] && [ "$t" = "$BASE" ]; then
    echo "  $t  (code only - links kept)"
  else
    echo "  $t"
  fi
done
for d in "${sideloads[@]:-}"; do
  [ -n "$d" ] && echo "  Steam library entry: $(basename "$d")"
done

if [ "$DRY" = "1" ]; then
  echo
  echo "dry run - nothing changed"
  exit 0
fi

if [ "$ASSUME_YES" != "1" ]; then
  printf '\nRemove all of the above? [y/N] '
  read -r reply
  case "$reply" in y|Y|yes|YES) ;; *) echo "cancelled"; exit 1 ;; esac
fi

# ---- stop the running server first -----------------------------------------
if curl -fsS -m 2 -o /dev/null "http://127.0.0.1:${SENDLINK_PORT:-8765}/health" 2>/dev/null; then
  curl -fsS -m 2 -X POST -o /dev/null "http://127.0.0.1:${SENDLINK_PORT:-8765}/shutdown" 2>/dev/null || true
  echo "stopped the running server"
fi
if [ -f "$BASE/server.pid" ]; then
  pid="$(cat "$BASE/server.pid" 2>/dev/null || true)"
  if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
    kill "$pid" 2>/dev/null || true
  fi
fi

# ---- Steam entries for sideloaded copies -----------------------------------
for d in "${sideloads[@]:-}"; do
  [ -n "$d" ] || continue
  gid="$(basename "$d")"
  if [ -x "$UTILS/steamos-delete" ]; then
    python3 "$UTILS/steamos-delete" --delete-title "$gid" >/dev/null 2>&1 \
      && echo "removed Steam entry $gid" \
      || echo "could not remove the Steam entry $gid - remove it from the library by hand"
  else
    echo "no devkit-utils here - remove '$gid' from the Steam library by hand"
  fi
  rm -rf "$DEVDIR/$gid"
  rm -f "$DEVDIR/$gid"-*.json
done

# ---- files ------------------------------------------------------------------
if [ "$KEEP_DATA" = "1" ] && [ -d "$BASE" ]; then
  find "$BASE" -mindepth 1 -maxdepth 1 \
       ! -name inbox.jsonl ! -name 'inbox.jsonl.tmp' -exec rm -rf {} +
  echo "kept $BASE/inbox.jsonl"
else
  rm -rf "$BASE"
fi
rm -f "$BIN/frame-inbox" "$BIN/sendlink" \
      "$APPS/frame-inbox.desktop" "$HOME/Desktop/frame-inbox.desktop" \
      "$HOME/.config/sendlink/topic"
rmdir "$HOME/.config/sendlink" 2>/dev/null || true
for size in 48x48 64x64 128x128 256x256 scalable; do
  rm -f "$ICONS/$size/apps/frame-inbox.png" "$ICONS/$size/apps/frame-inbox.svg"
done
command -v gtk-update-icon-cache >/dev/null 2>&1 \
  && gtk-update-icon-cache -f -t "$ICONS" >/dev/null 2>&1 || true

echo
echo "Frame Inbox removed."
if [ "$KEEP_DATA" = "1" ]; then
  echo "Your links are still in $BASE/inbox.jsonl - delete that file when you no longer want them."
fi
