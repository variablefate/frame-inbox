# Frame Inbox

Paste a link on your desktop, tap it on your phone. No QR codes, no phone apps, no accounts, no cloud.

Built for a Steam Frame headset running SteamOS, but it works on any Linux desktop with GTK3.

![The control panel](docs/panel.png)

## How it works

- **`server.py`** — a stdlib `http.server` on port 8765 rendering a dark, thumb-sized list. `http(s)` rows open in the phone's browser; anything else with a scheme (`magnet:`, `mailto:`, `ss://`, `obsidian://`, …) renders as a **copy** row, because a phone browser cannot open those. Tapping copies it to the clipboard.
- **`control.py`** — a GTK3 panel that starts and stops that server, sends links into it, and clears it. It owns the server's lifetime: the server is armed with a parent-death watchdog, so it cannot outlive the panel even if the panel is killed.
- **`sendlink`** — a CLI for sending without opening the panel.

The page is deliberately small: a list, a per-row delete, and a confirm-guarded clear. Entries expire after 7 days, pruned whenever something is written.

## Requirements

- Linux with GTK3 Python bindings (`python3-gi`)
- Python 3.9+
- Optional: `rsvg-convert` (icon rendering), `node` (only for the smoke test)

## Install

### On the headset itself

No Windows PC needed — the Frame is a PC, it just isn't a Windows one. Desktop Mode → Konsole → paste this line (the copy button appears on hover):

```bash
git clone https://github.com/variablefate/frame-inbox && cd frame-inbox && ./install.sh --desktop-icon
```

That puts the app in `~/.local/share/frame-inbox/`, the launchers in `~/.local/bin/`, and an icon on the desktop. Nothing is installed system-wide, no root is needed, and `git` ships with SteamOS.

### From a Windows PC with FrameDrop

[![Install with FrameDrop](docs/framedrop-button.svg)](https://framedropvr.com/install?manifest=https%3A%2F%2Fraw.githubusercontent.com%2Fvariablefate%2Fframe-inbox%2Fmain%2Fframedrop.json)

On a Windows PC with [FrameDrop](https://framedropvr.com/) paired to your headset, that button downloads the ARM64 bundle and adds it to the Steam library. It is the same code as the installer above, just pre-packaged to run from wherever it unpacks.

FrameDrop's client is Windows-only, and its install page has no fallback when opened in the headset's own browser — so a headset-only setup uses the one-liner above instead.

Verifying the sideload bundle: `sha256sum frame-inbox-linux-arm64.zip` should print `c181c303352608d0ed88dcf1ea445f3b2007b1892c161ee5ca8b48ea33f65e36` (also in [`framedrop.json`](framedrop.json)).

### Either way, then

1. Launch **Frame Inbox** (app menu, desktop icon, or the Steam library if FrameDrop installed it).
2. On the phone, open `http://<your-lan-ip>:8765` and *Add to Home screen*.
3. Paste a link, hit **Send to inbox**, tap it on the phone.

Use the IP, not a `.local` name — Android Chrome does not resolve mDNS reliably.

## Using the panel

| Control | What it does |
|---|---|
| Start / Stop | Runs or stops the local server (starting happens automatically when the panel opens) |
| Paste | Pulls the clipboard into the link field |
| Send to inbox | Adds the link (and optional note); works even when the server is stopped |
| Open page | Opens the page in the local browser |
| Clear all links | Two-step: first click arms it for 5 s, second click wipes |
| × on a row | Deletes that link, with a 6 s undo toast |
| A `magnet:` / `mailto:` / other-scheme row | Tapping copies the text instead of navigating (the page runs on plain HTTP, so it falls back to `execCommand` — `navigator.clipboard` does not exist there) |
| Quit | Stops the server, then exits |

Closing the window minimizes it to the taskbar while the page keeps serving. There is no tray icon: this image ships no AppIndicator bindings, and a package install would not survive SteamOS atomic updates — the taskbar entry is the equivalent.

## CLI

```bash
sendlink 'https://example.com/x' 'optional note'   # add (also prunes)
sendlink -                                         # read the url from stdin
sendlink                                           # list the newest 15
sendlink --push 'https://example.com/x'            # also send an ntfy notification
sendlink --topic                                   # generate/pick the ntfy topic
sendlink --prune                                   # apply retention now
sendlink --clear                                   # empty the inbox
```

`--push` uses [ntfy.sh](https://ntfy.sh): install the ntfy app on the phone, subscribe to the topic once, and tapping the notification opens the link. Useful when the phone is not on the same Wi-Fi.

## Configuration

| Variable | Default | Meaning |
|---|---|---|
| `SENDLINK_PORT` | `8765` | Port to serve on |
| `SENDLINK_KEEP_DAYS` | `7` | Retention window; `0` keeps forever |
| `FRAME_INBOX_HOME` | `$XDG_DATA_HOME/frame-inbox` | Where the server, store and log live |
| `FRAME_INBOX_PATH` | `$FRAME_INBOX_HOME/inbox.jsonl` | Store location (used by tests) |
| `FRAME_INBOX_PIDFILE` | `$FRAME_INBOX_HOME/server.pid` | Pid file location (used by tests) |

## HTTP API

| Route | Behaviour |
|---|---|
| `GET /` | The page |
| `GET /raw` | Plain text, newest first |
| `GET /latest` | 302 to the newest entry |
| `GET /health` | `ok` |
| `POST /add` | Body: `url` or `url\nnote` |
| `POST /delete` | Body: entry id |
| `POST /clear` | Wipes everything, returns the count |
| `POST /shutdown` | Answers, then exits |

## Security

The page has no authentication. Anything on your LAN can read the links and delete them. It is meant for a trusted home network — do not run it on a network you would not hand your clipboard to.

## Development

The panel and server are plain Python, no build step. After an edit, restart the panel (it spawns a fresh server).

```bash
xvfb-run -a python3 scripts/panel-smoke-test.py
```

That drives the real GTK handlers headlessly — start, send, clear, stop, restart, quit — checks the page's inline JavaScript parses, and asserts the live inbox is untouched (it points the store at a temp dir).

Layout notes worth knowing before you change things:

- The page template is assembled with `.replace()` markers, never `str.format()` — every CSS/JS brace would otherwise need doubling.
- Any backslash that must reach JavaScript has to be written `\\n` in the Python source; a live newline silently kills the whole `<script>` block.
- Start/stop pollers carry a generation counter. Without it, a stop-poller left over from the previous stop kills the server you just restarted.

## Uninstall

```bash
rm -rf ~/.local/share/frame-inbox ~/.local/bin/frame-inbox ~/.local/bin/sendlink \
       ~/.local/share/applications/frame-inbox.desktop ~/Desktop/frame-inbox.desktop
```

## License

MIT
