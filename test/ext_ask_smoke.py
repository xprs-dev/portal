#!/usr/bin/env python3
"""A NOSTR extension is offered first, in headless Chromium, against the mock.

    python3 tool/build.py && /usr/bin/python3 test/ext_ask_smoke.py

The stand-in extension of ext_smoke.py, injected the moment the page has its
helpers (as a real one injects window.nostr), on a fresh browser:
  1. a first visit with an extension asks, makes no key, and "Use my NOSTR
     identity" adopts the extension's callsign;
  2. a reload remembers the choice and does not ask;
  3. a first visit that answers "Make a new key" gets a page key, and is not
     asked again;
  4. a first visit with no extension gets a page key, as before.
"""
import asyncio
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.request

import websockets

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
PROF = os.path.expanduser('~/snap/chromium/common/webchat-ask-prof')
PORT, CDP = 8793, 9467
fails = 0

# The stand-in extension from ext_smoke.py (getPublicKey is all this needs,
# plus signEvent for the session the page proves after adopting it).
src = open(os.path.join(HERE, 'ext_smoke.py'), encoding='utf-8').read()
EXT = re.search(r'EXT = r"""(.*?)"""', src, re.S).group(1)


def check(ok, what):
    global fails
    print(('  [PASS] ' if ok else '  [FAIL] ') + what)
    fails += 0 if ok else 1


async def main():
    mock = subprocess.Popen([sys.executable, os.path.join(ROOT, 'contract', 'mock_station.py'), str(PORT)])
    shutil.rmtree(PROF, ignore_errors=True)
    os.makedirs(PROF, exist_ok=True)
    chrome = subprocess.Popen(['chromium', '--headless=new', '--no-sandbox', '--disable-gpu',
                               '--user-data-dir=' + PROF, '--remote-debugging-port=%d' % CDP, 'about:blank'],
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
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
                r = await send('Runtime.evaluate', {'expression': js, 'awaitPromise': True, 'returnByValue': True})
                return r.get('result', {}).get('value')

            async def visit(fresh, extension):
                if fresh:  # a browser that never saw this station
                    await ev("(localStorage.clear(),document.cookie.split(';').forEach(function(c){"
                             "document.cookie=c.split('=')[0].trim()+'=; max-age=0; path=/';}),1)")
                await send('Page.navigate', {'url': 'http://127.0.0.1:%d/' % PORT})
                await asyncio.sleep(0.6)
                if extension:
                    await ev(EXT + "1")
                await asyncio.sleep(3.2)  # past the page's 3 s look for an extension

            asking = "document.getElementById('extask').style.display!=='none'"
            expect = None
            await send('Page.enable')
            await send('Page.navigate', {'url': 'http://127.0.0.1:%d/' % PORT})
            await asyncio.sleep(1)

            # 1. First visit, extension present.
            await visit(fresh=True, extension=True)
            expect = await ev("callsignFromNpub(npubEncode(pubkeyX(n2b(7n,32))))")
            check(await ev(asking), '1. a first visit with an extension is asked')
            check(await ev("stGet('xprs_nsec')===null&&!canSign()"),
                  '1. and no key is made while the question is open')
            check(await ev("document.activeElement&&document.activeElement.id") == 'extyes',
                  '1. "Use my NOSTR identity" is the default answer')
            await ev("(answerExt(true),1)")
            await asyncio.sleep(2)
            check(await ev("extMode") is True and await ev("mycall") == expect,
                  '1. answering yes adopts the extension: %s' % expect)
            check(not await ev(asking) and await ev("stGet('xprs_ext')") == '1',
                  '1. the question closes and the choice is kept')
            check(await ev("stGet('xprs_nsec')") is None, '1. still no page key was made')

            # 2. Reload: remembered.
            await visit(fresh=False, extension=True)
            check(not await ev(asking), '2. a reload does not ask again')
            check(await ev("extMode") is True and await ev("mycall") == expect,
                  '2. and comes back as the extension identity')

            # 3. First visit, declined.
            await visit(fresh=True, extension=True)
            check(await ev(asking), '3. a new browser is asked')
            await ev("(answerExt(false),1)")
            await asyncio.sleep(1)
            mine = await ev("mycall")
            check(await ev("extMode") is False and await ev("!!priv") and mine and mine != expect,
                  '3. "Make a new key" gives a page key: %s' % mine)
            check(await ev("stGet('xprs_ext')") == '0' and bool(await ev("stGet('xprs_nsec')")),
                  '3. the refusal and the key are kept')
            await visit(fresh=False, extension=True)
            check(not await ev(asking) and await ev("mycall") == mine,
                  '3. a reload keeps the page key and does not ask')

            # 4. First visit, no extension.
            await visit(fresh=True, extension=False)
            check(not await ev(asking) and await ev("!!priv") and bool(await ev("mycall")),
                  '4. with no extension a page key is made, as before')
    finally:
        chrome.terminate()
        mock.terminate()


asyncio.run(main())
sys.exit(1 if fails else 0)
