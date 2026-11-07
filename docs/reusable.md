# Reusable pieces in the web chat

- **`wireId(w)`** (`page/chat_page.html`): the XPRS.md 5 identifier in the
  browser, `via:` and `sig:` left out. Use it wherever two rows may be copies of
  one packet: chat bubbles and the Traffic merge both key on it.
- **`trafficGroups(rows)`**: folds history rows into one entry per packet with
  a tag per direction (`sent`/`heard`) and bearer, the loudest RSSI per tag and
  a copy count. Any list of archive rows that should read as packets rather
  than copies can reuse it.
- **`backfillRooms()`**: asks a list of `/api/xprs/history` questions one after
  another on the shared `getJSON`, never in parallel, because a board has one
  HTTP worker. Reuse the chained shape for any one-off series of reads.
- **`headField(w, key)`**: one value from a wire's head (before `m:`), or
  `''`. Use it instead of a fresh regex wherever the page reads a field off a
  packet.
- **`blogPosts(rows)`**: folds history rows of one type into publications:
  joins split parts keyed on `(f, ts)` (6.6), drops a set with a hole, keeps
  the newest edition per author and `title:` (18.1). Events (26) replace by
  title the same way, so an Events feed would reuse it with `t:event`.
- **`splitSigned(head, text, cb)`**: a long text as up to nine packets split
  at spaces (7.6), signed once over the whole with the signature on the last
  part (9.1.1), or one signed packet when it fits. The forum uses it for
  topics and comments; the chat composer could use it for a long message
  instead of refusing one. `postWires()` sends them one after another.
- **`slugOf(text)`**: a label (18.1) from free text.
- **`distCell(v)`**: the Distance cell for a devices row -- the sum when the
  station could add the legs up, the first leg as a floor (`>~12 m`) when the
  relay has not said, the relay's name beside it. Anything that prints a
  device's distance (a map popup, the station panel) should call it.
- **`park()` with the `html`/`body` rule**: keeps the document scrolled one
  pixel so Android's captive-portal WebView (a swipe-to-refresh layout round
  it) does not reload the page on a scroll-up inside a panel. Any page of ours
  that scrolls in panels rather than the document, served to a phone over a
  hotspot, needs the same three lines.
- **`fit()` with the `--sa*`, `--lay-h` and `--cut` properties**: a full-height
  page that never scrolls has to end where the visitor can see, and on
  Android that is not `100%`. It asks for safe-area insets
  (`viewport-fit=cover`), cuts off what a toolbar lying over the page covers
  (window height minus the visual viewport), and guesses the Android bars for
  a WebView drawn under them that reports no inset (page as tall as the
  screen). Goes with `park()`; any phone-sized page of ours wants both.
- **`Cdp` in `test/cdp.py`**: headless Chrome driven over the DevTools
  protocol on a pipe (fds 3 and 4), no websocket module: `attach()` a page,
  `load(url)`, `eval(js)`, `wait(js, seconds)` polls until truthy. Used by
  `layout_smoke.py` (device emulation) and `feed_smoke.py` (clicking through
  the feeds); any browser test that runs script in the page starts here.
- **`test/shots.py`**: screenshots of every feed and panel (desktop, phone,
  landscape) against the mock, claimed as administrator, into a directory:
  the way to look at a change before deciding it looks right.
- **The palette on `:root`** (`--panel`, `--field`, `--line`, `--dim`,
  `--on-accent`, `--own`, `--banner`, `--hover`, `--accent-soft`, `--radius`
  beside the five colours): no grey is written twice in the stylesheet, so a
  theme is one `:root` block. New CSS uses these, never a literal grey.
- **`THEMES` with `themeChips()` / `pickTheme()`**: a named CSS preset is a
  chip with a three-colour swatch; picking previews and fills the stylesheet.
  A seventh theme is one more entry.
- **`page_<name>` settings** (`applyCss()`, `applyLogo()`, `drawBanner()`):
  anything the page lets the administrator set about itself is a string the
  station stores under `page_<name>` and reports as `page.<name>`, with no
  station-side meaning. A new one is a textarea in Administration, a line in
  `applyServices()` and a line in `adminSet()`; nothing on the server.
- **`fabSet(mode)` / `fabClick()` / `closeComposer()`**: the round + of a
  feed and the panel it opens at the top of the conversation column. A feed's
  loader redraws only while no `#composer` is open, so a new feed with
  something to add gets a mode, a form function, and that one guard.
- **`roomCreateFrom(prefix, kind, done)`**: creates a station room from any
  form whose fields are `prefix+name/about/vis/post`: the admin's New room
  and the Forum's category panel share it; a third form would too.
- **`splitSigned(head, text, cb)` and `postWires(wires, i, cb)`**: a long
  packet as parts (7.6) signed once over the whole (9.1.1), posted one after
  another. A forum topic, a reply and a post to everybody all go through them;
  so would anything else the page lets a visitor write at length.
- **`pick(name)` in `test/traffic_test.js` and `test/devices_test.js`**: lifts
  one function out of the page source by brace matching, so a page function is
  unit-tested in Node without a browser.
- **`meshPanel()` with `meshRoom()`**: a closed group's roster run from the
  page through `/api/rooms` (create, mirror, add, appoint, remove, accept,
  unmirror). Anything else whose membership is a set of stations, signed and
  spread, can be the same: a room of its own kind and this panel's actions.
