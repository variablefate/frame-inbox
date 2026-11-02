#!/usr/bin/env bash
# Frame Inbox installer - all user-local, no root, nothing system-wide.
set -euo pipefail

SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BASE="${FRAME_INBOX_HOME:-${XDG_DATA_HOME:-$HOME/.local/share}/frame-inbox}"
BIN="${BIN_DIR:-$HOME/.local/bin}"
DATA="${XDG_DATA_HOME:-$HOME/.local/share}"
APPS="$DATA/applications"
ICONS="$DATA/icons/hicolor"

say() { printf '  %s\n' "$*"; }

command -v python3 >/dev/null || { echo "python3 is required" >&2; exit 1; }

# find an interpreter that actually has GTK bindings - PATH's python3 may be a venv
PY=""
for cand in /usr/bin/python3 "$(command -v python3)"; do
  [ -x "$cand" ] || continue
  if "$cand" -c 'import gi; gi.require_version("Gtk", "3.0")' 2>/dev/null; then PY="$cand"; break; fi
done
[ -n "$PY" ] || { echo "GTK3 Python bindings are required (python3-gi)" >&2; exit 1; }

echo "Installing Frame Inbox"
mkdir -p "$BASE" "$BIN" "$APPS"
install -m 755 "$SRC/server.py"  "$BASE/server.py"
install -m 755 "$SRC/control.py" "$BASE/control.py"
install -m 644 "$SRC/icon.svg"   "$BASE/icon.svg"
install -m 644 "$SRC/VERSION"    "$BASE/VERSION"
install -m 755 "$SRC/update.sh"  "$BASE/update.sh"
install -m 755 "$SRC/bin/frame-inbox" "$BIN/frame-inbox"
install -m 755 "$SRC/bin/sendlink"    "$BIN/sendlink"
# bake in the interpreter that actually has GTK (escape sed replacement metacharacters)
PY_ESC=$(printf '%s' "$PY" | sed 's/[&#\\]/\\&/g')
sed -i "s#/usr/bin/python3#$PY_ESC#" "$BIN/frame-inbox"
say "app        $BASE"
say "launchers  $BIN/frame-inbox, $BIN/sendlink"

if command -v rsvg-convert >/dev/null 2>&1; then
  for s in 48 64 128 256; do
    install -d "$ICONS/${s}x${s}/apps"
    rsvg-convert -w "$s" -h "$s" "$SRC/icon.svg" -o "$ICONS/${s}x${s}/apps/frame-inbox.png"
  done
  install -Dm644 "$SRC/icon.svg" "$ICONS/scalable/apps/frame-inbox.svg"
  command -v gtk-update-icon-cache >/dev/null 2>&1 && gtk-update-icon-cache -f -t "$ICONS" 2>/dev/null || true
  say "icon       $ICONS"
else
  say "icon       skipped (rsvg-convert not found)"
fi

sed "s|@EXEC@|\"$BIN/frame-inbox\"|g" "$SRC/desktop/frame-inbox.desktop.in" > "$APPS/frame-inbox.desktop"
chmod +x "$APPS/frame-inbox.desktop"
say "menu entry $APPS/frame-inbox.desktop"

if [ "${1:-}" = "--desktop-icon" ] && [ -d "$HOME/Desktop" ]; then
  ln -sf "$APPS/frame-inbox.desktop" "$HOME/Desktop/frame-inbox.desktop"
  say "desktop    ~/Desktop/frame-inbox.desktop"
fi

echo
IP=$(ip -4 route get 1.1.1.1 2>/dev/null | awk '{print $7; exit}')
[ -n "$IP" ] || IP=$(hostname -I 2>/dev/null | awk '{print $1}')
[ -n "$IP" ] || IP="<your-lan-ip>"
echo "Done. Launch 'Frame Inbox', then open http://$IP:8765 on your phone."
