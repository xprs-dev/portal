# Plan: the portal as an app on the phone, and likes on posts

Status 2026-11-27: **a plan, not started.**

## Where we are

- **Reaching a station from anywhere already works.** `xprs.dev/in/<call>`
  loads `shell.js`, `rns.js` (reticulum-dart compiled to JavaScript) and the
  portal page, connects to a gateway by `wss://`, opens a Reticulum link to
  the station, checks its proof (`/xprs/prove`) and runs the unchanged page
  over the link (`docs/plan-browser-reticulum.md`, built since).
  `xprs.dev/in/` opens the visitor's own archivers.
- **Nothing is kept between visits.** Every visit downloads the page code
  again (`fetch(..., {cache: 'no-cache'})`): `portal.html` 124 KB, `rns.js`
  189 KB and `shell.js` 10 KB, gzipped. That is about 320 KB before a single
  message. Leaflet, pmtiles and protomaps-leaflet come from two CDNs. Files
  fetched over the link are blobs that die with the tab. Only the map tiles
  (IndexedDB, 96 MB) and a few `localStorage` values survive.
- **The chat polls over the link.** The chat tab asks
  `history?kind=message,reaction,status&limit=40` every 3 s, and other tabs
  poll at 5–60 s. None of these asks uses `since=`, so each tick downloads the
  same 40 rows again. Over Reticulum that is about 10 KB per tick, **about
  12 MB an hour** with the page open and nothing new. This is the biggest
  waste of bytes, and it is a poll where an event belongs (performance.md
  §8.31).
- **One gateway.** `in/gateways.json` lists only `wss://x3ptzm.xprs.dev/rns`.
  If xprs.dev or that server is down, nobody gets in.
- **Likes** (`t:reaction r:<id> add:like`, XPRS.md 7.5) exist:
  - on chat messages and Social statuses, as "Like ♥" in the message's ⋯
    menu, with the count shown next to the time;
  - on gallery pictures, as a heart.

  **Blog posts and forum (hosted room) posts have no like at all.** On a
  status the like is hidden behind the menu, where nobody looks for it.

## Is it possible?

Yes, and most of the hard part (Reticulum in the browser) is already built.
What is missing is ordinary web-app work:

| Wanted | How | Limits |
|---|---|---|
| Install as an app (Android, iPhone, desktop) | a web app manifest and a service worker on xprs.dev, served from `/in/` | Android/desktop Chrome and Edge offer "Install". iPhone has no prompt: Safari → Share → Add to Home Screen (iOS 16.4+), so the page shows that hint itself. |
| Start without xprs.dev | the service worker serves the shell, the page, `rns.js`, fonts and map libraries from its cache. It answers every `/in/...` address from the cache, so `/in/x3ptzm` opens even when GitHub Pages is unreachable. | xprs.dev is needed once, to install, and again only to fetch an update. |
| Not depend on one server | keep every gateway ever learned, try the last one that worked first, and learn new ones from the network | A browser can only open `wss://` with a real certificate, so a gateway is a server with a public name. The names keeper gives one to every server station (`<call>.xprs.dev`). |
| Keep the bytes | cache-first for the code, IndexedDB for the rows, files kept by their content hash, `since=` instead of re-reading | described below |

**What it cannot do:**
- **Talk to a board on its own WiFi.** The installed app is an `https://`
  page, and browsers refuse its calls to `http://192.168.4.1` (mixed content,
  Private Network Access). Next to a board with no internet, people keep using
  the board's own page, as today. The app may offer a button that opens it.
- **Run as a saved HTML file.** A page opened as a saved file (`file://`)
  cannot have a service worker, and Android barely opens local HTML. So the
  installed app is the way to run without xprs.dev. A single-file
  `xprs.html` stays a possible extra (below), not the main road.
- **Install from a station's own page.** It is plain http, and a service
  worker needs https, so a station's page cannot install the app.

The visitor's key stays where it is: the installed app has the same origin
(`xprs.dev`) as `/in/` in the browser, so it finds the key already there.

## Steps

### 1. Likes on posts (portal only, small)

- Blog cards and forum cards get the same heart button as the gallery
  (`galHeart` made generic: `likeBtn(id)`), with the count and "you like
  this".
- Chat bubbles and Social statuses show the heart in the bubble, not only in
  the ⋯ menu.
