#!/usr/bin/env python3
"""Groups across a phone, a Linux server and an ESP32 board, with people in
browsers on the server and on the board.

    python3 test/interop_groups.py --server http://127.0.0.1/ \
        --board http://192.168.178.102/ --phone http://127.0.0.1:3458/

--phone is the phone's remote API (Settings > Remote control API, then
`adb forward tcp:3458 tcp:3456`). The phone takes part through the same core
its Chat app uses: it posts, creates a group, invites and reads history.

  1. An open group (XPRS.md 7.3): each of the three writes to it and the
     other two read it.
  2. A closed group (section 10) made on the phone: it invites the two
     browser visitors; each finds the invitation on their station and joins
     with their own signature; each posts and the phone and the other
     visitor read it; the phone's record shows both as members.
"""
import argparse
import json
import os
import sys
import time
import urllib.parse
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from cdp import Cdp  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument('--server', required=True)
ap.add_argument('--board', required=True)
ap.add_argument('--phone', required=True)
ap.add_argument('--wait', type=float, default=120, help='seconds to wait for a packet to cross')
ap.add_argument('--shots', default=os.environ.get('SHOTS', ''))
args = ap.parse_args()
T = time.strftime('%H%M%S')
fails = 0


def check(ok, what):
    global fails
    print(('  [PASS] ' if ok else '  [FAIL] ') + what, flush=True)
    fails += 0 if ok else 1
    return ok


def phone(method, path, body=None, q=None):
    url = args.phone.rstrip('/') + path + ('?' + urllib.parse.urlencode(q) if q else '')
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method,
                                 headers={'Content-Type': 'application/json'})
    return json.loads(urllib.request.urlopen(req, timeout=20).read())


def phone_has(dest, text):
    r = phone('GET', '/api/xprs/history', q={'to': dest, 'limit': 100})
    rows = r.get('rows', r if isinstance(r, list) else [])
    return any(text in (x.get('wire') or '') or text in (x.get('m') or '') for x in rows)


def until(fn, secs=None):
    end = time.time() + (secs or args.wait)
    while time.time() < end:
        try:
            v = fn()
            if v:
                return v
        except Exception:
            pass
        time.sleep(3)
    return None


def shot(c, name):
    if not args.shots:
        return
    import base64
    d = c.send('Page.captureScreenshot', {'format': 'png'})['data']
    with open(os.path.join(args.shots, name + '.png'), 'wb') as f:
        f.write(base64.b64decode(d))


def browser(url, prof):
    c = Cdp('chromium', os.path.expanduser('~/snap/chromium/common/interop-' + prof))
    c.attach()
    c.send('Emulation.setDeviceMetricsOverride',
           {'width': 412, 'height': 860, 'deviceScaleFactor': 1, 'mobile': True})
    # A board serves the page slowly (seconds over its Wi-Fi): wait for the
    # page and its key, not for a fixed time.
    c.send('Page.navigate', {'url': url})
    c.wait("document.readyState==='complete'&&!!document.getElementById('txt')", 60)
    return c


def follow(c, g):
    c.eval("window.prompt=function(){return %s};(switchRoom('onew'),1)" % json.dumps(g))
    return c.wait("curRoom==='o:'+%s" % json.dumps(g), 5)


def post(c, text):
    c.eval("el('txt').disabled=false;el('txt').value=%s;sendMsg()" % json.dumps(text))


def shows(c, text):
    return c.eval("document.getElementById('msgs').innerText.indexOf(%s)>=0" % json.dumps(text))


