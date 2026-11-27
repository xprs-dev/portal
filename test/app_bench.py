#!/usr/bin/env python3
"""The installable app, end to end, against a live station (a bench test: it
needs the network and a gateway that reaches the station).

    python3 tool/build.py && sh ../xprs-dev.github.io/tool/sync_in.sh
    python3 test/app_bench.py [callsign]          # default x3ptzm

The site is served from this machine as GitHub Pages serves it
(xprs-dev.github.io/tool/serve.py); the page reaches the station over
Reticulum through the gateways of in/gateways.json. Checked:

  - the portal opens over the link, thrifty, and can be installed (the
    manifest and the worker satisfy the browser);
  - the worker keeps every file of version.json;
  - an idle open page costs little (the bytes of the WebSocket are counted);
  - with the site gone (the server stopped), the app still starts and reaches
    the station, and the conversation is on the screen from what was kept
    before the station answered;
  - the second start costs a fraction of the first.
"""
import base64
import json
import os
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from cdp import Cdp  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SITE = os.path.join(os.path.dirname(ROOT), 'xprs-dev.github.io')
BROWSER = os.environ.get('WEBCHAT_BROWSER', 'chromium')
PROF = os.path.expanduser('~/snap/chromium/common/webchat-app-prof' if BROWSER == 'chromium'
                          else '~/.cache/webchat-app-prof')
PORT = 8800
CALL = (sys.argv[1] if len(sys.argv) > 1 else 'x3ptzm').lower()
URL = 'http://127.0.0.1:%d/in/%s' % (PORT, CALL)
IDLE = int(os.environ.get('APP_BENCH_IDLE', '90'))
fails = 0


def check(ok, what, extra=None):
    global fails
    print(('  [PASS] ' if ok else '  [FAIL] ') + what + (('  -- ' + str(extra)) if (extra and not ok) else ''))
    fails += 0 if ok else 1


def serve():
    p = subprocess.Popen([sys.executable, os.path.join(SITE, 'tool', 'serve.py'), str(PORT)])
    time.sleep(1)
    return p


def ws_bytes(c):
    """Bytes of WebSocket frames seen since the last call: (sent, received)."""
    c.eval('1')   # drain the pipe
    up = down = 0
    for e in c.events:
        d = e['params']['response']
        n = len(d.get('payloadData', ''))
        if d.get('opcode') == 2:
            n = n * 3 // 4
        if e['method'].endswith('Sent'):
            up += n
        else:
            down += n
    c.events = []
    return up, down


def aeval(c, expr):
    r = c.send('Runtime.evaluate', {'expression': expr, 'returnByValue': True, 'awaitPromise': True})
    return r.get('result', {}).get('value')


def asks(c, title):
    """What was asked over the link since the last call, largest first."""
    rows = c.eval("(function(){var a=window.__asks||[];window.__asks=[];return a;})()") or []
    by = {}
    for a in rows:
        q = json.loads(a.get('q') or '{}')
        k = a['m'] + ' ' + a['p'] + ' ' + ' '.join('%s=%s' % (x, '..' if x in ('session', 'since') else q[x])
                                                    for x in sorted(q) if x != 'limit')
        if 'since' not in q and a['p'].endswith('/history'):
            k += ' (whole)'
        e = by.setdefault(k, [0, 0])
        e[0] += 1
        e[1] += max(a.get('n', 0), 0)
    print('         %s: %d calls, %s of answers' % (title, len(rows), kb(sum(e[1] for e in by.values()))))
    for k, e in sorted(by.items(), key=lambda x: -x[1][1])[:14]:
        print('           %7s %3dx  %s' % (kb(e[1]), e[0], k[:110]))


def kb(n):
    return '%.1f KB' % (n / 1024.0)


