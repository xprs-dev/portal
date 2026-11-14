#!/usr/bin/env python3
"""Private collections, in headless Chromium, against the mock.

    python3 tool/build.py && /usr/bin/python3 test/private_files_smoke.py [shots-dir]

A file posted in a hosted room is served to whoever may read that room
(XPRS.md 11.2): the administrator makes a private Gallery category and a
private Music category, adds a photo and a track through the page, and then
  - the page shows the photo and plays the track to the administrator;
  - the bytes are refused (403) to a visitor with no session;
  - a photo in a public category stays open to anyone;
  - an upload naming a private room is refused to a stranger.
"""
import asyncio
import base64
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request

import websockets

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROF = os.path.expanduser('~/snap/chromium/common/webchat-private-prof')
CDP = 9471
PORT = 8797
fails = 0


def check(ok, what):
    global fails
    print(('  [PASS] ' if ok else '  [FAIL] ') + what)
    fails += 0 if ok else 1


def status(path, data=None):
    req = urllib.request.Request('http://127.0.0.1:%d%s' % (PORT, path), data=data,
                                 method='POST' if data is not None else 'GET')
    try:
        return urllib.request.urlopen(req).status
    except urllib.error.HTTPError as e:
        return e.code


async def stranger(shots, pub, priv_ref):
    import websockets as wsl
    ver = json.load(urllib.request.urlopen('http://127.0.0.1:%d/json/version' % CDP))
    async with wsl.connect(ver['webSocketDebuggerUrl'], max_size=None) as bws:
        bn = [0]

        async def bsend(method, params=None):
            bn[0] += 1
            await bws.send(json.dumps({'id': bn[0], 'method': method, 'params': params or {}}))
            while True:
                m = json.loads(await bws.recv())
                if m.get('id') == bn[0]:
                    return m.get('result', {})
        ctx = (await bsend('Target.createBrowserContext'))['browserContextId']
        tid = (await bsend('Target.createTarget', {'url': 'about:blank', 'browserContextId': ctx}))['targetId']
    async with websockets.connect('ws://127.0.0.1:%d/devtools/page/%s' % (CDP, tid), max_size=None) as ws:
        n = [0]

        async def send(method, params=None):
            n[0] += 1
            await ws.send(json.dumps({'id': n[0], 'method': method, 'params': params or {}}))
            while True:
                m = json.loads(await ws.recv())
                if m.get('id') == n[0]:
                    return m.get('result', {})

        async def ev(js):
            r = await send('Runtime.evaluate', {'expression': js, 'awaitPromise': True, 'returnByValue': True})
            return r.get('result', {}).get('value')
        await send('Page.enable')
        await send('Emulation.setDeviceMetricsOverride',
                   {'width': 390, 'height': 844, 'deviceScaleFactor': 2, 'mobile': True})
        await send('Page.navigate', {'url': 'http://127.0.0.1:%d/' % PORT})
        await asyncio.sleep(6)
        check(bool(await ev("mycall")) and not await ev("isStationAdmin"),
              'the stranger has a key of their own (%s, session %s), and is no administrator'
              % (await ev("mycall"), 'proved' if await ev("sess") else 'none'))
        await ev("(switchRoom('gallery'),1)")
        await asyncio.sleep(3)
        names = await ev("[].map.call(document.querySelectorAll('.galcat b'),function(b){return b.textContent})") or []
        check(names == ['Club'], 'the stranger lists the public category only: %s' % names)
        if shots:
            r = await send('Page.captureScreenshot', {'format': 'png'})
            with open(os.path.join(shots, 'gallery-stranger.png'), 'wb') as f:
                f.write(base64.b64decode(r['data']))
        got = await ev("new Promise(function(ok){var i=new Image();i.onload=function(){ok('loaded')};"
                       "i.onerror=function(){ok('refused')};i.src=fileUrl('%s')})" % priv_ref)
        check(got == 'refused', 'the private photo by its address, from the stranger\'s page: %s' % got)


