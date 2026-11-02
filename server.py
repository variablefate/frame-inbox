#!/usr/bin/env python3
"""Frame inbox — a tiny web page listing links pushed from the headset.

Listens on 0.0.0.0:8765 and renders ~/.local/share/sendlink/inbox.jsonl
(newest entry first). No auth: intended for a trusted home LAN only.

Entries older than SENDLINK_KEEP_DAYS (default 7) are dropped on every write.
"""
import hashlib
import html
import json
import os
import re
import secrets
import signal
import sys
import threading
import time
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

BASE = (os.environ.get("FRAME_INBOX_HOME")
        or os.path.join(os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share"),
                        "frame-inbox"))
INBOX = os.environ.get("FRAME_INBOX_PATH") or os.path.join(BASE, "inbox.jsonl")
PIDFILE = os.environ.get("FRAME_INBOX_PIDFILE") or os.path.join(BASE, "server.pid")
PORT = int(os.environ.get("SENDLINK_PORT", "8765"))
MAX_ITEMS = 500
# Entries older than this are dropped whenever something is written (0 = keep forever).
KEEP_DAYS = float(os.environ.get("SENDLINK_KEEP_DAYS", "7"))

PAGE = """<!doctype html>
<html lang="en"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="theme-color" content="#111318">
<title>Frame inbox</title>
<style>
  :root { color-scheme: dark; }
  body { margin:0; padding:18px 14px 90px; background:#111318; color:#e8eaf0;
         font:16px/1.45 -apple-system,system-ui,"Segoe UI",Roboto,sans-serif;
         -webkit-text-size-adjust:100%; }
  header { display:flex; align-items:center; justify-content:space-between;
           gap:8px; margin:0 0 14px; flex-wrap:wrap; }
  h1 { font-size:14px; font-weight:600; letter-spacing:.1em; text-transform:uppercase;
       color:#8b93a7; margin:0; }
  nav { display:flex; gap:8px; }
  .btn { font:inherit; font-size:13px; padding:7px 12px; border-radius:999px;
         background:#1a1e26; border:1px solid #2a2f3a; color:#9aa3b5;
         text-decoration:none; cursor:pointer; }
  .btn:active { background:#232935; }
  .btn.danger { background:#3a1d22; border-color:#5c2b33; color:#ff9aa8; }
  ul { list-style:none; margin:0; padding:0; }
  li.row { position:relative; margin:0 0 10px; transition:opacity .15s, transform .15s; }
  li.row.gone { opacity:0; transform:translateX(24px); }
  a.item, button.item { display:block; width:100%; padding:14px 58px 14px 16px;
           border-radius:14px; background:#1a1e26; border:1px solid #262c38;
           text-decoration:none; color:inherit; font:inherit; text-align:left;
           cursor:pointer; -webkit-tap-highlight-color:transparent; }
  a.item:active, button.item:active { background:#232935; }
  button.item.copied { border-color:#2f5a8c; background:#17222f; }
  .t { font-weight:600; color:#f2f4f8; word-break:break-word; }
  .u { font-size:13px; color:#8b93a7; margin-top:4px; word-break:break-all; }
  .n { font-size:13px; color:#b9c1d1; margin-top:6px; font-style:italic; }
  .meta { font-size:12px; color:#5f6779; margin-top:8px; }
  .del { position:absolute; top:10px; right:10px; width:36px; height:36px; padding:0;
         border-radius:11px; background:#20252f; border:1px solid #2b313d;
         color:#8b93a7; font-size:18px; line-height:1; cursor:pointer;
         -webkit-tap-highlight-color:transparent; }
  .del:active { background:#3a1d22; border-color:#5c2b33; color:#ff9aa8; }
  .empty { color:#6b7385; padding:26px 2px; }
  #toast { position:fixed; left:14px; right:14px; bottom:18px; max-width:420px; margin:0 auto;
           display:none; align-items:center; gap:12px; background:#232935;
           border:1px solid #333a49; border-radius:14px; padding:11px 8px 11px 16px;
           font-size:14px; box-shadow:0 10px 26px rgba(0,0,0,.5); }
  #toast.on { display:flex; }
  #toast span { flex:1; }
  #toast button { background:none; border:0; color:#6ea8fe; font:inherit;
                  font-weight:600; padding:6px 10px; cursor:pointer; }
</style>
<header>
  <h1>Frame inbox</h1>
  <nav>
    <a class="btn" href="/">Refresh</a>
    <button class="btn" id="clear" type="button" __CLEARHIDDEN__>Clear all</button>
  </nav>
</header>
<ul id="list">__ROWS__</ul>
<template id="empty"><p class="empty">Nothing here yet. Run <code>sendlink &lt;url&gt;</code> on the headset.</p></template>
<div id="toast" role="status" aria-live="polite"><span id="toast-text"></span><button id="toast-action" type="button"></button></div>
<script>
(function () {
  var toast = document.getElementById('toast');
  var toastText = document.getElementById('toast-text');
  var toastAction = document.getElementById('toast-action');
  var toastTimer = null;

  function notify(msg, actionLabel, action) {
    toastText.textContent = msg;
    clearTimeout(toastTimer);
    if (actionLabel) {
      toastAction.hidden = false;
      toastAction.textContent = actionLabel;
      toastAction.onclick = function () { toast.classList.remove('on'); action(); };
    } else {
      toastAction.hidden = true;
      toastAction.onclick = null;
    }
    toast.classList.add('on');
    toastTimer = setTimeout(function () { toast.classList.remove('on'); }, 6000);
  }

  async function post(path, body) {
    var res = await fetch(path, { method: 'POST', body: body || '' });
    if (!res.ok) throw new Error((await res.text()).trim() || res.status);
    return res;
  }

  // this page is served over plain http on a LAN address, so navigator.clipboard
  // is usually undefined; execCommand still works from a real tap
  function legacyCopy(text) {
    var ta = document.createElement('textarea');
    ta.value = text;
    ta.setAttribute('readonly', '');
    ta.style.position = 'fixed';
    ta.style.top = '-1000px';
    ta.style.opacity = '0';
    document.body.appendChild(ta);
    ta.select();
    ta.setSelectionRange(0, text.length);
    var ok = false;
    try { ok = document.execCommand('copy'); } catch (e) { ok = false; }
    document.body.removeChild(ta);
    return ok;
  }

  async function copyText(btn) {
    var text = btn.getAttribute('data-copy') || '';
    var ok = false;
    if (window.isSecureContext && navigator.clipboard) {
      try { await navigator.clipboard.writeText(text); ok = true; } catch (e) { ok = false; }
    }
    if (!ok) ok = legacyCopy(text);
    var hint = btn.querySelector('.u');
    if (ok) {
      var old = hint.textContent;
      hint.textContent = 'copied';
      btn.classList.add('copied');
      setTimeout(function () { hint.textContent = old; btn.classList.remove('copied'); }, 1800);
      notify('Copied to clipboard');
    } else {
      notify('Could not copy — long-press the row instead');
    }
  }

  function sweep() {
    var list = document.getElementById('list');
    if (list.querySelector('li.row')) return;
    list.textContent = '';
    list.appendChild(document.getElementById('empty').content.cloneNode(true));
    var clearBtn = document.getElementById('clear');
    if (clearBtn) clearBtn.hidden = true;
  }

  document.getElementById('list').addEventListener('click', async function (ev) {
    var copyBtn = ev.target.closest('button.item.copy');
    if (copyBtn) {
      ev.preventDefault();
      copyText(copyBtn);
      return;
    }
    var btn = ev.target.closest('button.del');
    if (!btn) return;
    ev.preventDefault();
    var li = btn.closest('li.row');
    var link = li.querySelector('a.item');
    var url = link.href;
    var note = li.dataset.note || '';
    btn.disabled = true;
    try {
      await post('/delete', btn.dataset.id);
      li.classList.add('gone');
      setTimeout(function () { li.remove(); sweep(); }, 150);
      notify('Removed', 'Undo', async function () {
        try { await post('/add', url + (note ? '\\n' + note : '')); location.reload(); }
        catch (e) { notify('Undo failed'); }
      });
    } catch (e) {
      btn.disabled = false;
      notify('Could not delete: ' + e.message);
    }
  });

  var clearBtn = document.getElementById('clear');
  var armed = false, armTimer = null;
  function disarm() {
    armed = false;
    clearTimeout(armTimer);
    clearBtn.classList.remove('danger');
    clearBtn.textContent = 'Clear all';
  }
  if (clearBtn) clearBtn.addEventListener('click', async function () {
    if (!armed) {
      armed = true;
      clearBtn.classList.add('danger');
      clearBtn.textContent = 'Confirm clear';
      armTimer = setTimeout(disarm, 5000);
      return;
    }
    disarm();
    clearBtn.disabled = true;
    try {
      var res = await post('/clear');
      var n = parseInt(await res.text(), 10);
      document.getElementById('list').textContent = '';
      document.getElementById('list').appendChild(
        document.getElementById('empty').content.cloneNode(true));
      clearBtn.hidden = true;
      notify(n ? 'Cleared ' + n + ' link' + (n === 1 ? '' : 's') : 'Inbox already empty');
    } catch (e) {
      clearBtn.disabled = false;
      notify('Could not clear: ' + e.message);
    }
  });
}());
</script>
"""


