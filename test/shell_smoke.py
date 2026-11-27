#!/usr/bin/env python3
"""xprs.dev/in/ as an app, without the network: the real shell (in/shell.js),
worker (in/sw.js) and portal, with Reticulum replaced by a stand-in that
carries each call to the mock station.

    python3 tool/build.py && sh ../xprs-dev.github.io/tool/sync_in.sh
    python3 test/shell_smoke.py

  - the portal opens through the shell, thrifty;
  - gateways: one that is down is passed over, the one that worked is tried
    first at the next visit, and every one listed is remembered;
  - the worker keeps every file of version.json; with the site answering
    nothing, the app starts and reaches the station;
  - an update fetches the one file whose hash changed, and nothing when a
    file is not what version.json names;
  - a file read from the station is kept by its reference: read again, and
    shown as a picture, without the station being asked;
  - the install entry: hidden on a desktop that offers nothing, shown with
    the way to do it on an iPhone.
"""
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from cdp import Cdp  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SITE = os.path.join(os.path.dirname(ROOT), 'xprs-dev.github.io')
BROWSER = os.environ.get('WEBCHAT_BROWSER', 'chromium')
PROF = os.path.expanduser('~/snap/chromium/common/webchat-shell-prof' if BROWSER == 'chromium'
                          else '~/.cache/webchat-shell-prof')
PORT, MOCK = 8795, 8796
URL = 'http://127.0.0.1:%d/in/x3mock' % PORT
fails = 0

# Reticulum for the browser, stood in for: a gateway whose name says `down`
# refuses; a call goes to the mock station through this server (/__mock).
FAKE_RNS = r'''
window.__gw=[];window.__api=[];
window.XprsRns={
  connect:function(g){window.__gw.push(g);
    try{var t=JSON.parse(sessionStorage.getItem('gwTried')||'[]');t.push(g);sessionStorage.setItem('gwTried',JSON.stringify(t));}catch(e){}
    return /down/.test(g)?Promise.reject(new Error(g+' is down')):Promise.resolve(JSON.stringify({station:'X3MOCK'}));},
  resolve:function(c){return Promise.resolve(JSON.stringify({rns:new Array(65).join('ab')}));},
  open:function(){return Promise.resolve(true);},
  prove:function(){return Promise.resolve('proof');},
  verify:function(){return JSON.stringify({ok:true,nick:''});},
  api:function(m,p,q,b,c,h){window.__api.push(m+' '+p);
    var qs=new URLSearchParams(JSON.parse(q||'{}')).toString();
    return fetch('/__mock'+p+(qs?'?'+qs:''),{method:m,body:b==null?undefined:b,headers:h?JSON.parse(h):{}}).then(function(r){
      return r.arrayBuffer().then(function(buf){var hd={};r.headers.forEach(function(v,k){hd[k]=v;});
        return {status:r.status,type:r.headers.get('content-type')||'',body:new Uint8Array(buf),headers:JSON.stringify(hd)};});});}
};
'''


def check(ok, what, extra=None):
    global fails
    print(('  [PASS] ' if ok else '  [FAIL] ') + what + (('  -- ' + str(extra)) if (extra and not ok) else ''))
    fails += 0 if ok else 1


def version(tree):
    v = json.load(open(os.path.join(tree, 'in', 'version.json')))
    for p in v['files']:
        v['files'][p] = hashlib.sha256(open(os.path.join(tree, p.lstrip('/')), 'rb').read()).hexdigest()
    json.dump(v, open(os.path.join(tree, 'in', 'version.json'), 'w'))


TREE = tempfile.mkdtemp(prefix='xprs-site-')
shutil.copytree(os.path.join(SITE, 'in'), os.path.join(TREE, 'in'))
for f in ('404.html', 'favicon.svg'):
    shutil.copy(os.path.join(SITE, f), TREE)
open(os.path.join(TREE, 'in', 'rns.js'), 'w').write(FAKE_RNS)
json.dump({'gateways': ['wss://down.example/rns', 'wss://up.example/rns']},
          open(os.path.join(TREE, 'in', 'gateways.json'), 'w'))
