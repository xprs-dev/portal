# Plan: the portal over Reticulum, from any browser

Status 2026-11-10: **a plan, not started.** It replaces HTTPS on the boards
(`firmware/docs/plan-firmware-https.md`, set aside).

## The idea

`https://xprs.dev/in/x3ptzm` opens the portal of station X3PTZM from
anywhere. The page comes from xprs.dev (HTTPS, a trusted certificate, the same
page every station serves). It carries Reticulum in JavaScript, connects by
`wss://` to one of a list of gateways (XPRS server stations on Linux, like
the Pi), and from there reaches the station inside the Reticulum network,
wherever it is: a board behind any NAT, a phone, a server. The page then talks
to that station's API over a Reticulum link instead of HTTP.

```
browser ──wss──> gateway (Linux XPRS server, a Reticulum transport node)
                   └── Reticulum (hubs, other transports) ──> the station
browser <──── end-to-end encrypted Reticulum link (X25519 + AES) ────> station
```

What it gives:

- **No TLS, certificate, port forwarding or public address on the station.**
  A board needs only what it already has: an outbound Reticulum uplink.
  The C3 qualifies as it is.
- **End-to-end privacy.** The gateway forwards Reticulum packets; the link is
  encrypted between the browser and the station. The gateway cannot read it.
- **One page.** The portal is the same file everywhere; only its transport
  changes (HTTP on the station's own network, Reticulum from xprs.dev).

## How each part works

### 1. Reticulum in the browser: reticulum-dart compiled to JavaScript

reticulum-dart is pure Dart, and the app already builds the core for the web
(dart2js / dart2wasm). Compile the parts the browser needs (identity, packets,
announces, path requests, links, link requests, resources) into one module,
`rns.js`, behind a small JS interface: `connect(wsUrl)`, `resolve(call)`,
`link(dest)`, `request(path, data)`, `resource(...)`. One implementation of
Reticulum, reused, rather than a second one written in JavaScript. The module
is loaded only by the xprs.dev shell, never embedded in a board's page.

### 2. The gateway: a WebSocket interface on the Linux server

A new reticulum-dart interface, `RnsWebSocketServerInterface`: one Reticulum
packet per WebSocket frame (no HDLC framing), served by the server's own web
server at `/rns` (on 443 with its existing certificate, and on 80 for its own
network). Each browser is one interface client of the server's transport
node, so the server routes its packets like any other's. Per-client limits:
packets per second, bytes per minute, open links, idle timeout.

A server becomes a gateway by a setting (`gateway: true`, on by default for a
server that has a public name). It announces it in its `dial:` beacon; the
names keeper lists the live ones.

### 3. Finding the station by its callsign

The browser needs the station's Reticulum destination. Every station already
announces `xprs.wapp` with a signed XPRS beacon in the announce data, and that
beacon names its Reticulum identity (`lx:`). So:

- the gateway answers "who is X3PTZM?" from the announces it holds (a link
  request to the gateway's own destination, `/resolve`), or the browser sends a
  path request and listens;
- the browser **checks** what it gets: the beacon's XPRS signature verifies
  against the callsign's key, and the `lx:` in it matches the announcing
  identity. A gateway cannot hand it a different station.

### 4. The API over Reticulum: link requests

Every `/api/...` call becomes a Reticulum link request on the station's
destination (the NomadNet mechanism reticulum-dart already speaks):
the path is the API path, the data carries method, query and body, and the
response carries status, content type and body. Files are Reticulum
resources; a range is a request with `range` in its data. No new XPRS words;
`spec/API-HTTP.md` gains a section "The same API over a Reticulum link".

- **Dart stations (server, app):** the link request handler calls
  `WebChatApi.handle()` directly: every endpoint, as on HTTP.
- **Boards:** the firmware's Reticulum is a client today (it opens links, it
  does not accept them). It gains a link responder on its `xprs.wapp`
  destination (accept, prove, derive keys), the request dispatcher (msgpack,
  calling the same handlers `xprs_api` registers with httpd), and a resource
  sender for files. At most two links; their memory is claimed when a link
  opens.

### 5. The page: one transport switch

The portal's few network calls (`getJSON`, `postWire`, the file uploads and
reads) go through one function, `api(method, path, body)`. On the station's
own network it is HTTP, as now; under `xprs.dev/in/<call>` it is a link
request. Images and files the page shows by URL (`/api/xprs/file/<ref>`)
become blob URLs fetched over the link. The session proof (a signed nonce)
works unchanged: the station sees a visitor from the internet, never a local
one, so the admin claim and WiFi changes stay closed to it.

### 6. xprs.dev/in/<callsign>

On GitHub Pages (`xprs-dev.github.io`): one static shell for every
`/in/<call>` path (GitHub Pages' `404.html` serves any unknown path; the shell
reads the callsign from the URL). It loads the portal page and `rns.js`, reads
the gateway list (a static `gateways.json` in the site, refreshed from the
names keeper's live list), tries them in order until one connects, resolves
the callsign, opens the link, and hands the portal its transport. It shows
which gateway it went through, and offers the next one if a gateway fails.

## Steps

1. **Spec**: the API over a Reticulum link, the WebSocket framing, `/resolve`,
   the gateway list format.
2. **reticulum-dart**: the WebSocket interface (server side for the gateway,
   client side for the browser), and the JS build of the browser subset with a
   test in headless Chromium (connect, resolve, link, request).
3. **Server**: `/rns` on its web server, the gateway setting and limits, link
   requests into `WebChatApi.handle()`, files as resources. Test: a browser on
   the Pi reaches the Pi's own station through its own gateway.
4. **Portal**: the transport switch; the xprs.dev shell; the browser tests run
   once over HTTP and once over Reticulum against the mock.
5. **Firmware**: link responder, request dispatcher, resource sender; host
   tests; QEMU (its Reticulum uplink to a gateway on the Pi), then the bench C3.
6. **xprs.dev**: the `/in/` shell and `gateways.json`; the names keeper
   publishes the live gateway list.
7. **The app** (phones): the same link requests, so a phone's station is
   reachable the same way.

## Limits to know

- **Speed.** Reticulum over public hubs is slow and rationed: JSON and
  pictures are fine; films and large files are slow. Stations should also
  uplink to our gateways (the gateway list doubles as a hub list), which
  keeps the path short and on infrastructure we run.
- **The gateway sees traffic patterns** (who talks to which destination, how
  much), not content.
- **The page's integrity** rests on xprs.dev (GitHub Pages, HTTPS).
- **A board's memory**: two links and a resource at a time; the C3's budget
  is measured in step 5 before it is turned on there.