- The blog feed asks `kind=blog,reaction`. The forum and the Social feed
  already ask for reactions. One reaction table (`likes`, `myLikes`) serves
  all of them; the gallery's own copy goes.
- The like is signed in the page and goes out through `/api/xprs/send`, as
  now, so it works over HTTP and over a link alike.
- Nothing new on the wire, and no station change.
- Tests:
  - `test/feed_smoke.py`: like a blog post, unlike it, and see the count
    come back from the archive;
  - the same on a forum post.

### 2. Stop re-reading (portal, plus one small API addition)

This comes before the install work. It saves more bytes than anything else,
and it also helps people on a board's own WiFi.

- **Every repeat read asks `since=<newest ts held>`.** This covers the chat
  tick, the rooms, the blog, alerts, devices, traffic and the forum. An
  answer with nothing new is a few dozen bytes. `since` is in the API already
  (`spec/API-HTTP.md`, GET /api/xprs/history), so this part needs no station
  change.
- **Ticks follow the transport and the screen.**
  - Over a link, the chat asks every 20 s, not every 3 s.
  - A hidden tab (`document.hidden`) asks nothing.
  - A tab that is not on screen asks nothing; the per-tab intervals in
    `TAB_MS` apply only to the visible tab.
  - Coming back to the page asks once, with `since`.
- **Then the event, not the clock** (performance.md §8.31). A generic
  `wait=<s>` on `/api/xprs/history`: a station holds the ask until a row
  newer than `since` arrives, or `wait` runs out, then answers.
  - Over a link it is one pending request.
  - Over HTTP it is a long poll.
  - A station that does not know `wait` answers at once, and the page falls
    back to its slow tick.
  - The boards (single-threaded httpd) may ignore it over HTTP and honour it
    over a link, where they may already answer calls one after another.
  - Changes:
    - spec: one parameter in `API-HTTP.md`;
    - server and app: the station API wakes the waiting ask on the archive's
      own "row added" callback (core: an event in the layer that knows, no
      timer);
    - firmware: optional, later.
  - With it, an idle open chat costs one request per `wait`, for example one
    a minute instead of 1,200 an hour.

### 3. Keep what was downloaded (portal + shell)

- **Rows.** IndexedDB `xprs-rows`, one store per station callsign, keyed by
  the packet identifier, holding the row as received. On open the page draws
  from it at once, then asks `since=` the newest it holds. Rows are
  immutable, so nothing is asked twice. A cap per station (for example 20,000
  rows), oldest dropped first. This is the same pattern as the map's
  `mapKeepPut`/`mapKeepGet`, made general (`docs/reusable.md`).
- **Files.**
  - Each `/api/xprs/file/<ref>` the page fetched over a link is kept in Cache
    Storage under its ref. A ref is a content hash, so the file never goes
    stale and is never revalidated.
  - The shell's `blobFor` reads the cache before the link.
  - A size cap (for example 200 MB), least recently used out first; the map's
    96 MB stays separate.
  - Pictures shown as thumbnails keep only the thumbnail unless opened.
- **Identities, profiles, the station list.** Kept with their timestamp and
  refreshed by `since`, never re-read whole.
- **Where to reach a station.** The shell already remembers, per callsign:
  - the station's Reticulum identity and the last gateway that reached it;
  - the destination it resolved last time (which needs no new `resolve`), so
    a known station costs one path request and the link.
- **Ask not to be evicted.** `navigator.storage.persist()` on first install.
  An installed app on iPhone is exempt from Safari's 7-day clearing; a Safari
  tab is not, which is one more reason to install.

### 4. The installable app (xprs.dev)

- `in/manifest.webmanifest`:
  - name "XPRS", `start_url: /in/`, `scope: /in/`;
  - `display: standalone`;
  - the portal's colours (`#0a0a0b` background, `#ffa86a` accent);
  - icons 192 and 512 px plus a maskable one, made from the logo;
  - `shortcuts`: the last station opened.
- `in/sw.js`, the service worker:
  - **Code.** On install it pre-caches `shell.js`, `rns.js`, `portal.html`,
    `logo-font.css`, `gateways.json` and the icons, all under one version
    name. Fetches are answered from the cache first, and never revalidated
    on launch.
  - **Addresses.** Every navigation under `/in/` gets the cached shell, so
    `/in/<call>` and `/in/g/<name>` work offline from GitHub Pages; the shell
    reads the callsign from the address, as now.
  - **Map libraries.** Leaflet, pmtiles and protomaps-leaflet are copied into
    `in/lib/` (pinned versions, by `tool/sync_in.sh`) instead of the two
    CDNs. They are cached on first use. The page asks `lib/...` when it runs
    under `/in/`, and keeps the CDN on a station's own page as now.
