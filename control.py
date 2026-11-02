#!/usr/bin/env python3
"""Frame Inbox — desktop control panel.

Starts and stops the LAN page the phone opens, sends links into it, and clears it.
Everything lives in ~/.local/share/frame-inbox/ (server.py, inbox.jsonl, server.log).
"""
import json
import os
import re
import socket
import subprocess
import sys
import time
import urllib.request

import gi
gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
gi.require_version("Pango", "1.0")
from gi.repository import Gdk, GLib, Gtk, Pango

BASE = (os.environ.get("FRAME_INBOX_HOME")
        or os.path.join(os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share"),
                        "frame-inbox"))
SERVER = os.path.join(BASE, "server.py")
INBOX = os.environ.get("FRAME_INBOX_PATH") or os.path.join(BASE, "inbox.jsonl")
LOG = os.path.join(BASE, "server.log")
PIDFILE = os.environ.get("FRAME_INBOX_PIDFILE") or os.path.join(BASE, "server.pid")
PY = sys.executable or "/usr/bin/python3"
PORT = int(os.environ.get("SENDLINK_PORT", "8765"))
KEEP_DAYS = int(os.environ.get("SENDLINK_KEEP_DAYS", "7"))

CSS = b"""
window, .panel { background-color: #111318; }
label { color: #e8eaf0; }
.hdr { font-size: 12px; font-weight: 700; letter-spacing: 0.12em; color: #8b93a7; }
.addr { font-family: monospace; font-size: 12px; color: #8b93a7; }
.pill { font-size: 11px; font-weight: 700; border-radius: 10px; padding: 4px 10px; }
.pill.on  { background-color: #14312a; color: #63d6a3; }
.pill.off { background-color: #232833; color: #7e8798; }
.pill.err { background-color: #3a1d22; color: #ff9aa8; }
button { background-image: none; background-color: #1a1e26; border: 1px solid #2a2f3a;
         border-radius: 10px; padding: 8px 14px; color: #d7dbe4; }
button:hover { background-color: #232935; }
button:disabled { color: #5f6779; }
button.big { font-size: 15px; font-weight: 600; padding: 13px; }
button.go { background-color: #1d3a5c; border-color: #2f5a8c; color: #d8e8ff; }
button.go:hover { background-color: #22456d; }
button.quiet { color: #9aa3b5; }
button.danger { color: #ff9aa8; }
button.danger.armed { background-color: #3a1d22; border-color: #5c2b33; font-weight: 600; }
entry { background-image: none; background-color: #1a1e26; border: 1px solid #2a2f3a;
        border-radius: 10px; padding: 9px 11px; color: #e8eaf0; caret-color: #6ea8fe; }
entry:focus { border-color: #3d5a80; }
.dim { font-size: 11px; color: #5f6779; }
.error { font-size: 12px; color: #ff9aa8; }
separator { background-color: #232935; min-height: 1px; }
"""


