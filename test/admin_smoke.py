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
            check(st['settings'] == {'local_private': False, 'who_may_post': 'local'},
                  'changed settings reach the station: %s' % st['settings'])
    finally:
        chrome.terminate()
        mock.terminate()


print('on the station\'s network')
asyncio.run(run(8794, remote=False))
print('from the internet')
asyncio.run(run(8795, remote=True))
sys.exit(1 if fails else 0)
