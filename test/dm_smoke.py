#!/usr/bin/env python3
"""A direct message through the page, in headless Chromium, against the mock.

    python3 tool/build.py && /usr/bin/python3 test/dm_smoke.py

Proves what the unit tests cannot: that the page gets a session from a station
that offers one, reads a message another key sealed to it and opens it, finds
the peer's key from a verified identity, and seals its own reply so that the
peer's key opens it. Needs the `websockets` module (the system python has it).
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
PROF = os.path.expanduser('~/snap/chromium/common/webchat-dm-prof')
PORT, CDP = 8791, 9444
fails = 0


def check(ok, what):
    global fails
    print(('  [PASS] ' if ok else '  [FAIL] ') + what)
    fails += 0 if ok else 1


async def main():
    mock = subprocess.Popen([sys.executable, os.path.join(ROOT, 'contract', 'mock_station.py'), str(PORT)])
    shutil.rmtree(PROF, ignore_errors=True)   # the page keeps its room and key in localStorage
    os.makedirs(PROF, exist_ok=True)
    chrome = subprocess.Popen(['chromium', '--headless=new', '--no-sandbox', '--disable-gpu',
                               '--user-data-dir=' + PROF, '--remote-debugging-port=%d' % CDP,
                               'http://127.0.0.1:%d/' % PORT],
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

            async def ev(js):
                nonlocal n
                n += 1
                await ws.send(json.dumps({'id': n, 'method': 'Runtime.evaluate',
                                          'params': {'expression': js, 'awaitPromise': True,
                                                     'returnByValue': True}}))
                while True:
                    m = json.loads(await ws.recv())
                    if m.get('id') == n:
                        return m['result'].get('result', {}).get('value')

            await asyncio.sleep(4)
            check(await ev("sess!==''"), 'the page got a session from the station')
            peer = "n2b(7n,32)"
            await ev(f"""(async()=>{{
              var pp={peer}, pub=pubkeyX(pp);
              var sealed=sealBody(pp,pubkeyX(priv),'a secret from the peer');
              var post=(p,b)=>fetch(p,{{method:'POST',body:JSON.stringify(b)}});
              await post('/__row',{{ts:1790000000,bearer:'lan',rssi:0,from:'X1PEER',to:'',type:'identity',
                sig:'verified',own:false,wire:'t:identity f:X1PEER ts:2026-10-15_12:00:00 k:'+npubEncode(pub)}});
              await post('/__inject',{{from:'X1PEER',to:mycall,
                wire:'t:message f:X1PEER d:'+mycall+' ts:2026-10-15_12:00:01 x:'+sealed}});
              return 1;}})()""")
            await ev("(load(),1)")
            await asyncio.sleep(2)
            check('X1PEER' in (await ev("Object.keys(dmPeers).join()") or ''), 'a room for the peer appears')
            side = await ev("document.getElementById('side').textContent") or ''
            check('X1PEER (1)' in side, 'the left column counts the unread message: %r' % side[-40:])
            check(await ev("document.querySelector('#side .room[data-r=\"dm:X1PEER\"]').className.indexOf('unread')>=0"),
                  'and marks the conversation unread')
            await ev("(openDm('X1PEER'),1)")
            await asyncio.sleep(2)
            text = await ev("document.getElementById('msgs').innerText") or ''
            check('a secret from the peer' in text, 'the sealed message is opened and shown')
            side = await ev("document.getElementById('side').textContent") or ''
            check('X1PEER (1)' not in side and 'X1PEER' in side, 'opening it clears the count')
            await ev("(load(),1)")
            await asyncio.sleep(2)
            check('(1)' not in (await ev("document.querySelector('#side .room[data-r=\"dm:X1PEER\"]').textContent") or ''),
                  'and the next poll does not count it again')
            check(await ev("document.getElementById('msgs').innerHTML.indexOf('>sealed<')>=0"),
                  'and marked sealed')
            await ev("(document.getElementById('txt').value='reply sealed',sendMsg(),1)")
            await asyncio.sleep(2)
            sent = json.load(urllib.request.urlopen('http://127.0.0.1:%d/__sent' % PORT))
            dm = [w for w in sent if ' d:X1PEER' in w]
            check(len(dm) == 1 and ' x:' in dm[0] and ' m:' not in dm[0], 'the reply goes out sealed, with no m:')
            if dm:
                x = dm[0].split(' x:')[1].split(' ')[0]
                back = await ev(f"openBody(n2b(7n,32),pubkeyX(priv),{json.dumps(x)})")
                check(back == 'reply sealed', "and the peer's key opens it")
    finally:
        chrome.terminate()
        mock.terminate()


asyncio.run(main())
sys.exit(1 if fails else 0)
