#!/usr/bin/env bash
# Update an installed Frame Inbox to the latest GitHub release.
#
#   curl -fsSL https://raw.githubusercontent.com/variablefate/frame-inbox/main/update.sh | bash
#   ... | bash -s -- --check        # report only, change nothing
#   ./update.sh --dir /path/to/app  # when the install lives somewhere unusual
#
# Replaces the app files only. Links, the log and the retention window are untouched.
set -euo pipefail
umask 077

REPO="variablefate/frame-inbox"
ZIP_NAME="frame-inbox-linux-arm64.zip"
BASE="${FRAME_INBOX_HOME:-${XDG_DATA_HOME:-$HOME/.local/share}/frame-inbox}"
DIR=""
CHECK=0

usage() { sed -n '3,10p' "$0" | sed 's/^# \{0,1\}//' >&2; exit 2; }

while [ $# -gt 0 ]; do
  case "$1" in
    --check) CHECK=1 ;;
    --dir) DIR="${2:?--dir needs a path}"; shift ;;
    -h|--help) usage ;;
    *) usage ;;
  esac
  shift
done

# ---- where is it installed? -------------------------------------------------
if [ -z "$DIR" ]; then
  if [ -f "$BASE/control.py" ]; then
    DIR="$BASE"
  else
    hits=()
    for d in "$HOME"/devkit-game/*/; do
      [ -f "${d}control.py" ] && hits+=("${d%/}")
    done
    if [ ${#hits[@]} -eq 1 ]; then
      DIR="${hits[0]}"
    elif [ ${#hits[@]} -gt 1 ]; then
      echo "several sideload folders found - pick one:" >&2
      printf '  %s\n' "${hits[@]}" >&2
      echo "then: update.sh --dir <path>" >&2
      exit 1
    else
      echo "Frame Inbox not found in $BASE or ~/devkit-game" >&2
      exit 1
    fi
  fi
fi

installed="$(tr -d '[:space:]' < "$DIR/VERSION" 2>/dev/null || true)"
[ -n "$installed" ] || installed="0.0.0"

json() { python3 -c "import json,sys; d=json.load(sys.stdin); print($1)"; }

echo "installed  v$installed  ($DIR)"
latest="$(curl -fsSL -m 20 "https://api.github.com/repos/$REPO/releases/latest" \
          | json 'd["tag_name"].lstrip("v")')" \
  || { echo "could not reach GitHub" >&2; exit 1; }
echo "latest     v$latest"

newer=$(python3 - "$installed" "$latest" <<'PY'
import sys
def key(v):
    parts = v.split("-")[0].split(".")
    return tuple(int(p) if p.isdigit() else 0 for p in (parts + ["0", "0"])[:3])
print(1 if key(sys.argv[2]) > key(sys.argv[1]) else 0)
PY
)

if [ "$newer" != "1" ]; then
  echo "already up to date"
  exit 0
fi
if [ "$CHECK" = "1" ]; then
  echo "update available: v$installed -> v$latest"
  exit 0
fi

# ---- fetch and verify -------------------------------------------------------
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT
asset="https://github.com/$REPO/releases/download/v$latest/$ZIP_NAME"
echo "downloading $asset"
curl -fsSL -m 300 -o "$tmp/app.zip" "$asset"

got="$(sha256sum "$tmp/app.zip" | cut -d' ' -f1)"
manifest="$(curl -fsSL -m 20 "https://raw.githubusercontent.com/$REPO/main/framedrop.json" || true)"
if printf '%s' "$manifest" | grep -q "/download/v$latest/$ZIP_NAME"; then
  want="$(printf '%s' "$manifest" | json 'd["files"][0]["sha256"]')"
  if [ "$got" != "$want" ]; then
    echo "checksum mismatch - refusing to install" >&2
    echo "  manifest $want" >&2
    echo "  download $got" >&2
    exit 1
  fi
  echo "checksum   verified"
else
  echo "checksum   no pin for v$latest (manifest points at another tag) - continuing on TLS only"
fi

python3 - "$tmp/app.zip" "$tmp/x" <<'PY'
import os, sys, zipfile
root = os.path.realpath(sys.argv[2])
with zipfile.ZipFile(sys.argv[1]) as zf:
    for i in zf.infolist():
        t = os.path.realpath(os.path.join(root, i.filename))
        if not (t == root or t.startswith(root + os.sep)):
            sys.exit(f"refusing path outside the target: {i.filename}")
        if i.is_dir():
            os.makedirs(t, exist_ok=True)
            continue
        os.makedirs(os.path.dirname(t), exist_ok=True)
        with zf.open(i) as src, open(t, "wb") as out:
            out.write(src.read())
        mode = (i.external_attr >> 16) & 0o777
        if mode:
            os.chmod(t, mode)
PY

src="$(find "$tmp/x" -maxdepth 2 -name VERSION -printf '%h\n' | head -1)"
[ -n "$src" ] || { echo "release archive looks wrong (no VERSION)" >&2; exit 1; }

# ---- swap the code, leave the data alone ------------------------------------
for f in server.py control.py icon.svg VERSION frame-inbox; do
  [ -f "$src/$f" ] || continue
  # the bundle carries its own launcher; an install.sh layout keeps its launcher
  # in ~/.local/bin and should not grow a second one here
  if [ "$f" = "frame-inbox" ] && [ ! -f "$DIR/frame-inbox" ]; then
    continue
  fi
  install -m "$(stat -c %a "$src/$f")" "$src/$f" "$DIR/.$f.new"
  mv -f "$DIR/.$f.new" "$DIR/$f"
  echo "  updated $f"
done

echo
echo "updated v$installed -> v$latest"
echo "Quit and reopen Frame Inbox to run the new version (a running copy keeps the old code)."