def main():
    s = browser(args.server, 's')
    b = browser(args.board, 'b')
    try:
        sc, bc = s.wait('mycall', 60), b.wait('mycall', 180)
        if not check(bool(sc and bc), 'both visitors have keys'):
            return
        me = phone('GET', '/api/status').get('callsign') or ''
        print('visitors: server %s, board %s; phone %s; run %s' % (sc, bc, me, T))
        # Each visitor's identity goes out, so the phone can verify them.
        for c in (s, b):
            c.eval("sendIdentity()")

        print('1. open group LISBOA')
        # The phone follows it, as its Chat does when its owner opens the room
        # (an older phone build has no such call: open #LISBOA in Chat first).
        try:
            phone('POST', '/api/xprs/group/follow', {'d': 'LISBOA'})
        except Exception:
            pass
        for c in (s, b):
            check(follow(c, 'LISBOA'), 'a browser follows LISBOA')
        phone('POST', '/api/xprs/send', {'type': 'message', 'd': 'LISBOA', 'm': 'phone ' + T, 'private': False})
        check(until(lambda: s.eval("loadGroup(),1") and shows(s, 'phone ' + T)),
              'the server\'s visitor reads the phone\'s post')
        check(until(lambda: b.eval("loadGroup(),1") and shows(b, 'phone ' + T)),
              'the board\'s visitor reads the phone\'s post')
        post(s, 'server ' + T)
        check(until(lambda: phone_has('LISBOA', 'server ' + T)), 'the phone reads the server visitor\'s post')
        check(until(lambda: b.eval("loadGroup(),1") and shows(b, 'server ' + T)),
              'the board\'s visitor reads it too')
        post(b, 'board ' + T)
        check(until(lambda: phone_has('LISBOA', 'board ' + T)), 'the phone reads the board visitor\'s post')
        check(until(lambda: s.eval("loadGroup(),1") and shows(s, 'board ' + T)),
              'the server\'s visitor reads it too')
        shot(s, 'interop_open_server')
        shot(b, 'interop_open_board')

        print('2. a closed group made on the phone')
        g = phone('POST', '/api/xprs/group/create', {'nick': 'Interop ' + T}).get('group')
        check(bool(g), 'the phone makes a group: %s' % g)
        r = phone('POST', '/api/xprs/group/grant', {'d': g, 'calls': '%s,%s' % (sc, bc)})
        check(r.get('ok'), 'the phone invites both visitors')
        for c, who in ((s, 'server'), (b, 'board')):
            follow(c, g)
            c.eval("delete groupInfo[%s]" % json.dumps(g))
            ok = until(lambda: c.eval("(groupInfo[%s]||{}).askedAt=0,loadGroup(),1" % json.dumps(g)) and c.eval(
                "!!(groupInfo[%s]&&groupInfo[%s].role==='invited'&&groupInfo[%s].offer)"
                % (json.dumps(g), json.dumps(g), json.dumps(g))))
            check(ok, 'the %s\'s visitor finds the invitation' % who)
            shot(c, 'interop_invited_' + who)
            c.eval("acceptGroup(%s)" % json.dumps(g))
        def members():
            j = phone('GET', '/api/xprs/group', q={'d': g})
            roles = j.get('roles') or {}
            return roles.get(sc) == 'member' and roles.get(bc) == 'member' and j
        j = until(members)
        check(bool(j), 'the phone\'s record has both as members')
        if not j:
            print('   phone record:', json.dumps(phone('GET', '/api/xprs/group', q={'d': g}))[:600])
        post(s, 'member on server ' + T)
        check(until(lambda: phone_has(g, 'member on server ' + T)), 'the phone reads the server member\'s post')
        post(b, 'member on board ' + T)
        check(until(lambda: phone_has(g, 'member on board ' + T)), 'the phone reads the board member\'s post')
        phone('POST', '/api/xprs/send', {'type': 'message', 'd': g, 'm': 'admin ' + T, 'private': False})
        check(until(lambda: s.eval("loadGroup(),1") and shows(s, 'admin ' + T)),
              'the server\'s member reads the phone\'s post in the group')
        check(until(lambda: b.eval("loadGroup(),1") and shows(b, 'admin ' + T)),
              'the board\'s member reads it')
        check(until(lambda: s.eval("loadGroup(),1") and shows(s, 'member on board ' + T)),
              'the server\'s member reads the board member\'s post')
        shot(s, 'interop_group_server')
        shot(b, 'interop_group_board')
    finally:
        s.close()
        b.close()
    print('FAILED' if fails else 'all passed')
    sys.exit(1 if fails else 0)


main()
