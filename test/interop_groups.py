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
ap.add_argument('--board', required=True, action='append', help='a board\'s page; repeat for several')
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
    names = ['server'] + ['board %d' % (k + 1) for k in range(len(args.board))]
    urls = [args.server] + args.board
    pages = [browser(u, 'p%d' % k) for k, u in enumerate(urls)]
    try:
        calls = [c.wait('mycall', 60 if k == 0 else 180) for k, c in enumerate(pages)]
        me = phone('GET', '/api/status').get('callsign') or ''
        print('phone %s; visitors %s; run %s' % (me, ', '.join('%s %s' % x for x in zip(names, calls)), T))
        if not check(all(calls), 'every visitor has a key'):
            return
        for c in pages:
            c.eval("sendIdentity()")

        def reads(c, text):
            return until(lambda: c.eval("loadGroup(),1") and shows(c, text))

        print('1. open group LISBOA')
        try:
            phone('POST', '/api/xprs/group/follow', {'d': 'LISBOA'})
        except Exception:
            pass
        for c, n in zip(pages, names):
            check(follow(c, 'LISBOA'), 'the %s visitor follows LISBOA' % n)
        phone('POST', '/api/xprs/send', {'type': 'message', 'd': 'LISBOA', 'm': 'phone ' + T, 'private': False})
        for c, n in zip(pages, names):
            check(reads(c, 'phone ' + T), 'the %s visitor reads the phone\'s post' % n)
        for k, (c, n) in enumerate(zip(pages, names)):
            text = '%s says %s' % (n, T)
            post(c, text)
            check(until(lambda: phone_has('LISBOA', text)), 'the phone reads the %s visitor\'s post' % n)
            for c2, n2 in zip(pages, names):
                if c2 is not c:
                    check(reads(c2, text), 'the %s visitor reads the %s visitor\'s post' % (n2, n))
        for c, n in zip(pages, names):
            shot(c, 'interop_open_' + n.replace(' ', ''))

        print('2. a closed group made on the phone')
        g = phone('POST', '/api/xprs/group/create', {'nick': 'Interop ' + T}).get('group')
        check(bool(g), 'the phone makes a group: %s' % g)
        r = phone('POST', '/api/xprs/group/grant', {'d': g, 'calls': ','.join(calls)})
        check(r.get('ok'), 'the phone invites every visitor')
        for c, n in zip(pages, names):
            follow(c, g)
            c.eval("delete groupInfo[%s]" % json.dumps(g))
            ok = until(lambda: c.eval("(groupInfo[%s]||{}).askedAt=0,loadGroup(),1" % json.dumps(g)) and c.eval(
                "!!(groupInfo[%s]&&groupInfo[%s].role==='invited'&&groupInfo[%s].offer)"
                % (json.dumps(g), json.dumps(g), json.dumps(g))))
            check(ok, 'the %s visitor finds the invitation' % n)
            shot(c, 'interop_invited_' + n.replace(' ', ''))
            c.eval("acceptGroup(%s)" % json.dumps(g))

        def members():
            j = phone('GET', '/api/xprs/group', q={'d': g})
            roles = j.get('roles') or {}
            return all(roles.get(x) == 'member' for x in calls) and j
        j = until(members)
        check(bool(j), 'the phone\'s record has every visitor as a member')
        if not j:
            print('   phone record:', json.dumps(phone('GET', '/api/xprs/group', q={'d': g}))[:600])
        phone('POST', '/api/xprs/send', {'type': 'message', 'd': g, 'm': 'admin ' + T, 'private': False})
        for c, n in zip(pages, names):
            check(reads(c, 'admin ' + T), 'the %s member reads the phone\'s post in the group' % n)
        for c, n in zip(pages, names):
            text = 'member on %s %s' % (n, T)
            post(c, text)
            check(until(lambda: phone_has(g, text)), 'the phone reads the %s member\'s post' % n)
            for c2, n2 in zip(pages, names):
                if c2 is not c:
                    check(reads(c2, text), 'the %s member reads the %s member\'s post' % (n2, n))
        for c, n in zip(pages, names):
            shot(c, 'interop_group_' + n.replace(' ', ''))
        print('   group %s' % g)
    finally:
        for c in pages:
            c.close()
    print('FAILED' if fails else 'all passed')
    sys.exit(1 if fails else 0)


main()
