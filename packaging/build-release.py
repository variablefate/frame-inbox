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
    ("server.py", 0o644),
    ("control.py", 0o644),
    ("icon.svg", 0o644),
    ("packaging/frame-inbox", 0o755),
    ("packaging/README.txt", 0o644),
]

os.makedirs(OUT, exist_ok=True)
with zipfile.ZipFile(ZIP, "w", zipfile.ZIP_DEFLATED) as zf:
    for path, mode in FILES:
        full = os.path.join(SRC, path)
        info = zipfile.ZipInfo(f"{NAME}/{os.path.basename(path)}", date_time=(2026, 1, 1, 0, 0, 0))
        info.compress_type = zipfile.ZIP_DEFLATED
        info.external_attr = (mode & 0xFFFF) << 16
        with open(full, "rb") as fh:
            zf.writestr(info, fh.read())

digest = hashlib.sha256(open(ZIP, "rb").read()).hexdigest()
size = os.path.getsize(ZIP)
print(f"built {ZIP}  ({size} bytes)")
print(f"sha256 {digest}")