async def run(shots):
    env = dict(os.environ, MOCK_WIFI='1')
    mock = subprocess.Popen([sys.executable, os.path.join(ROOT, 'contract', 'mock_station.py'),
                             str(PORT)], env=env)
    shutil.rmtree(PROF, ignore_errors=True)
    os.makedirs(PROF, exist_ok=True)
    chrome = subprocess.Popen(['chromium', '--headless=new', '--no-sandbox', '--disable-gpu',
                               '--user-data-dir=' + PROF, '--remote-debugging-port=%d' % CDP,
                               '--window-size=1100,800', 'about:blank'],
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
                r = await send('Runtime.evaluate', {'expression': js, 'awaitPromise': True,
                                                   'returnByValue': True})
                return r.get('result', {}).get('value')

            async def shot(name):
                if not shots:
                    return
                r = await send('Page.captureScreenshot', {'format': 'png'})
                with open(os.path.join(shots, name + '.png'), 'wb') as f:
                    f.write(base64.b64decode(r['data']))

            await send('Page.enable')
            await send('Emulation.setDeviceMetricsOverride',
                       {'width': 1100, 'height': 800, 'deviceScaleFactor': 1, 'mobile': False})
            await send('Page.navigate', {'url': 'http://127.0.0.1:%d/' % PORT})
            await asyncio.sleep(5)
            # The administrator claims the station (the mock's first visitor may).
            await ev("(window.confirm=function(){return true},openView('admin'),1)")
            await asyncio.sleep(2)
            await ev("(el('ad-claim').click(),1)")
            await asyncio.sleep(3)
            check(bool(await ev("sess")), 'the administrator has a session')
            # Every upload's reference, as the page sends it.
            await ev("""(window.__puts=[],window.__galPut=galPut,galPut=function(ref,b,pv,pr,cb){
                __puts.push({ref:ref,room:galCat,preview:pv});return __galPut(ref,b,pv,pr,cb);},1)""")

            async def category(kind, name, vis):
                await ev("(showTab('chat'),switchRoom('%s'),1)" % kind)
                await asyncio.sleep(1.5)
                await ev("new Promise(function(ok){roomPost({action:'create',name:'%s',kind:'%s',"
                         "visibility:'%s',posting:'members'},function(j){loadRooms(function(){"
                         "ok(1)})})})" % (name, kind, vis))
                call = await ev("(galRooms().filter(function(r){return r.name==='%s'})[0]||{}).call" % name)
                await ev("(galOpen('%s'),1)" % call)
                await asyncio.sleep(1.5)
                folder = 'trip' if kind == 'gallery' else 'live'
                await ev("(el('ge-title').value='%s',el('ge-about').value='x',galNewEvent(),1)" % folder)
                await asyncio.sleep(2.5)
                return call

            async def add(make_js, name, type_):
                await ev("""new Promise(function(ok){(%s)(function(blob){
                    var f=new File([blob],'%s',{type:'%s'}),done=false;
                    galUpload(f,galRoom(),galEvent,function(){},function(){ok(1)});})})""" % (make_js, name, type_))
                await asyncio.sleep(1)
                await ev("(galAt=0,loadGallery(true),1)")
                await asyncio.sleep(2.5)

            photo = """function(cb){var c=document.createElement('canvas');c.width=640;c.height=420;
                var g=c.getContext('2d'),gr=g.createLinearGradient(0,0,640,420);
                gr.addColorStop(0,'#1e88e5');gr.addColorStop(1,'#43a047');g.fillStyle=gr;g.fillRect(0,0,640,420);
                g.fillStyle='#fff';g.font='bold 64px sans-serif';g.fillText('%s',40,230);c.toBlob(cb,'image/jpeg',.8);}"""
            tone = """function(cb){var sr=8000,n=sr,b=new ArrayBuffer(44+n*2),v=new DataView(b);
                function s(o,t){for(var i=0;i<t.length;i++)v.setUint8(o+i,t.charCodeAt(i));}
                s(0,'RIFF');v.setUint32(4,36+n*2,true);s(8,'WAVE');s(12,'fmt ');v.setUint32(16,16,true);
                v.setUint16(20,1,true);v.setUint16(22,1,true);v.setUint32(24,sr,true);v.setUint32(28,sr*2,true);
                v.setUint16(32,2,true);v.setUint16(34,16,true);s(36,'data');v.setUint32(40,n*2,true);
                for(var i=0;i<n;i++)v.setInt16(44+i*2,Math.sin(i/sr*2*Math.PI*440)*8000,true);
                cb(new Blob([b],{type:'audio/wav'}));}"""

            # A private gallery, a photo in it.
            fam = await category('gallery', 'Family', 'private')
            await add(photo % 'private', 'beach.jpg', 'image/jpeg')
            puts = await ev("__puts") or []
            priv = [p['ref'] for p in puts if p['room'] == fam]
            check(len(priv) == 2, 'the photo and its preview were uploaded naming the room: %s' % len(priv))
            shown = await ev("[].filter.call(document.querySelectorAll('#v-gallery img, .galgrid img'),"
                             "function(i){return i.complete&&i.naturalWidth>0}).length")
            check((shown or 0) >= 1, 'the administrator sees the private photo (%s shown)' % shown)
            await shot('private-gallery-admin')
            tok = await ev("sess")
            for ref in priv:
                check(status('/api/xprs/file/' + ref) == 403, 'no session: %s… refused (403)' % ref[:8])
                check(status('/api/xprs/file/%s?session=%s' % (ref, tok)) == 200,
                      'the administrator\'s session: %s… served' % ref[:8])
            check(status('/api/xprs/file/%s?session=nobody' % priv[0]) == 403, 'a made-up session: refused')
            check(status('/api/xprs/file/%s?room=%s' % (
                'AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA.jpg', fam), b'x') == 403,
                'a stranger cannot upload naming the private room')

            # A private music category, a track in it.
            band = await category('music', 'Rehearsals', 'private')
            await add(tone, 'tuning.wav', 'audio/wav')
            puts = await ev("__puts") or []
            track = [p['ref'] for p in puts if p['room'] == band]
            check(len(track) == 1, 'the track was uploaded naming the room')
            if track:
                check(status('/api/xprs/file/' + track[0]) == 403, 'the private track is refused without a session')
            await ev("(galPlay&&document.querySelector('.galplay')&&document.querySelector('.galplay').click(),1)")
            await asyncio.sleep(2)
            src = await ev("(function(){var a=document.getElementById('gal-player');return a?a.src:''})()") or ''
            check('session=' in src, 'the player asks for the track with the session')
            dur = await ev("""new Promise(function(ok){var a=document.getElementById('gal-player');
                if(!a)return ok(null);if(a.duration>0)return ok(a.duration);
                a.addEventListener('loadedmetadata',function(){ok(a.duration)});
                a.addEventListener('error',function(){ok(-1)});a.preload='metadata';a.load();
                setTimeout(function(){ok(a.duration||0)},8000);})""")
            check(bool(dur) and dur > 0.5, 'the administrator plays it (%.1f s)' % (dur or 0))
            await shot('private-music-admin')

            # A public gallery: its photo stays open.
            pub = await category('gallery', 'Club', 'public')
            await add(photo % 'public', 'mast.jpg', 'image/jpeg')
            puts = await ev("__puts") or []
            open_ = [p['ref'] for p in puts if p['room'] == pub]
            check(len(open_) == 2 and all(status('/api/xprs/file/' + r) == 200 for r in open_),
                  'a public category\'s photo is served to anyone')

            # A stranger: a browser of their own (a fresh context, its own
            # key and session, in no room), who knows the private photo's address.
            await stranger(shots, pub, priv[0])
    finally:
        chrome.terminate()
        mock.terminate()


if __name__ == '__main__':
    shots = sys.argv[1] if len(sys.argv) > 1 else ''
    if shots:
        os.makedirs(shots, exist_ok=True)
    asyncio.run(run(shots))
    print('private files: %s' % ('all passed' if not fails else '%d failed' % fails))
    sys.exit(1 if fails else 0)
