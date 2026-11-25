# Reusable pieces in the web chat

- **`stGet(k)` / `stSet(k, v)`**: the page's storage, `localStorage` first;
  a cookie only where `localStorage` cannot keep the value (captive WebViews),
  and a leftover cookie dropped, because a cookie goes to the server with every
  request and `xprs_nsec` is the secret key. Store anything the page keeps
  through them, never `document.cookie` directly.
- **Accounts (`accList` / `accEntry` / `accSet` / `accHold`)**: several
  identities kept in this browser (`xprs_accounts`), the one in use still in
  `xprs_nsec` / `xprs_ext`; each carries its archivers (`hold`). Anything kept
  per person (not per browser) goes on the account entry through `accSet`.
- **`declareHold(list)`**: the signed `t:mailbox hold:<list> until:+30d`
  (XPRS.md 9.12), handed to this station and to each archiver in the list.
- **Other stations (`remote()`, `remoteSession(c)`, `remotePost(c, wire)`,
  `remoteEach(fn)`)**: where the page can reach more than its own station
  (xprs.dev's `window.XPRS_REMOTE`), a session on another station, a wire
  posted there with our identity first, and a loop over this account's
  archivers. Anything that must reach every archiver (mail, receipts) uses them.
- **Finding stations (`mapFilter`, `mapMatch`, `mapChips`, `mapTagsOf`)**:
  search, an area and filters built from what stations announce in
  `t:service` (`serve:`, `source:`), freshest first, 50 at a time. A new
  criterion is a new tag from the same announcement, not new code.
- **`mapMerge(rows)` / `mapBack(page, n)` / `mapLookup(call)`**: the map's rows
  as one newest-first set, older pages read with history's `until`, and a
  callsign asked for by name.
- **`mapPos(p)` / `mapStations(rows)`**: `pos:` as XPRS.md 15.1 reads it
  (redaction bars: the middle of the square, with `box` and `range`), and
  history rows folded into one entry per station (place, key, nick,
  `archive` from `t:service serve:`). The Map view draws them; anything that
  lists stations reuses them.
- **`groupFromAddress()` / `dmFromAddress()`**: what the address asks to open,
  `#g=<group>` or `#dm=<callsign>`. A link that should land on one
  conversation (the xprs.dev map's Message, a shared link) uses these forms.

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
- **`page/xprs_md.js`**: formatted text (XPRS.md 4.11) with no dependency
  but `sha256`/`b64uEnc`. `mdRender(text, {img, file, mention})` escapes first
  and reads the subset; the hooks draw references and callsigns, so any feed
  (a status, an event's description) can render it the same way.
  `mdToWire`/`mdFromWire` turn composer newlines into U+2028/U+2029 and back;
  `isRef`/`isImageRef`/`mdRefs` check and list content references;
  `refOf(bytes, ext)` is a file's reference in the browser.
- **`splitParts(head, text)`**: the arithmetic of `splitSigned` alone,
  `{parts|null, count, per, why}`. A composer's live "N of 9 packets" counter
  calls it so it can never disagree with what is sent.
- **`pendingPost(post, head, wires)`** with `pendFor`/`pendPrune`/`pendPills`:
  the visitor's own publication shown at once, sending, published or refused
  with Retry, until history returns the same section 5 identifier. Kept in
  localStorage only (never the cookie). Anything else that is posted and then
  read back from the archive (an alert, an event) should use it rather than
  waiting for the archive's next write.
- **`mdEditor(prefix, placeholder)`** with `mdLive`/`mdWrap`/`mdInsert`/
  `mdAttach`/`mdBusy`: the raw text beside its preview, a toolbar, the packet
  counter and the image button (shrunk to 1600 px, hashed, shown from a blob
  URL, stored with `mdUpload`). Used by the Blog and the forum's topic form;
  the ids it makes are `<prefix>-text`, `-prev`, `-count`, `-file`, and the
  form supplies `<prefix>-title`, `<prefix>-go` and a head function.
- **`mdImgHtml`/`mdFileHtml`/`mdPh`**: a reference drawn from the station
  (`/api/xprs/file/<ref>`) with a placeholder when it is not held, tap to try
  again.

## Collections: Gallery, Music, Library (page/chat_page.html, `GAL_KINDS`)

One module serves the three. Everything a kind changes is one entry of
`GAL_KINDS` (names, accepted files, grid or list, whether items carry a
preview); the data path is shared: `galTree` builds folders/items/files/likes
from the room's history, `galUpload` does preview → streamed file → item →
`t:file` for any kind, `galPut`/`galRefOf` upload and hash a file of any size
without holding it (`sha256Init/Update/Final` in xprs_crypto.js),
`galHeart`/`galLike` the likes, `fileIcon(ref)` a typed file icon (SVG, by
extension in `GAL_ICONS`), `galCover(name,glyph)` a deterministic cover where
there is no picture, `galView` the full-screen viewer, `galPlayerBar`/`galPlay`
the music player. A fourth kind is one `GAL_KINDS` entry plus its view branch.

`tool/seed_collections.py` fills a station's collections from a manifest
through the page itself (headless Chromium), signing with a given signer
(`xprs-server sign`): demo content, or a migration.

## Groups with a callsign (2026-11-22)

- `noteSubs(g, subs)` / `groupUp` / `groupTree(g, depth)`: the folders of a
  group (XPRS.md 10.2) from the station's `group.subs`, drawn on the list of
  rooms and inside the group. A folder is a room `o:<callsign>` and needs no
  following.
- `askToJoin(g)` / `joinAsked(g)`: a non-member's one request a day; the
  message box of a group with a callsign opens only for a member
  (`drawGroupNote`). Use the same pair wherever writing needs admission.

## A room's head and the message box (2026-11-23)

- `IC.share` / `IC.open` / `IC.star` / `IC.staron` / `IC.folder`: inline SVG
  icons, drawn in the text colour. Use these (and add to the set) instead of
  emoji, which come out as empty boxes on a device without the font.
- `.icb`: a square icon button (38 px, `.on` when active); `.grpsec`: a small
  section heading with a rule; `.grpfolds` / `.grpfold`: a grid of rows that
  each open something. The group head (`drawGroupNote`) is built from them
  and any other "title, actions, list of places" head should be too.
- The message box hides itself wherever it is disabled: setting
  `el('txt').disabled` is the one switch (hooked once, beside `snack`). Never
  leave a disabled box on the page with an explanation in its placeholder.
- `shutBar(html)`: what stands where the box would be when nobody may write
  but there is something to do instead (Ask to join, Join an invitation).
  `switchRoom` clears it; an empty string hides it.
- `groupOpenHere(g)`: is the room being read inside group `g`? The list of
  rooms shows a group's folders only then.
- `groupCount(g)` / `groupNew(g)` / `groupSeenSet(g, n)`: a room's held
  message count from the station (`n` in the group record and in each of its
  `subs`) and what is new since this browser last had it open, shown as
  "1276 (+24)" with the addition in green (`.gcnt b`, `.gnew`). The "seen"
  number lives in the browser (`xprs_gseen`); the station keeps nothing per
  visitor. Reuse for any list of rooms that should show unread counts.
- `nostrQueue(fn)` (`page/xprs_nostr.js`): every call to a NOSTR extension
  (`signEvent`, `nip04`) goes through it, one at a time; `fn(done)` calls
  `done()` when the extension answered. nos2x shows a popup per request and
  can deny a queued one when the previous popup closes. Any new `window.nostr`
  call belongs in it.
- `noticed{}` + `openedAt` (beep): a message beeps only the first time this
  page sees it and only if sent after the page opened; rooms drawn again on
  switching stay quiet. Reuse for any "new since you came" signal.
- `daysStuck()`: among sticky separators that share one scroll box, only the
  newest stuck one shows. Reuse for any other sticky headers in a list.
- `navHere()` / `navCheck()` / `navRestore(s)` (Back goes back a section):
  every place a tap leads to is one history entry (address unchanged), open
  overlays (menu, side list, picture viewer) included so Back closes them
  first. A new place or overlay only needs its state added to `navHere()` and
  its way back to `navRestore()`; taps are picked up on their own.
- **`look(what)` / `lookDone()` / `lookState(room)` / `roomAnswered(room)`**
  with the `.messages[data-look]` and `[data-none]` rules: what a section
  says while it has nothing to show. `look('posts')` writes "Looking for
  posts…" until the answer is drawn (`lookDone()`); a conversation says "No
  messages here yet" only once its own history came (`roomAnswered()`).
  Anything new that fills `#msgs` from a request calls `look()` when it
  clears the column and `lookDone()` where it draws, and never prints an
  empty note before the station answered. `svcKnown`, `roomsLoaded`,
  `alertsLoaded` and `blogLoaded` say which first answers have come.
- **Held answers in `test/look_smoke.py`**: `getJSON` wrapped in the page so
  every answer waits for `release()`. A slow link made exact, for testing
  what the page shows between asking and being answered.
- **`posBarred(lat, lon, rangeM)` with `mapPos(pos)`**: a place written as
  a station airs it (XPRS.md 6.2.1, the core's `xprsPosAuthored`): the
  digits past the range barred, `49█████,8█████` at 100 km; `mapPos` reads
  it back to the middle of its square. `test/place_test.js` holds both to
  the core's worked values. Anything in the page that shows or previews a
  station's place uses these, never a rounding of its own.
- **`canSwitch()` / `useBtn(c)` / `mapUse(s)` / `baseSwitch(c)`**: another
  archiver as the page's base, where the shell can make one
  (`XPRS_REMOTE.use`, xprs.dev only): `useBtn` is the Visit button for any
  list of archivers, `mapUse` the popup's, `baseSwitch` keeps the map's view
  (`mapViewKept()` reads it back once, in `mapInit`) and opens the portal on
  it. `test/base_switch_test.js`; the page half end to end in
  `test/accounts_smoke.py`.
- **`profileArchivers(j, done)` / `holdersOf(j)` / `profileAround(done)`**:
  the person's archivers as the network knows them (their signed
  `t:mailbox hold:`, XPRS.md 9.12, passed between archivers 12.9.5), like a
  NOSTR relay list: a session reply's `holders` is the account's list, this
  browser's copy only a cache; where the station knows none, the other
  archivers in reach are asked before anything is declared. `done(list,
  adopted)`: an adopted list is never re-signed by the page.
  `test/profile_test.js`; a new browser end to end in
  `test/accounts_smoke.py` (`/__mailbox` on the mock seeds what a station
  learned from its peers).
- **`mapTagOne(t)` / `mapTagName(t)`**: what a station announces
  (`serve:archive`...), named for ONE station (a popup: "Archiver") or for
  a group of them (a filter chip: "Archivers").