- **Updates.**
  - At most once a day, and only when online, the worker fetches
    `in/version.json` (about 60 bytes: a hash per file).
  - Only a file whose hash changed is downloaded, in the background, and
    used at the next launch. A small "updated" note says so.
  - Nothing is re-downloaded otherwise; the 320 KB is paid once per release,
    not per visit.
  - Later, the same hashes can come over Reticulum, from the stations'
    update beacon (xprs.dev `updates/`), so even the update check stops
    needing xprs.dev.
- **The install button.**
  - Android and desktop: the page keeps `beforeinstallprompt` and shows
    "Install app" in the menu.
  - iPhone (Safari, not standalone): the menu shows "Add to Home Screen" with
    the two taps.
  - Once installed (`display-mode: standalone`), neither is shown.
- **The portal stays one page.** The manifest, the worker and the install
  menu entry belong to the xprs.dev shell. The portal shows the menu entry
  only when the shell says the page can be installed, the same way stations
  offer features as data (`page.app`). The boards' copy is unchanged.

### 5. More than one way in (spec, server, xprs.dev)

- **More gateways in `gateways.json`.** Every server station with a public
  name becomes a gateway by default (as the browser plan already said), and
  the names keeper writes the live ones into `in/gateways.json`.
- **The app keeps every gateway it has seen** in `localStorage`, tries:
  1. the last one that worked;
  2. then the rest shuffled;
  3. and only then the fetched list, if xprs.dev answers.
- **Learning gateways from the network.**
  - A gateway already says so in its `dial:` beacon. The shell asks the
    gateway it is on for the gateway beacons it holds (one more `op` on the
    control frame: `{"op":"gateways"}`, answered from beacons the gateway
    holds, each signed by its station, checked in the page).
  - So one working gateway is enough to find the others, and a list on
    xprs.dev is only the first seed.
- **Optionally, mirrors of the app on other names.** The same `/in/` files
  are served by any server station at `https://<call>.xprs.dev/in/`, so the
  app can be installed from there too. It is a different origin, so it would
  have its own key, and that has to be said on the page.

### 6. Optional: the single file

`tool/sync_in.sh` also writes `xprs.html`: the shell, `rns.js` and the
portal inlined into one file.
- Saved on a desktop, it opens from disk and connects to a gateway by
  `wss://`. The gateways must accept the `null` Origin.
- It has no service worker; its rows are kept in IndexedDB on that file's
  origin.
- A fallback for desktops and for handing the app around on a USB stick, not
  the phone road.

## Order and size

| Step | Where | Size | Station change |
|---|---|---|---|
| 1 likes | portal page | small | none |
| 2a `since`, slower and visible-only ticks | portal page | small | none |
| 2b `wait` | spec, server, app (core event), firmware later | medium | yes, generic |
| 3 rows and files kept | portal page, shell | medium | none |
| 4 manifest, worker, install, updates | xprs.dev `in/`, `sync_in.sh` | medium | none |
| 5 gateways learned | spec (one control op), server gateway, shell | small–medium | server |
| 6 single file | `sync_in.sh` | small | none |

1, 2a and 3 change nothing on the stations and save the most. After 4 the
app opens from the phone's launcher with nothing downloaded at all, and
after 5 it no longer depends on xprs.dev or on any one server.

## Tests

- **Bytes.** A headless Chromium run of `/in/<call>` against the Pi's gateway
  counts the WebSocket bytes:
  - for the first open, for an idle hour, and for a second open;
  - before and after steps 2 and 3;
  - pass: an idle open chat under 100 KB an hour, and a second open under
    10 KB plus whatever is new.
- **Offline start.** Install, cut the route to xprs.dev (but not to the
  gateway), and open `/in/` and `/in/<call>` from the launcher.
- **Update.** Change `version.json` and one file: only that file is fetched,
  and the change appears at the next launch.
- **Install.** Android Chrome: "Install app" appears and the launcher icon
  opens standalone. iPhone Safari: the hint appears, and after Add to Home
  Screen the app opens standalone and still has its key.
- The existing smoke tests still pass on the station page (the boards' copy
  must not change behaviour except fewer re-reads).
