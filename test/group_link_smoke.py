#!/usr/bin/env python3
"""A link to a group, in a browser against a real station.

    python3 tool/build.py && python3 test/group_link_smoke.py http://127.0.0.1:8099/

The page opened with a group in its address (#g=<name or X5 callsign>, which
is what xprs.dev/in/<x5> and xprs.dev/in/g/<name> hand it) starts on that
group, followed. Checks:
  - an open group by name: opened, followed, and a visitor can write in it;
  - a group by its X5 callsign: opened, with the note that what a non-member
    writes asks to join (XPRS.md 10.3);
  - the address changing while the page is open switches the group;
  - Share link gives xprs.dev/in/<x5> for a callsign and xprs.dev/in/g/<name>
    for a name, lowercase;
  - no "Open in XPRS" on a station's own page (it is for xprs.dev), and one
    when the page was reached through xprs.dev;
  - an address that names no group opens the usual room.
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from cdp import Cdp  # noqa: E402

URL = (sys.argv[1] if len(sys.argv) > 1 else 'http://127.0.0.1:8099/').rstrip('/') + '/'
SHOTS = os.environ.get('SHOTS', '')
fails = 0


def check(ok, what, got=None):
    global fails
    print(('  [PASS] ' if ok else '  [FAIL] ') + what + ('' if ok or got is None else f'  [{got}]'))
    fails += 0 if ok else 1


def shot(c, name):
    if not SHOTS:
        return
    import base64
    d = c.send('Page.captureScreenshot', {'format': 'png'})['data']
    with open(os.path.join(SHOTS, name + '.png'), 'wb') as f:
        f.write(base64.b64decode(d))


def main():
    c = Cdp('chromium', os.path.expanduser('~/snap/chromium/common/group-link-smoke'))
    try:
        c.attach()
        c.send('Emulation.setDeviceMetricsOverride',
               {'width': 412, 'height': 860, 'deviceScaleFactor': 1, 'mobile': True})

        # An open group by name.
        c.load(URL + '#g=lisboa')
        time.sleep(4)  # past the look for an extension: the page makes a key
        check(c.eval('curRoom') == 'o:LISBOA', 'a named group in the address opens it', c.eval('curRoom'))
        check('LISBOA' in (c.eval('JSON.stringify(myGroups)') or ''), 'and follows it')
        note = c.eval("document.getElementById('msgs').innerText") or ''
        check('open group' in note.lower(), 'the page says it is an open group', note[:80])
        check(c.eval("!document.getElementById('txt').disabled") is True, 'a visitor can write in it')
        check('Share link' in note, 'Share link is offered')
        check('Open in XPRS' not in note, "no 'Open in XPRS' on a station's own page")
        check(c.eval("groupLink('LISBOA')") == 'https://xprs.dev/in/g/lisboa',
              'its link is xprs.dev/in/g/<name>', c.eval("groupLink('LISBOA')"))
        shot(c, 'group-open')

        # The address changes while the page is open: a group by its callsign.
        c.eval("location.hash='#g=X5ABCD'")
        time.sleep(1.5)
        check(c.eval('curRoom') == 'o:X5ABCD', 'the address changing switches the group', c.eval('curRoom'))
        note = c.eval("document.getElementById('msgs').innerText") or ''
        check('its members write' in note, 'a group with a callsign: anyone reads, its members write', note[:90])
        check(c.eval("document.getElementById('txt').disabled") is True,
              'a non-member has no message box there')
        check('Ask to join' in note, 'and is offered Ask to join')
        # Its folders (10.2), as the station lists them with the group.
        c.eval("groupInfo.X5ABCD=groupInfo.X5ABCD||{};groupInfo.X5ABCD.subs=[{g:'X5SUB1',name:'Recipes'}];"
               "noteSubs('X5ABCD',groupInfo.X5ABCD.subs);renderSide();drawGroupNote('X5ABCD')")
        time.sleep(0.3)
        side = c.eval("document.getElementById('side').innerText") or ''
        check('Recipes' in side, 'a folder of the group is on the list of rooms', side[-120:])
        note = c.eval("document.getElementById('msgs').innerText") or ''
        check('Recipes' in note, 'and offered inside the group')
        c.eval("switchRoom('o:X5SUB1')")
        time.sleep(1.5)
        check(c.eval('curRoom') == 'o:X5SUB1', 'a folder opens as a room of its own', c.eval('curRoom'))
        note = c.eval("document.getElementById('msgs').innerText") or ''
        check('X5ABCD' in note or 'Stop following' not in note, 'with the way back up to its group', note[:120])
        c.eval("switchRoom('o:X5ABCD')")
        time.sleep(1)
        # A member writes.
        c.eval("groupInfo.X5ABCD.role='member';drawGroupNote('X5ABCD')")
        check(c.eval("document.getElementById('txt').disabled") is False, 'a member has the message box')
        check(c.eval("groupLink('X5ABCD')") == 'https://xprs.dev/in/x5abcd',
              'its link is xprs.dev/in/<x5 callsign>', c.eval("groupLink('X5ABCD')"))
        shot(c, 'group-x5')

        # Reached through xprs.dev: the same group in the installed app.
        c.eval("window.XPRS_REMOTE={station:'X3TEST',gateway:'wss://x',group:'X5ABCD'};switchRoom(curRoom)")
        time.sleep(0.5)
        href = c.eval("(document.querySelector('a[href^=\"xprs://\"]')||{}).href") or ''
        check(href == 'xprs://in/x5abcd', "through xprs.dev: 'Open in XPRS' goes to xprs://in/<group>", href)

        # Not a group name: the usual room. From a fresh load each time (a
        # change after the # alone does not reload the page).
        c.load('about:blank', ready='true')
        c.load(URL + '#g=' + 'a' * 40)
        time.sleep(3)
        check(c.eval('curRoom') == 'local', 'an address that names no group opens the usual room', c.eval('curRoom'))
        c.load('about:blank', ready='true')
        c.load(URL)
        time.sleep(3)
        check(c.eval('curRoom') == 'local', 'no group in the address: the usual room', c.eval('curRoom'))
    finally:
        c.close()
    print('\n%d failure(s)' % fails if fails else '\nall passed')
    return 1 if fails else 0


if __name__ == '__main__':
    sys.exit(main())