version(TREE)
STATE = {'down': False, 'hits': []}
TYPES = {'html': 'text/html; charset=utf-8', 'js': 'text/javascript', 'css': 'text/css', 'json': 'application/json',
         'svg': 'image/svg+xml', 'png': 'image/png', 'webmanifest': 'application/manifest+json'}


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _go(self):
        path = self.path.split('?')[0]
        n = int(self.headers.get('Content-Length') or 0)
        body = self.rfile.read(n) if n else None
        if path.startswith('/__mock/'):
            req = urllib.request.Request('http://127.0.0.1:%d%s' % (MOCK, self.path[len('/__mock'):]), data=body,
                                         method=self.command)
            for k in ('Range', 'Content-Type'):
                if self.headers.get(k):
                    req.add_header(k, self.headers[k])
            try:
                r = urllib.request.urlopen(req, timeout=10)
                code, data, hd = r.status, r.read(), r.headers
            except urllib.error.HTTPError as e:
                code, data, hd = e.code, e.read(), e.headers
            self.send_response(code)
            for k in ('Content-Type', 'Cache-Control', 'Content-Range'):
                if hd.get(k):
                    self.send_header(k, hd[k])
            self.send_header('Content-Length', str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return
        STATE['hits'].append(path)
        if STATE['down']:
            self.send_response(503)
            self.send_header('Content-Length', '0')
            self.end_headers()
            return
        f = os.path.join(TREE, path.lstrip('/'))
        if os.path.isdir(f):
            f = os.path.join(f, 'index.html')
        code = 200
        if not os.path.isfile(f):
            f, code = os.path.join(TREE, '404.html'), 404
        data = open(f, 'rb').read()
        self.send_response(code)
        self.send_header('Content-Type', TYPES.get(f.rsplit('.', 1)[-1], 'application/octet-stream'))
        self.send_header('Content-Length', str(len(data)))
        self.send_header('Cache-Control', 'no-cache')
        self.end_headers()
        self.wfile.write(data)

    def _quiet(self):
        try:
            self._go()
        except (BrokenPipeError, ConnectionResetError):
            pass    # the page went on to the next visit

    do_GET = do_POST = _quiet


site = ThreadingHTTPServer(('127.0.0.1', PORT), H)
Thread(target=site.serve_forever, daemon=True).start()
env = dict(os.environ)
env['MOCK_FORUM'] = '1'
station = subprocess.Popen([sys.executable, os.path.join(ROOT, 'contract', 'mock_station.py'), str(MOCK)], env=env)
time.sleep(1)
c = Cdp(BROWSER, PROF)
portal = "!!window.XPRS_REMOTE&&!!document.getElementById('txt')"
drawn = "document.getElementById('msgs').textContent.indexOf('hello from the mock')>=0"


def aeval(expr):
    r = c.send('Runtime.evaluate', {'expression': expr, 'returnByValue': True, 'awaitPromise': True})
    return r.get('result', {}).get('value')


def go():
    c.send('Page.navigate', {'url': URL})
    return c.wait(portal, 30)


try:
    c.attach()
    c.send('Network.enable')
    c.send('Network.setBlockedURLs', {'urls': ['*leaflet*']})

    print('the portal through the shell')
    check(go(), 'the portal takes the looking page\'s place', c.eval("document.body.innerText.slice(0,300)"))
    check(c.wait(drawn, 10), 'and draws the station\'s conversation, read over the link')
    check(c.eval("THRIFTY") is True and c.eval("XPRS_REMOTE.station") == 'X3MOCK', 'thrifty, on X3MOCK')
    check(c.eval("!!document.querySelector('link[rel=manifest]')&&!!document.querySelector('link[rel=apple-touch-icon]')"),
          'what makes it an app is on the portal\'s head')

    print('gateways')
    check(c.eval("XPRS_REMOTE.gateway") == 'wss://up.example/rns', 'the gateway that is down is passed over')
    memo = json.loads(c.eval("localStorage.getItem('xprs_reach')"))
    check(memo.get('gw') == 'wss://up.example/rns' and sorted(memo.get('gws', [])) ==
          ['wss://down.example/rns', 'wss://up.example/rns'], 'the one that worked and every one listed are remembered', memo)
    check(c.wait("!!navigator.serviceWorker.controller", 20), 'the worker controls the page')
    c.eval("sessionStorage.removeItem('gwTried')")
    check(go(), 'a second visit')
    check(json.loads(c.eval("sessionStorage.getItem('gwTried')"))[0] == 'wss://up.example/rns',
          'tries the gateway that worked first', c.eval("sessionStorage.getItem('gwTried')"))

    print('kept on the device')
    kept = aeval("caches.open('xprs-app-v1').then(function(c){return c.keys();})"
                 ".then(function(k){return k.map(function(r){return new URL(r.url).pathname;});})") or []
    listed = list(json.load(open(os.path.join(TREE, 'in', 'version.json')))['files'])
    check(all(p in kept for p in listed), 'the worker keeps every file of version.json (%d)' % len(listed),
          [p for p in listed if p not in kept])
    errs = c.send('Page.getInstallabilityErrors').get('installabilityErrors', [])
    check(not errs, 'the browser finds it installable', errs)
    STATE['hits'] = []
    check(go() and c.wait(drawn, 10), 'a start with the worker in place')
    asked = [h for h in STATE['hits'] if h not in ('/in/sw.js', '/in/manifest.webmanifest') and '/icons/' not in h]
    check(not asked, 'asks the site for none of the app\'s files', asked)
    STATE['down'] = True
    check(go() and c.wait(drawn, 10), 'with the site answering nothing, the app starts and reaches the station')
    json.dump({'gateways': []}, open(os.path.join(TREE, 'in', 'gateways.json'), 'w'))
    STATE['down'] = False

    print('an update')
    css = os.path.join(TREE, 'in', 'logo-font.css')
    open(css, 'a').write('\n/* a new release */\n')
    version(TREE)
    STATE['hits'] = []
    got = aeval("""new Promise(function(ok){navigator.serviceWorker.addEventListener('message',function(e){
      if(e.data&&e.data.op==='checked')ok(e.data);});navigator.serviceWorker.controller.postMessage({op:'check'});})""")
    check(got and got.get('ok') and got.get('changed') == 2, 'two files changed: the font and the gateway list', got)
    check(sorted(h for h in STATE['hits'] if h != '/in/version.json') == ['/in/gateways.json', '/in/logo-font.css'],
          'and only those two were fetched', STATE['hits'])
    check('a new release' in (aeval("caches.open('xprs-app-v1').then(function(c){return c.match('/in/logo-font.css');})"
                                    ".then(function(r){return r.text();})") or ''), 'the kept copy is the new one')
    check(go() and c.eval("XPRS_REMOTE.gateway") == 'wss://up.example/rns',
          'a list that names no gateway any more: the remembered ones still open the app')
    open(css, 'a').write('/* tampered */')
    v = json.load(open(os.path.join(TREE, 'in', 'version.json')))
    v['files']['/in/logo-font.css'] = '0' * 64
    json.dump(v, open(os.path.join(TREE, 'in', 'version.json'), 'w'))
    got = aeval("""new Promise(function(ok){navigator.serviceWorker.addEventListener('message',function(e){
      if(e.data&&e.data.op==='checked')ok(e.data);});navigator.serviceWorker.controller.postMessage({op:'check'});})""")
    check(got and got.get('ok') is False, 'a file that is not what version.json names: the update is refused', got)
    check('tampered' not in (aeval("caches.open('xprs-app-v1').then(function(c){return c.match('/in/logo-font.css');})"
                                   ".then(function(r){return r.text();})") or 'tampered'), 'and what was kept stays')

    print('a file, kept by its reference')
    png = bytes.fromhex('89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489'
                        '0000000d49444154789c6360f8cfc0500f00048501808'
                        '4a98c210000000049454e44ae426082')
    import base64
    ref = base64.urlsafe_b64encode(hashlib.sha256(png).digest()).decode().rstrip('=') + '.png'
    urllib.request.urlopen(urllib.request.Request('http://127.0.0.1:%d/api/xprs/file/%s' % (MOCK, ref), data=png), timeout=5)
    read = "fetch('/api/xprs/file/%s').then(function(r){return r.arrayBuffer();}).then(function(b){return b.byteLength;})" % ref
    c.eval("window.__api=[]")
    check(aeval(read) == len(png) and len([a for a in c.eval("window.__api") if '/file/' in a]) == 1,
          'read over the link, once', c.eval("window.__api"))
    time.sleep(0.5)
    check(aeval("caches.open('xprs-files-v1').then(function(k){return k.match('/in/_file/%s');}).then(function(r){return !!r;})" % ref),
          'it is kept under its reference')
    check(go(), 'at the next visit')
    c.eval("window.__api=[]")
    check(aeval(read) == len(png) and not [a for a in c.eval("window.__api") if '/file/' in a],
          'the same bytes, and the station is not asked for the file')
    c.eval("var i=document.createElement('img');i.id='kept-img';i.src='/api/xprs/file/%s?session=x';document.body.appendChild(i)" % ref)
    check(c.wait("(function(){var i=document.getElementById('kept-img');return i.src.indexOf('blob:')===0&&i.naturalWidth===1;})()", 5)
          and not [a for a in c.eval("window.__api") if '/file/' in a], 'a picture of it is drawn from the kept bytes')

    print('the install entry')
    check(c.eval("XPRS_REMOTE.install.state()") in ('no', 'ask'), 'a desktop: the browser\'s own offer, or none')
    check(c.eval("document.getElementById('instbtn').style.display") ==
          ('' if c.eval("XPRS_REMOTE.install.state()") == 'ask' else 'none'), 'and the menu entry follows it')
    c.send('Emulation.setUserAgentOverride', {'userAgent': 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) '
           'AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Mobile/15E148 Safari/604.1'})
    # (Headless Chrome may still make its own offer, which an iPhone never does.)
    check(go() and c.eval("XPRS_REMOTE.install.state()") in ('ios', 'ask'), 'an iPhone: only its Share sheet installs',
          c.eval("XPRS_REMOTE.install.state()"))
    ios = c.eval("XPRS_REMOTE.install.state()") == 'ios'
    check(c.eval("document.getElementById('instbtn').style.display") == '', 'the menu offers Install as an app')
    c.eval("window.__said='';window.alert=function(t){window.__said=t;};installApp()")
    check(not ios or 'Add to Home Screen' in (c.eval("window.__said") or ''), 'and says how', c.eval("window.__said"))
finally:
    c.close()
    station.terminate()
    site.shutdown()
    shutil.rmtree(TREE, ignore_errors=True)
sys.exit(1 if fails else 0)