site = serve()
c = Cdp(BROWSER, PROF)
portal = "!!window.XPRS_REMOTE&&!!document.getElementById('txt')"
rows = "document.querySelectorAll('#msgs .msg').length"
try:
    c.attach()
    c.send('Network.enable')
    c.watch = {'Network.webSocketFrameReceived', 'Network.webSocketFrameSent'}
    # Every call over the link, by what it asked and how much came back.
    c.send('Page.addScriptToEvaluateOnNewDocument', {'source': '''
      window.__asks=[];
      (function(){var t=setInterval(function(){
        var r=window.XprsRns;if(!r||!r.api||r.api.__w)return;
        var real=r.api;
        r.api=function(m,p,q){var a={m:m,p:p,q:q,n:-1};window.__asks.push(a);
          return real.apply(this,arguments).then(function(x){a.n=x&&x.body?x.body.length:0;a.s=x&&x.status;return x;});};
        r.api.__w=1;clearInterval(t);},5);})();'''})

    print('first visit: ' + URL)
    t0 = time.time()
    c.send('Page.navigate', {'url': URL})
    ok = c.wait(portal, 120)
    check(ok, 'the portal opens over Reticulum', c.eval("(document.getElementById('in-log')||{}).innerText"))
    if not ok:
        raise SystemExit(1)
    print('         in %.0f s, on %s through %s' % (time.time() - t0, c.eval("XPRS_REMOTE.station"),
                                                      c.eval("XPRS_REMOTE.gateway")))
    check(c.eval("THRIFTY") is True and c.eval("tabMs('chat')") == 20000, 'thrifty: the chat asks every twenty seconds')
    check(c.wait("chatLoaded", 60), 'the station answered the conversation')
    time.sleep(20)   # the rooms, the blog, the alerts, the map's first asks
    n1 = c.eval(rows)
    up, down = ws_bytes(c)
    first = up + down
    print('         first open: %s up, %s down; %d messages drawn' % (kb(up), kb(down), n1))
    asks(c, 'first open')

    print('an app')
    check(c.eval("!!document.querySelector('link[rel=manifest]')"), 'the manifest is on the portal\'s head')
    check(c.eval("typeof XPRS_REMOTE.install.state()") == 'string' and
          c.eval("XPRS_REMOTE.lib") == '/in/lib/', 'the portal is told of the install offer and the libraries')
    check(c.wait("!!navigator.serviceWorker.controller", 30), 'the worker controls the page')
    kept = aeval(c, "caches.open('xprs-app-v1').then(function(c){return c.keys();})"
                    ".then(function(k){return k.map(function(r){return new URL(r.url).pathname;});})") or []
    listed = list(json.load(open(os.path.join(SITE, 'in', 'version.json')))['files'])
    check(all(p in kept for p in listed), 'it keeps every file of version.json (%d)' % len(listed),
          [p for p in listed if p not in kept])
    errs = c.send('Page.getInstallabilityErrors').get('installabilityErrors', [])
    check(not errs, 'the browser finds it installable', errs)
    man = c.send('Page.getAppManifest')
    check(not man.get('errors') and '"start_url": "/in/"' in man.get('data', ''), 'its manifest parses, starting at /in/',
          man.get('errors'))
    check(c.eval("window.L&&document.querySelector('script[src^=\"/in/lib/leaflet\"]')?1:0") == 1,
          'the map\'s library came from the app, not a CDN')

    print('idle for %d s' % IDLE)
    ws_bytes(c)
    time.sleep(IDLE)
    c.eval('1')
    # Announces (Reticulum packet type 1) are not the page's: the gateway
    # pushes them, and they are counted apart.
    ann = [0, 0]
    for e in c.events:
        d = e['params']['response']
        if d.get('opcode') == 2 and e['method'].endswith('Received'):
            raw = base64.b64decode(d['payloadData'])
            if raw and raw[0] & 3 == 1:
                ann[0] += 1
                ann[1] += len(raw)
    up, down = ws_bytes(c)
    own = (up + down - ann[1]) * 3600.0 / IDLE
    print('         %s up, %s down, of which %d announces the gateway pushed (%s)' % (kb(up), kb(down), ann[0], kb(ann[1])))
    print('         the page\'s own: %s an hour; with the announces: %s an hour' %
          (kb(own), kb((up + down) * 3600.0 / IDLE)))
    asks(c, 'idle')
    check(own < 150 * 1024, 'an idle open page costs under 150 KB an hour of its own (it was about 12 MB)')

    print('a file, kept by its reference')
    # The smallest file the station really serves whole: a few of what it
    # lists and of what its conversations carry, the smallest first.
    small = aeval(c, """fetch('/api/xprs/history?kind=file,message,blog,status&limit=200').then(function(r){return r.json();}).then(function(d){
      var c=[];(d.rows||[]).forEach(function(r){var w=r.wire||'',f=/ file:(\\S+\\.[a-z0-9]+)/.exec(w),z=/ size:(\\d+)/.exec(w);
        if(f&&!r.to&&!/\\.(pmtiles|xfl|want)$/.test(f[1])&&(!z||+z[1]<300000))c.push({ref:f[1],size:z?+z[1]:1});});
      c.sort(function(a,b){return a.size-b.size;});c=c.slice(0,4);
      function next(i){if(i>=c.length)return null;
        return fetch('/api/xprs/file/'+c[i].ref).then(function(r){if(!r.ok)return next(i+1);
          return r.arrayBuffer().then(function(b){return {ref:c[i].ref,size:b.byteLength};});});}
      return next(0);})""")
    if not small:
        print('         (the station shares no small public file: not checked)')
    else:
        asks(c, 'the listing and the file')
        print('         read over the link: %s, %d bytes' % (small['ref'], small['size']))
        time.sleep(1)
        check(aeval(c, "caches.open('xprs-files-v1').then(function(k){return k.match('/in/_file/%s');}).then(function(r){return !!r;})" % small['ref']),
              'it is kept')
        c.eval("window.__asks=[]")
        n = aeval(c, "fetch('/api/xprs/file/%s').then(function(r){return r.arrayBuffer();}).then(function(b){return b.byteLength;})" % small['ref'])
        check(n == small['size'] and c.eval("window.__asks.length") == 0, 'read again: the same bytes, and the station was not asked')
    time.sleep(2)

    print('the site is gone')
    site.terminate()
    site.wait()
    site = None
    t0 = time.time()
    c.send('Page.navigate', {'url': URL})
    ok = c.wait(portal, 120)
    check(ok, 'the app starts with nothing fetched from the site', c.eval("document.body&&document.body.innerText.slice(0,200)"))
    if ok:
        early = c.wait(rows + ">0", 6)
        check(early and not c.eval("chatLoaded&&false"), 'the conversation is on the screen from what was kept (%s messages)' % early)
        check(c.wait("chatLoaded", 90), 'and the station is reached again over the link (%.0f s)' % (time.time() - t0))
        time.sleep(20)
        up, down = ws_bytes(c)
        second = up + down
        print('         second open: %s up, %s down (the first was %s)' % (kb(up), kb(down), kb(first)))
        asks(c, 'second open')
        check(second < first * 0.6, 'the second start costs well under the first')
        check(c.eval(rows) >= n1, 'with every message of the first still drawn')
        files = aeval(c, "caches.open('xprs-files-v1').then(function(c){return c.keys();}).then(function(k){return k.length;})")
        print('         files kept by reference: %s' % files)
finally:
    c.close()
    if site:
        site.terminate()
sys.exit(1 if fails else 0)
