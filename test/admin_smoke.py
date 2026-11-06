#!/usr/bin/env python3
"""The menu and the Administration view, in headless Chromium, against the mock.

    python3 tool/build.py && /usr/bin/python3 test/admin_smoke.py

  - the menu is grouped (your identity / this station / this page) and closes
    on a click anywhere outside it;
  - a station with no administrator lets the visitor claim it, then shows the
    settings, which reach the station when changed;
  - from the internet (MOCK_REMOTE) the claim is not offered.
"""
import asyncio
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.request

import websockets

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROF = os.path.expanduser('~/snap/chromium/common/webchat-admin-prof')
CDP = 9468
fails = 0


def check(ok, what):
    global fails
    print(('  [PASS] ' if ok else '  [FAIL] ') + what)
    fails += 0 if ok else 1


async def run(port, remote):
    env = dict(os.environ)
    if remote:
        env['MOCK_REMOTE'] = '1'
    mock = subprocess.Popen([sys.executable, os.path.join(ROOT, 'contract', 'mock_station.py'),
                             str(port)], env=env)
    shutil.rmtree(PROF, ignore_errors=True)
    os.makedirs(PROF, exist_ok=True)
    chrome = subprocess.Popen(['chromium', '--headless=new', '--no-sandbox', '--disable-gpu',
                               '--user-data-dir=' + PROF, '--remote-debugging-port=%d' % CDP,
                               'about:blank'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        ws_url = None
        for _ in range(60):
            time.sleep(0.5)
            try:
                tabs = json.load(urllib.request.urlopen('http://127.0.0.1:%d/json' % CDP))
                ws_url = next(t['webSocketDebuggerUrl'] for t in tabs if t['type'] == 'page')
                break
            except Exception:
                pass
        async with websockets.connect(ws_url, max_size=None) as ws:
            n = 0

            async def send(method, params=None):
                nonlocal n
                n += 1
                await ws.send(json.dumps({'id': n, 'method': method, 'params': params or {}}))
                while True:
                    m = json.loads(await ws.recv())
                    if m.get('id') == n:
                        return m.get('result', {})

            async def ev(js):
                r = await send('Runtime.evaluate', {'expression': js, 'awaitPromise': True,
                                                   'returnByValue': True})
                return r.get('result', {}).get('value')

            async def click(sel):
                # A real click at the element's centre, as a finger would.
                box = await ev("(function(){var r=document.querySelector(%s)"
                               ".getBoundingClientRect();return [r.x+r.width/2,r.y+r.height/2];})()"
                               % json.dumps(sel))
                for t in ('mousePressed', 'mouseReleased'):
                    await send('Input.dispatchMouseEvent', {'type': t, 'x': box[0], 'y': box[1],
                                                            'button': 'left', 'clickCount': 1})

            await send('Page.enable')
            await send('Page.navigate', {'url': 'http://127.0.0.1:%d/' % port})
            await asyncio.sleep(5)  # past the 3 s look for an extension: a key is made
            is_open = "document.getElementById('menu').className.indexOf('open')>=0"
            if not remote:
                secs = await ev("[].map.call(document.querySelectorAll('#menu .menu-sec'),"
                                "function(e){return e.textContent})")
                check(secs == ['Your identity', 'This station', 'This page'],
                      'the menu is grouped: %s' % secs)
                await click('.menu-btn')
                check(await ev(is_open), 'the menu opens')
                await click('#msgs')
                check(not await ev(is_open), 'a click outside closes it')
                await click('.menu-btn')
                await ev("(document.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape'})),1)")
                check(not await ev(is_open), 'and so does Escape')
                await click('.menu-btn')
                await asyncio.sleep(0.4)  # the drawer slides in
                await click('#adminbtn')
                check(not await ev(is_open), 'choosing an item closes it too')
            else:
                await ev("(openView('admin'),1)")
            await asyncio.sleep(3)
            text = await ev("document.getElementById('v-admin').innerText") or ''
            if remote:
                check('only from its own network' in text and
                      not await ev("!!document.getElementById('ad-claim')"),
                      'from the internet the claim is not offered')
                await ev("(switchRoom('alerts'),1)")
                await asyncio.sleep(2)
                check('power cut' in (await ev("document.getElementById('msgs').innerText") or '')
                      and await ev("getComputedStyle(document.getElementById('fab')).display") == 'none',
                      'a visitor sees the alerts feed and, by default, no + to post one')
                return
            check('none yet' in text and await ev("!!document.getElementById('ad-claim')"),
                  'a station with no administrator offers the claim')
            await click('#ad-claim')
            await asyncio.sleep(2)
            me = await ev("mycall")
            st = json.loads(urllib.request.urlopen(urllib.request.Request(
                'http://127.0.0.1:%d/__admin' % port, method='POST', data=b'{}')).read())
            check(st['admin'] == me, 'claimed: the station names %s as administrator' % me)
            check(await ev("!!document.getElementById('ad-lp')"), 'and the settings appear')
            await click('#ad-lp')
            await click('input[name="ad-who"][value="local"]')
            await asyncio.sleep(2)
            st = json.loads(urllib.request.urlopen(urllib.request.Request(
                'http://127.0.0.1:%d/__admin' % port, method='POST', data=b'{}')).read())
            got = {k: st['settings'].get(k) for k in ('local_private', 'who_may_post', 'who_may_alert')}
            check(got == {'local_private': False, 'who_may_post': 'local', 'who_may_alert': 'moderators'},
                  'changed settings reach the station: %s' % st['settings'])

            # Moderation (XPRS.md 10.10).
            def station():
                return json.loads(urllib.request.urlopen(urllib.request.Request(
                    'http://127.0.0.1:%d/__admin' % port, method='POST', data=b'{}')).read())
            check(station()['roles'].get(me) == 'mod',
                  'claiming also accepted the moderator role, signed in the page')
            await ev("(window.confirm=function(){return true},1)")
            await ev("(showTab('chat'),1)")
            await asyncio.sleep(3)
            bubbles = "document.querySelectorAll('#msgs .msg[data-from=\"X1ARKL\"]').length"
            check(await ev(bubbles) == 1, 'a visitor\'s message is shown')
            await click('#msgs .msg[data-from="X1ARKL"] .dots')
            items = await ev("document.getElementById('msgmenu').innerText") or ''
            check('Delete for everyone' in items and 'away until lifted' in items,
                  'a moderator\'s message menu offers delete and send away')
            await ev("(menuAct('mdel',document.querySelector('#msgs .msg[data-from=\"X1ARKL\"]')"
                     ".getAttribute('data-id'),'X1ARKL'),1)")
            await asyncio.sleep(2)
            w = [x for x in json.load(urllib.request.urlopen('http://127.0.0.1:%d/__sent' % port))
                 if x.startswith('t:moderate')]
            check(any(' d:X3MOCK ' in x and ' remove:message' in x and ' sig:' in x for x in w),
                  'the deletion is a signed t:moderate ... r:<id> remove:message to the station')
            check(await ev(bubbles) == 0, 'and the message leaves the page')
            await ev("(modSendAway('X1SPAM',0),1)")
            await asyncio.sleep(2)
            check(station()['away'] == ['X1SPAM'], 'sending somebody away reaches the station')
            await ev("(showTab('admin'),1)")
            await asyncio.sleep(2)
            text = (await ev("document.getElementById('v-admin').textContent") or '').lower()
            check('sent away' in text and 'x1spam' in text and 'moderators' in text,
                  'Administration lists moderators and the people sent away')
            await ev("(adminDo('lift',{call:'X1SPAM'}),1)")
            await ev("(document.getElementById('ad-newmod')||{}).value='X1BOBB'")
            await asyncio.sleep(1)
            await ev("(document.getElementById('ad-newmod').value='X1BOBB',adminAppoint(),1)")
            await asyncio.sleep(2)
            st = station()
            check(st['away'] == [] and st['roles'].get('X1BOBB') == 'invited',
                  'the administrator lifts and appoints')

            # Rooms the station hosts (XPRS.md 10.10.1).
            await ev("(document.getElementById('rn-name').value='Block C',"
                     "document.getElementById('rn-about').value='residents',"
                     "document.getElementById('rn-post').value='members',roomCreate(),1)")
            await asyncio.sleep(3)
            st = station()
            check(list(st['rooms']) == ['X5R001'] and st['rooms']['X5R001']['posting'] == 'members',
                  'the administrator creates a room: %s' % st['rooms'])
            check(st['room_roles'].get('X5R001 ' + me) == 'mod',
                  'and accepted its moderator role, signed in the page')
            side = await ev("document.getElementById('side').textContent") or ''
            check('Station rooms' in side and 'Block C' in side, 'the room is in the sidebar')
            await ev("(roomDo===roomDo&&(document.getElementById('rm-X5R001').value='X1BOBB'),roomDo('add','X5R001'),1)")
            await asyncio.sleep(2)
            check(station()['room_roles'].get('X5R001 X1BOBB') == 'invited', 'a member is invited')
            await ev("(showTab('chat'),switchRoom('g:X5R001'),1)")
            await asyncio.sleep(1)
            await ev("(document.getElementById('txt').value='hello room',sendMsg(),1)")
            await asyncio.sleep(2)
            sent = json.load(urllib.request.urlopen('http://127.0.0.1:%d/__sent' % port))
            check(any(x.startswith('t:message') and ' d:X5R001 ' in x and 'hello room' in x for x in sent),
                  'a message in the room is addressed to it (d:X5R001)')
            check(await ev("document.querySelectorAll('#msgs .msg').length") == 1,
                  'and is shown in the room')
            await ev("(roomPost({action:'update',call:'X5R001',visibility:'private'}),1)")
            await asyncio.sleep(2)
            check(station()['rooms']['X5R001']['visibility'] == 'private', 'the room can be made private')

            # Alerts (XPRS.md 10.10.2).
            await ev("(alertsSeen={},pollAlerts(),1)")
            await asyncio.sleep(2)
            label = await ev("document.getElementById('alertsroom').textContent") or ''
            check('(1)' in label, 'the Feed entry says Alerts (1) while an alert is unread: %r' % label)
            check(await ev("document.querySelectorAll('#tabs [data-tab=alerts]').length") == 0,
                  'and there is no Alerts tab')
            await ev("(switchRoom('alerts'),1)")
            await asyncio.sleep(2)
            text = await ev("document.getElementById('msgs').innerText") or ''
            check('power cut' in text, 'opening it lists the active alert in the conversation column')
            check('(1)' not in (await ev("document.getElementById('alertsroom').textContent") or ''),
                  'and clears the count')
            check(await ev("getComputedStyle(document.querySelector('.input-area')).display") == 'none',
                  'no composer bar in the feed')
            check(await ev("fabMode==='alert'&&getComputedStyle(document.getElementById('fab')).display") != 'none',
                  'a moderator has the + on Alerts')
            await ev("(fabClick(),1)")
            await asyncio.sleep(1)
            check(await ev("!!document.getElementById('al-text')"), 'it opens the alert form at the top of the feed')
            await ev("(document.getElementById('al-kind').value='road',"
                     "document.getElementById('al-text').value='bridge closed',postAlert(),1)")
            await asyncio.sleep(3)
            sent = json.load(urllib.request.urlopen('http://127.0.0.1:%d/__sent' % port))
            mine = [x for x in sent if x.startswith('t:warning') and 'bridge closed' in x]
            check(len(mine) == 1 and ' kind:road ' in mine[0] and ' sev:' in mine[0] and ' until:' in mine[0]
                  and ' sig:' in mine[0], 'a posted alert is a signed t:warning with kind, sev and until')
            text = await ev("document.getElementById('msgs').innerText") or ''
            check('bridge closed' in text and 'Withdraw' in text, 'it is listed, with Withdraw on our own')
            await ev("(withdrawAlert(document.querySelector('.alert[data-id] button')"
                     "&&[].slice.call(document.querySelectorAll('.alert')).filter(function(a){"
                     "return a.innerText.indexOf('bridge closed')>=0})[0].getAttribute('data-id'),'warning'),1)")
            await asyncio.sleep(3)
            sent = json.load(urllib.request.urlopen('http://127.0.0.1:%d/__sent' % port))
            check(any(x.startswith('t:warning') and ' remove:warning' in x for x in sent),
                  'withdrawing sends r:<id> remove:warning')

            # Private messages: sealed by default, clear text on request (6.2, 6.4).
            await ev("(showTab('admin'),1)")
            await asyncio.sleep(2)
            await ev("(document.querySelector('#v-admin .call.link').scrollIntoView({block:'center'}),1)")
            await asyncio.sleep(0.5)
            await click('#v-admin .call.link')
            await asyncio.sleep(1)
            check((await ev("curRoom") or '').startswith('dm:') and await ev("tab") == 'chat',
                  'a callsign in Administration opens a private message: %s' % await ev("curRoom"))
            peer_npub = await ev("npubEncode(pubkeyX(n2b(0x1234567890abcdef1234567890abcdefn,32)))")
            peer = await ev("callsignFromNpub(%s)" % json.dumps(peer_npub))
            await ev("(switchRoom('dmnew'),1)")
            await asyncio.sleep(1)
            check(await ev("!!document.getElementById('dm-to')"), 'New private message asks for a callsign or npub')
            await ev("(document.getElementById('dm-to').value=%s,startDm(),1)" % json.dumps(peer_npub))
            await asyncio.sleep(1)
            check(await ev("curRoom") == 'dm:' + peer, 'an npub opens the conversation with its callsign %s' % peer)
            await ev("(document.getElementById('txt').value='a sealed hello',sendMsg(),1)")
            await asyncio.sleep(2)
            sent = json.load(urllib.request.urlopen('http://127.0.0.1:%d/__sent' % port))
            dm = [x for x in sent if (' d:%s ' % peer) in x]
            check(len(dm) == 1 and ' x:' in dm[0] and ' m:' not in dm[0],
                  'sealed by default: x:, no words in the clear')
            await ev("(toggleSeal(),1)")
            await asyncio.sleep(1)
            check('Clear text' in (await ev("document.getElementById('msgs').innerText") or ''),
                  'the lock switches the conversation to clear text, and says so')
            await ev("(document.getElementById('txt').value='73 de radio',sendMsg(),1)")
            await asyncio.sleep(2)
            sent = json.load(urllib.request.urlopen('http://127.0.0.1:%d/__sent' % port))
            dm = [x for x in sent if (' d:%s ' % peer) in x and '73 de radio' in x]
            check(len(dm) == 1 and ' m:73 de radio' in dm[0] and ' x:' not in dm[0],
                  'clear text: m:, as amateur radio needs')
            await ev("(toggleSeal(),window.__asked=0,window.confirm=function(){window.__asked++;return false},1)")
            await ev("(openDm('X1NOKY'),document.getElementById('txt').value='who?',sendMsg(),1)")
            await asyncio.sleep(2)
            sent = json.load(urllib.request.urlopen('http://127.0.0.1:%d/__sent' % port))
            check(await ev("window.__asked") == 1 and not any(' d:X1NOKY ' in x for x in sent),
                  'with no key known it asks before sending in clear, and a no sends nothing')
    finally:
        chrome.terminate()
        mock.terminate()


print('on the station\'s network')
asyncio.run(run(8794, remote=False))
print('from the internet')
asyncio.run(run(8795, remote=True))
sys.exit(1 if fails else 0)
