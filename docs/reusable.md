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
- **`Cdp` in `test/layout_smoke.py`**: headless Chrome driven over the
  DevTools protocol on a pipe (fds 3 and 4), no websocket module. Use it for
  any browser test that needs device emulation or to run script in the page.
- **`pick(name)` in `test/traffic_test.js` and `test/devices_test.js`**: lifts
  one function out of the page source by brace matching, so a page function is
  unit-tested in Node without a browser.