def lan_ip():
    """Best-guess LAN address without sending a packet."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("192.0.2.1", 9))
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()


class Panel(Gtk.Window):
    def __init__(self):
        super().__init__(title="Frame Inbox")
        self.set_wmclass("frame-inbox", "Frame Inbox")
        Gdk.set_program_class("frame-inbox")
        self.set_resizable(False)
        self.set_size_request(420, -1)
        self.set_border_width(0)
        self.connect("delete-event", self.on_delete)

        self.proc = None
        self.deadline = 0.0
        self.stop_deadline = 0.0
        self.gen = 0          # bumps on every start/stop so stale callbacks bail
        self.armed = False
        self.arm_timer = None
        self.msg_timer = None
        self.owns_loop = False   # True only when main() started Gtk.main()

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        box.set_border_width(16)
        self.add(box)

        # --- header -------------------------------------------------------
        head = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        title = Gtk.Label(label="FRAME INBOX", xalign=0.0)
        title.get_style_context().add_class("hdr")
        self.pill = Gtk.Label(label="STOPPED", xalign=0.5)
        self.pill.get_style_context().add_class("pill")
        self.pill.get_style_context().add_class("off")
        head.pack_start(title, False, False, 0)
        head.pack_end(self.pill, False, False, 0)
        box.pack_start(head, False, False, 0)

        self.addr = Gtk.Label(label=f"http://{lan_ip()}:{PORT}", xalign=0.0)
        self.addr.get_style_context().add_class("addr")
        self.addr.set_selectable(True)
        self.addr.set_ellipsize(Pango.EllipsizeMode.MIDDLE)
        box.pack_start(self.addr, False, False, 0)

        self.toggle = Gtk.Button(label="Start server")
        self.toggle.get_style_context().add_class("big")
        self.toggle.get_style_context().add_class("go")
        self.toggle.connect("clicked", self.on_toggle)
        box.pack_start(self.toggle, False, False, 2)

        box.pack_start(Gtk.Separator(), False, False, 4)

        # --- send ---------------------------------------------------------
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self.url = Gtk.Entry()
        self.url.set_placeholder_text("Paste a link…")
        self.url.connect("activate", lambda *_: self.send())
        paste = Gtk.Button(label="Paste")
        paste.get_style_context().add_class("quiet")
        paste.connect("clicked", self.on_paste)
        row.pack_start(self.url, True, True, 0)
        row.pack_end(paste, False, False, 0)
        box.pack_start(row, False, False, 0)

        self.note = Gtk.Entry()
        self.note.set_placeholder_text("note (optional)")
        self.note.connect("activate", lambda *_: self.send())
        box.pack_start(self.note, False, False, 0)

        self.send_btn = Gtk.Button(label="Send to inbox  ⏎")
        self.send_btn.get_style_context().add_class("go")
        self.send_btn.connect("clicked", lambda *_: self.send())
        box.pack_start(self.send_btn, False, False, 0)

        self.status = Gtk.Label(label="", xalign=0.0)
        self.status.get_style_context().add_class("error")
        box.pack_start(self.status, False, False, 0)

        box.pack_start(Gtk.Separator(), False, False, 4)

        # --- footer actions ----------------------------------------------
        foot = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self.open_btn = Gtk.Button(label="Open page")
        self.open_btn.get_style_context().add_class("quiet")
        self.open_btn.connect("clicked", self.on_open)
        self.clear_btn = Gtk.Button(label="Clear all links")
        self.clear_btn.get_style_context().add_class("danger")
        self.clear_btn.connect("clicked", self.on_clear)
        self.quit_btn = Gtk.Button(label="Quit")
        self.quit_btn.get_style_context().add_class("quiet")
        self.quit_btn.connect("clicked", self.on_quit)
        foot.pack_start(self.open_btn, False, False, 0)
        foot.pack_start(self.clear_btn, False, False, 0)
        foot.pack_end(self.quit_btn, False, False, 0)
        box.pack_start(foot, False, False, 0)

        self.footer = Gtk.Label(label="", xalign=0.0)
        self.footer.get_style_context().add_class("dim")
        box.pack_start(self.footer, False, False, 0)

        self.connect("destroy", lambda *_: Gtk.main_quit())
        GLib.timeout_add_seconds(2, self.tick)
        self.refresh()

    # --- helpers ---------------------------------------------------------
    def health(self, timeout=0.6):
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{PORT}/health", timeout=timeout) as r:
                return r.status == 200
        except Exception:
            return False

    def post(self, path, body="", timeout=3):
        req = urllib.request.Request(f"http://127.0.0.1:{PORT}{path}",
                                     data=body.encode(), method="POST")
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read().decode().strip()

    def alive(self):
        return self.proc is not None and self.proc.poll() is None

    @staticmethod
    def clear_pidfile():
        try:
            os.unlink(PIDFILE)
        except OSError:
            pass

    def set_pill(self, text, kind):
        ctx = self.pill.get_style_context()
        for c in ("on", "off", "err"):
            ctx.remove_class(c)
        ctx.add_class(kind)
        self.pill.set_text(text)

    def flash(self, msg, error=False):
        self.status.set_text(msg)
        ctx = self.status.get_style_context()
        if error:
            ctx.add_class("error")
        else:
            ctx.remove_class("error")
        if self.msg_timer:
            GLib.source_remove(self.msg_timer)
        self.msg_timer = GLib.timeout_add(4000, self.clear_msg)

    def clear_msg(self):
        self.status.set_text("")
        self.msg_timer = None
        return False

    def count(self):
        try:
            with open(INBOX, encoding="utf-8") as fh:
                return sum(1 for line in fh if line.strip())
        except FileNotFoundError:
            return 0

    def refresh(self):
        n = self.count()
        self.footer.set_text(f"{n} link{'s' if n != 1 else ''} on the page · kept {KEEP_DAYS} days")
        self.clear_btn.set_sensitive(n > 0)

    def tick(self):
        up = self.health(0.3)
        if up:
            self.set_pill("RUNNING", "on")
            self.toggle.set_label("Stop server")
            self.toggle.get_style_context().remove_class("go")
        elif self.alive():
            self.set_pill("STARTING…", "off")
        else:
            self.set_pill("STOPPED", "off")
            self.toggle.set_label("Start server")
            self.toggle.get_style_context().add_class("go")
        self.refresh()
        return True

    # --- server lifecycle ------------------------------------------------
    def on_toggle(self, *_):
        if self.health(0.3) or self.alive():
            self.stop_server()
        else:
            self.start_server()

    def start_server(self):
        os.makedirs(BASE, exist_ok=True)
        self.gen += 1
        gen = self.gen
        self.toggle.set_sensitive(False)
        self.toggle.set_label("Starting…")
        self.set_pill("STARTING…", "off")
        log = open(LOG, "ab", buffering=0)
        try:
            # FRAME_INBOX_PARENT makes the server exit if this panel dies
            env = dict(os.environ, FRAME_INBOX_PARENT=str(os.getpid()))
            self.proc = subprocess.Popen([PY, SERVER], stdout=log, stderr=subprocess.STDOUT,
                                         cwd=BASE, env=env)
        except OSError as exc:
            self.toggle.set_sensitive(True)
            self.flash(f"Could not launch: {exc}", error=True)
            return
        self.deadline = time.time() + 20
        GLib.timeout_add(250, self.poll_start, gen)

    def poll_start(self, gen):
        if gen != self.gen:
            return False          # superseded by a newer start/stop
        if self.health(0.3):
            self.toggle.set_sensitive(True)
            self.tick()
            self.flash("Server is up — open the page on your phone")
            return False
        if time.time() > self.deadline or (self.proc and self.proc.poll() is not None):
            self.toggle.set_sensitive(True)
            self.tick()
            self.flash(f"Did not start — see {os.path.basename(LOG)}", error=True)
            return False
        GLib.timeout_add(250, self.poll_start, gen)
        return False

    def stop_server(self):
        self.gen += 1
        gen = self.gen
        # ask the server to exit, so it works even if something else started it
        try:
            self.post("/shutdown", timeout=1)
        except Exception:
            pass
        self.stop_deadline = time.time() + 4
        GLib.timeout_add(150, self.poll_stop, gen)
        self.toggle.set_sensitive(False)
        self.set_pill("STOPPING…", "off")

    def poll_stop(self, gen):
        if gen != self.gen:
            return False          # superseded by a newer start/stop
        if not self.health(0.2):
            if self.proc:
                try:
                    self.proc.wait(timeout=1)
                except Exception:
                    self.proc.kill()
                self.proc = None
            self.clear_pidfile()
            self.toggle.set_sensitive(True)
            self.tick()
            return False
        if time.time() > self.stop_deadline:
            if self.proc and self.proc.poll() is None:
                self.proc.kill()
            self.proc = None
            self.clear_pidfile()
            self.toggle.set_sensitive(True)
            self.tick()
            return False
        GLib.timeout_add(150, self.poll_stop, gen)
        return False

    # --- actions ---------------------------------------------------------
    def on_paste(self, *_):
        text = Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD).wait_for_text() or ""
        text = text.strip().splitlines()[0] if text.strip() else ""
        if text:
            self.url.set_text(text)
            self.url.set_position(-1)
        else:
            self.flash("Clipboard is empty", error=True)

    def send(self):
        url = self.url.get_text().strip()
        note = self.note.get_text().strip()
        if not url:
            self.flash("Nothing to send — paste a link first", error=True)
            return
        if not re.match(r"^[a-zA-Z][a-zA-Z0-9+.\-]*:\S+$", url):
            self.flash("Needs to look like https://… or scheme:…", error=True)
            return
        try:
            if self.health(0.3):
                self.post("/add", url + (f"\n{note}" if note else ""))
            else:
                os.makedirs(BASE, exist_ok=True)
                with open(INBOX, "a", encoding="utf-8") as fh:
                    fh.write(json.dumps({"t": time.time(), "url": url, "note": note}) + "\n")
        except Exception as exc:
            self.flash(f"Send failed: {exc}", error=True)
            return
        self.url.set_text("")
        self.note.set_text("")
        self.refresh()
        self.flash("Sent" if self.health(0.2) else "Saved (server is stopped — it appears when you start it)")

    def on_open(self, *_):
        if not self.health(0.3):
            self.flash("Start the server first", error=True)
            return
        Gtk.show_uri_on_window(self, f"http://127.0.0.1:{PORT}", Gdk.CURRENT_TIME)

    def disarm(self):
        self.armed = False
        if self.arm_timer:
            GLib.source_remove(self.arm_timer)
            self.arm_timer = None
        self.clear_btn.set_label("Clear all links")
        self.clear_btn.get_style_context().remove_class("armed")

    def on_clear(self, *_):
        if not self.armed:
            self.armed = True
            self.clear_btn.set_label("Confirm — tap again")
            self.clear_btn.get_style_context().add_class("armed")
            self.arm_timer = GLib.timeout_add_seconds(5, self.disarm_and_false)
            return
        self.disarm()
        try:
            if self.health(0.3):
                n = int(self.post("/clear") or 0)
            else:
                n = self.count()
                with open(INBOX, "w", encoding="utf-8"):
                    pass
        except Exception as exc:
            self.flash(f"Clear failed: {exc}", error=True)
            return
        self.refresh()
        self.flash(f"Cleared {n} link{'s' if n != 1 else ''}" if n else "Inbox was already empty")

    def disarm_and_false(self):
        self.disarm()
        return False

    def on_delete(self, *_):
        # closing the window parks it in the taskbar; the page keeps serving
        if self.health(0.3) or self.alive():
            self.iconify()
            return True
        Gtk.main_quit()
        return False

    def quit_app(self):
        if self.owns_loop:
            Gtk.main_quit()

    def on_quit(self, *_):
        if self.health(0.3) or self.alive():
            try:
                self.post("/shutdown", timeout=1)
            except Exception:
                pass
            if self.proc and self.proc.poll() is None:
                time.sleep(0.3)
                self.proc.kill()
        self.quit_app()


def main():
    provider = Gtk.CssProvider()
    provider.load_from_data(CSS)
    Gtk.StyleContext.add_provider_for_screen(
        Gdk.Screen.get_default(), provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
    Gtk.Window.set_default_icon_name("frame-inbox")
    win = Panel()
    win.owns_loop = True
    win.show_all()
    win.present()
    # opening the panel means "I want to share something" - bring the page up
    if not win.health(0.3):
        win.start_server()
    Gtk.main()


if __name__ == "__main__":
    main()
