#!/usr/bin/env python3
"""Build the sideload bundle: dist/frame-inbox-linux-arm64.zip

Stdlib zipfile so the build has no dependencies. Prints the sha256 that goes
into framedrop.json.
"""
import hashlib
import os
import zipfile

SRC = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(SRC, "dist")
NAME = "frame-inbox-linux-arm64"
ZIP = os.path.join(OUT, f"{NAME}.zip")

FILES = [
    ("install.sh", 0o755),
    ("uninstall.sh", 0o755),
    ("server.py", 0o644),
    ("control.py", 0o644),
    ("icon.svg", 0o644),
    ("VERSION", 0o644),
    ("update.sh", 0o755),
    ("bin/frame-inbox", 0o755),
    ("bin/sendlink", 0o755),
    ("bin/frame-inbox-uninstall", 0o755),
    ("desktop/frame-inbox.desktop.in", 0o644),
    ("static/icon-192.png", 0o644),
    ("static/icon-512.png", 0o644),
    ("packaging/frame-inbox", 0o755),
    ("packaging/README.txt", 0o644),
]

os.makedirs(OUT, exist_ok=True)
with zipfile.ZipFile(ZIP, "w", zipfile.ZIP_DEFLATED) as zf:
    for path, mode in FILES:
        full = os.path.join(SRC, path)
        arc = os.path.basename(path) if path.startswith("packaging/") else path
        info = zipfile.ZipInfo(f"{NAME}/{arc}", date_time=(2026, 1, 1, 0, 0, 0))
        info.compress_type = zipfile.ZIP_DEFLATED
        info.external_attr = (mode & 0xFFFF) << 16
        with open(full, "rb") as fh:
            zf.writestr(info, fh.read())

digest = hashlib.sha256(open(ZIP, "rb").read()).hexdigest()
size = os.path.getsize(ZIP)
print(f"built {ZIP}  ({size} bytes)")
print(f"sha256 {digest}")