def entry_id(item):
    """Stable id for an entry; derives one for legacy lines written without it."""
    if item.get("id"):
        return item["id"]
    raw = f'{item.get("url", "")}|{item.get("t", 0)}|{item.get("note", "")}'
    return hashlib.sha1(raw.encode()).hexdigest()[:10]


def read_all():
    """Every entry in file order (oldest first)."""
    items = []
    try:
        with open(INBOX, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    item = json.loads(line)
                except ValueError:
                    continue
                item["id"] = entry_id(item)
                items.append(item)
    except FileNotFoundError:
        pass
    return items


def write_all(items):
    os.makedirs(os.path.dirname(INBOX), exist_ok=True)
    tmp = INBOX + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        for item in items:
            item = {k: v for k, v in item.items() if k != "id"}
            fh.write(json.dumps(item) + "\n")
    os.replace(tmp, INBOX)


def append_entry(entry):
    os.makedirs(os.path.dirname(INBOX), exist_ok=True)
    with open(INBOX, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry) + "\n")


def prune(keep_days=None):
    """Drop entries older than keep_days. Returns how many were removed."""
    days = KEEP_DAYS if keep_days is None else keep_days
    if not days or days <= 0 or not os.path.exists(INBOX):
        return 0
    cutoff = time.time() - days * 86400
    items = read_all()
    keep = [i for i in items if i.get("t", 0) >= cutoff]
    dropped = len(items) - len(keep)
    if dropped:
        write_all(keep)
    return dropped


