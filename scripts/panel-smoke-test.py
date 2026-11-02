#!/usr/bin/env python3
"""Headless smoke test for the Frame Inbox control panel.

    xvfb-run -a /usr/bin/python3 panel-smoke-test.py

Drives the real GTK handlers (start, send, clear, stop, restart, quit), checks the
inline JS parses, and verifies the live inbox was never touched. Uses port 8799 and
a temp store via FRAME_INBOX_PATH / FRAME_INBOX_PIDFILE.
"""
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request

PORT = os.environ.setdefault("SENDLINK_PORT", "8799")
TMP = tempfile.mkdtemp(prefix="frame-inbox-test-")
os.environ["FRAME_INBOX_PATH"] = os.path.join(TMP, "inbox.jsonl")
os.environ["FRAME_INBOX_PIDFILE"] = os.path.join(TMP, "server.pid")

APP = (os.environ.get("FRAME_INBOX_HOME")
       or os.path.join(os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share"),
                       "frame-inbox"))
LIVE = os.path.join(APP, "inbox.jsonl")
sys.path.insert(0, APP)

if not (os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")):
    sys.exit("no display — run with: xvfb-run -a python3 " + __file__)

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gdk, Gtk

import control

FAILED = []


def check(cond, label):
    print(("  OK   " if cond else "  FAIL ") + label)
    if not cond:
        FAILED.append(label)
    return cond


def pump(seconds):
    end = time.time() + seconds
    while time.time() < end:
        while Gtk.events_pending():
            Gtk.main_iteration_do(False)
        time.sleep(0.02)


def wait(fn, timeout, label):
    end = time.time() + timeout
    while time.time() < end:
        pump(0.1)
        if fn():
            check(True, label)
            return True
    check(False, label)
    return False


def live_digest():
    try:
        with open(LIVE, "rb") as fh:
            return hashlib.sha1(fh.read()).hexdigest()
    except FileNotFoundError:
        return "missing"


print("0. isolation and syntax")
live_before = live_digest()
check(os.path.realpath(control.INBOX).startswith(TMP), "panel store is the temp file")
for f in ("server.py", "control.py"):
    r = subprocess.run(["/usr/bin/python3", "-m", "py_compile", os.path.join(APP, f)],
                       capture_output=True)
    check(r.returncode == 0, f"{f} compiles")

provider = Gtk.CssProvider()
provider.load_from_data(control.CSS)
Gtk.StyleContext.add_provider_for_screen(
    Gdk.Screen.get_default(), provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

win = control.Panel()
win.show_all()

print("1. start from the panel")
win.on_toggle()
wait(lambda: win.health(0.3), 30, "health endpoint answers")
check(os.path.exists(control.PIDFILE), "pidfile written")
check(win.pill.get_text() in ("RUNNING", "STARTING…"), "pill reflects a live server")
if win.proc:
    with open(f"/proc/{win.proc.pid}/environ", "rb") as fh:
        check(b"FRAME_INBOX_PARENT" in fh.read(), "child armed with the parent watchdog")

print("2. page renders and its inline JS parses")
try:
    html = urllib.request.urlopen(f"http://127.0.0.1:{PORT}/", timeout=5).read().decode()
    check('<li class="row"' not in html or "button class=\"del\"" in html, "page served")
    script = re.search(r"<script>(.*)</script>", html, re.S).group(1)
    js = os.path.join(TMP, "page.js")
    with open(js, "w", encoding="utf-8") as fh:
        fh.write(script)
    r = subprocess.run(["node", "--check", js], capture_output=True)
    check(r.returncode == 0, "inline script parses (node --check)")
except Exception as exc:  # noqa: BLE001
    check(False, f"page fetch/parse: {exc}")

print("3. send a link through the panel")
win.url.set_text("https://example.com/smoke-test")
win.note.set_text("from the smoke test")
win.send()
wait(lambda: "smoke-test" in open(control.INBOX).read(), 5, "row landed in the store")
check(win.count() == 1, "counter agrees with the store")

print("3b. non-http links become copy rows")
win.url.set_text("magnet:?xt=urn:btih:deadbeef&dn=thing")
win.send()
wait(lambda: "magnet:" in open(control.INBOX).read(), 5, "magnet accepted by the panel")
try:
    page = urllib.request.urlopen(f"http://127.0.0.1:{PORT}/", timeout=5).read().decode()
    check('<button class="item copy"' in page, "magnet renders as a copy button")
    check(page.count('<a class="item"') == 1, "http row is still a plain link")
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *a, **k):
            return None

    try:
        urllib.request.build_opener(NoRedirect).open(
            f"http://127.0.0.1:{PORT}/latest", timeout=5)
        check(False, "/latest did not redirect")
    except urllib.error.HTTPError as err:
        loc = err.headers.get("Location", "")
        check(err.code == 302 and loc.endswith("smoke-test"),
              "/latest skips copy rows")
except Exception as exc:  # noqa: BLE001
    check(False, f"copy-row page check: {exc}")

print("3c. request hardening")
import http.client


def raw(method, path, body=b"", headers=None):
    conn = http.client.HTTPConnection("127.0.0.1", int(PORT), timeout=5)
    conn.request(method, path, body=body, headers=headers or {})
    resp = conn.getresponse()
    data = resp.read()
    hdrs = {k.lower(): v for k, v in resp.getheaders()}
    conn.close()
    return resp.status, data, hdrs


st, _, _ = raw("POST", "/add", b"https://evil.example/x", {"Origin": "https://evil.example"})
check(st == 403, "cross-origin POST rejected (CSRF)")
st, _, _ = raw("POST", "/clear", b"", {"Sec-Fetch-Site": "cross-site"})
check(st == 403, "Sec-Fetch-Site cross-site rejected")
st, _, _ = raw("POST", "/add", b"https://evil.example/x", {"Host": "rebind.example:8765"})
check(st == 403, "foreign Host rejected (DNS rebinding)")
st, _, hdrs = raw("GET", "/")
check(hdrs.get("x-frame-options") == "DENY", "clickjacking blocked")
check("default-src 'none'" in hdrs.get("content-security-policy", ""), "CSP present")
check(hdrs.get("x-content-type-options") == "nosniff", "nosniff present")
st, _, _ = raw("POST", "/add", b"https://ok.example/x")
check(st == 200, "no-Origin writes still work (CLI, panel)")
mode = oct(os.stat(control.INBOX).st_mode & 0o777)
check(mode == "0o600", f"store is private (mode {mode})")

print("4. clear needs arming")
win.on_clear()
check(win.clear_btn.get_label().startswith("Confirm"), "first click only arms")
win.on_clear()
wait(lambda: win.count() == 0, 5, "second click wipes")
check(win.clear_btn.get_label() == "Clear all links", "button disarmed afterwards")

print("5. graceful stop")
win.on_toggle()
wait(lambda: not win.health(0.3) and not win.alive() and win.pill.get_text() == "STOPPED",
     15, "server stopped, panel settled")
check(not os.path.exists(control.PIDFILE), "pidfile removed")

print("6. send while stopped queues to disk")
win.url.set_text("https://example.com/queued")
win.send()
check("queued" in open(control.INBOX).read(), "queued without a server")

print("7. restart picks it up, quit stops it")
win.on_toggle()
wait(lambda: win.health(0.3), 30, "restarted")
check(win.count() == 1, "queued row is on the page")
win.on_quit()
pump(2.0)
wait(lambda: not win.health(0.3), 10, "quit stopped the server")

print("8. live inbox untouched")
check(live_digest() == live_before, "real inbox byte-identical")

shutil.rmtree(TMP, ignore_errors=True)
print("RESULT:", "PASS" if not FAILED else f"FAIL ({len(FAILED)})")
sys.exit(0 if not FAILED else 1)
