# Security model

Frame Inbox is a personal LAN tool. It has **no authentication by design** — the
page your phone opens and the API it talks to are the same thing, and adding a
login would defeat the point of a two-tap handoff.

## What that means in practice

- **Anyone on your network can read, add and delete links.** Treat the page as
  public to your LAN. Don't run it on a network you would not hand your
  clipboard to (cafés, hotels, conferences).
- **Traffic is plain HTTP.** The links travel unencrypted over Wi-Fi. Anything
  sniffing the network can see them. There is no TLS, and adding a self-signed
  cert to a page a phone must trust with one tap is worse than the problem.
- **Never expose it to the internet.** No port forwarding, no reverse proxy, no
  tunnel. It is not built for that and will not survive it.

## What is protected, and how

| Concern | Mitigation |
|---|---|
| CSRF — any website you visit while on the LAN POSTing to `/clear` | Writes are rejected when `Origin` is present and not the same origin, or when `Sec-Fetch-Site` is anything but `same-origin`/`none`. Requests with no `Origin` (the CLI, the panel) still work. |
| DNS rebinding — `attacker.com` resolving to your headset | `Host` must be an IP literal, `localhost`, this machine's hostname, or a `*.local` name. A rebindable domain is rejected with 403. |
| XSS via a crafted link or note | Everything is HTML-escaped on the way in, and every response carries a strict CSP (`default-src 'none'`, inline script/style only, no frames). |
| Clickjacking — embedding the page to trick a tap | `X-Frame-Options: DENY` and `frame-ancestors 'none'`. |
| Stored links readable by other local accounts | The store, log and pid file are created `0600` in a `0700` directory (`umask 077`). |
| Header/response sniffing | `X-Content-Type-Options: nosniff`, `Referrer-Policy: no-referrer`. |
| Untrusted input shapes | Only `http(s)://…` and `scheme:…` are accepted; `javascript:`, `data:`, `vbscript:`, `blob:` and `file:` are refused. Request bodies are capped at 8 KB. |

## Known and accepted

- A device on your LAN can wipe the inbox or stop the server. That is the same
  reach as anyone who can open the page.
- No rate limiting. A LAN peer can spam `/add`.
- The parent-death watchdog only protects against the panel dying; it is not a
  sandbox, and the server runs with your user's privileges.

## Reporting

Open a [private security advisory](https://github.com/variablefate/frame-inbox/security/advisories/new)
rather than a public issue.