def delete_entry(target):
    items = read_all()
    keep = [i for i in items if i["id"] != target]
    removed = len(items) - len(keep)
    if removed:
        write_all(keep)
    return removed


def write_pidfile():
    try:
        with open(PIDFILE, "w", encoding="utf-8") as fh:
            fh.write(str(os.getpid()))
    except OSError:
        pass


def clear_pidfile():
    try:
        with open(PIDFILE, encoding="utf-8") as fh:
            mine = fh.read().strip() == str(os.getpid())
        if mine:
            os.unlink(PIDFILE)
    except (OSError, ValueError):
        pass


def watch_parent():
    """Exit if the panel that launched us dies — crash, SIGKILL, or OOM.

    Set by the control panel as FRAME_INBOX_PARENT=<panel pid>. Two mechanisms:
    the kernel's PDEATHSIG (fires even on SIGKILL) and a 3s getppid() poll
    (catches the case where prctl is unavailable or raced).
    """
    expected = os.environ.get("FRAME_INBOX_PARENT")
    if not expected:
        return
    try:
        expected = int(expected)
    except ValueError:
        return
    try:
        import ctypes
        ctypes.CDLL("libc.so.6", use_errno=True).prctl(1, signal.SIGTERM)  # PR_SET_PDEATHSIG
    except Exception:
        pass
    if os.getppid() != expected:
        os._exit(0)          # parent died before we armed

    def poll():
        while True:
            time.sleep(3)
            if os.getppid() != expected:
                os._exit(0)

    threading.Thread(target=poll, daemon=True).start()


LINK_RE = re.compile(r"^([a-z][a-z0-9+.\-]*):(\S+)$", re.I)
# schemes that must never be stored: they mean nothing as text and are dangerous if
# anything downstream ever treats them as navigable
COPY_BLOCK = {"javascript", "data", "vbscript", "blob", "file"}


def link_type(value):
    """'page' = open it, 'copy' = hand it to the clipboard, None = not a link."""
    if not isinstance(value, str):
        return None
    m = LINK_RE.match(value.strip())
    if not m:
        return None
    scheme = m.group(1).lower()
    if scheme in COPY_BLOCK:
        return None
    if scheme in ("http", "https"):
        rest = value.split("://", 1)
        return "page" if len(rest) == 2 and rest[1].strip() else None
    return "copy"


def row_html(item):
    url = item["url"]
    kind = link_type(url)
    ts = item.get("t", 0)
    when = datetime.fromtimestamp(ts).strftime("%d %b, %H:%M") if ts else ""
    note = item.get("note") or ""
    note_div = f'<div class="n">{html.escape(note)}</div>' if note else ""
    esc = html.escape(url, quote=True)
    if kind == "page":
        body = (f'<a class="item" href="{esc}">'
                f'<div class="t">{html.escape(url)}</div>'
                f'<div class="u">{html.escape(url.split("://", 1)[-1])}</div>'
                f'{note_div}<div class="meta">{when}</div></a>')
    else:
        scheme = html.escape(url.split(":", 1)[0].lower())
        body = (f'<button class="item copy" type="button" data-copy="{esc}">'
                f'<div class="t">{html.escape(url)}</div>'
                f'<div class="u">{scheme} · tap to copy</div>'
                f'{note_div}<div class="meta">{when}</div></button>')
    return (
        f'<li class="row" data-note="{html.escape(note, quote=True)}">'
        f"{body}"
        f'<button class="del" type="button" data-id="{html.escape(item["id"], quote=True)}"'
        f' aria-label="Delete link" title="Delete">&times;</button></li>'
    )


def render(items):
    rows = "".join(row_html(i) for i in items if link_type(i.get("url")))
    has_rows = 'class="row' in rows
    return (PAGE
            .replace("__ROWS__", rows)
            .replace("__CLEARHIDDEN__", "" if has_rows else "hidden"))


class Handler(BaseHTTPRequestHandler):
    server_version = "frame-inbox/2"

    def _send(self, code, body=b"", ctype="text/html; charset=utf-8", extra=None):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if body and self.command != "HEAD":
            self.wfile.write(body)

    def _plain(self, code, text):
        self._send(code, (text + "\n").encode(), "text/plain; charset=utf-8")

    def do_HEAD(self):
        self.do_GET()

    def do_GET(self):
        path = self.path.split("?", 1)[0].rstrip("/") or "/"
        items = read_all()[::-1][:MAX_ITEMS]
        if path == "/":
            self._send(200, render(items).encode())
        elif path == "/raw":
            lines = "\n".join(i.get("url", "") for i in items if link_type(i.get("url")))
            self._send(200, (lines + "\n").encode(), "text/plain; charset=utf-8")
        elif path == "/latest":
            live = [i for i in items if link_type(i.get("url")) == "page"]
            if live:
                self._send(302, b"", extra={"Location": live[0]["url"]})
            else:
                self._plain(404, "inbox is empty")
        elif path == "/health":
            self._plain(200, "ok")
        else:
            self._plain(404, "not found")

    def do_POST(self):
        path = self.path.split("?", 1)[0].rstrip("/")
        length = int(self.headers.get("Content-Length") or 0)
        if length > 8192:
            return self._plain(413, "too big")
        body = self.rfile.read(length).decode("utf-8", "replace") if length else ""

        if path == "/add":
            url, _, note = body.strip().partition("\n")
            url, note = url.strip(), note.strip()
            if link_type(url) is None:
                return self._plain(400, "not a link: use https://… or scheme:…")
            append_entry({"t": time.time(), "url": url, "note": note,
                          "id": secrets.token_hex(5)})
            prune()
            self._plain(200, "ok")
        elif path == "/delete":
            target = body.strip()
            if not target:
                return self._plain(400, "missing id")
            removed = delete_entry(target)
            prune()
            self._plain(200, str(removed))
        elif path == "/clear":
            count = len(read_all())
            write_all([])
            self._plain(200, str(count))
        elif path == "/shutdown":
            self._plain(200, "bye")
            clear_pidfile()
            threading.Timer(0.2, lambda: os._exit(0)).start()
        else:
            self._plain(404, "not found")

    def log_message(self, fmt, *args):
        print("%s  %s" % (self.log_date_time_string(), fmt % args), flush=True)


if __name__ == "__main__":
    os.makedirs(os.path.dirname(INBOX), exist_ok=True)
    if "--prune" in sys.argv:
        if KEEP_DAYS and KEEP_DAYS > 0:
            print(f"removed {prune()} entries older than {KEEP_DAYS:g} days")
        else:
            print("pruning disabled (SENDLINK_KEEP_DAYS=0)")
        raise SystemExit(0)
    watch_parent()
    signal.signal(signal.SIGTERM, lambda *_: (clear_pidfile(), os._exit(0)))
    write_pidfile()
    dropped = prune()
    if dropped:
        print(f"startup prune: removed {dropped} entries older than {KEEP_DAYS:g} days", flush=True)
    srv = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    print(f"frame-inbox on http://0.0.0.0:{PORT}  (inbox: {INBOX}, keep: {KEEP_DAYS:g}d)", flush=True)
    srv.serve_forever()
