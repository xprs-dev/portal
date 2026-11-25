#!/usr/bin/env python3
"""The visitor's own portal, in headless Chromium, against two mock stations.

    python3 tool/build.py && python3 test/accounts_smoke.py

Station A is reached from the internet (MOCK_REMOTE: it keeps Local to its own
network); station B is a second archiver the page reaches the way xprs.dev
reaches one, through a stand-in window.XPRS_REMOTE (in/shell.js provides the
real one). Checks:
  - the page starts on Global where Local is private;
  - Accounts: the identity in use is listed, a new one is added and used, the
    first is used again, the second removed;
  - archivers: A offers and is declared, then B is added because it offers
    too, and both receive the signed t:mailbox hold:X3MOCK,X3ARCB;
  - mail kept by B is shown, and the receipt goes to B as well;
  - the Map view draws the stations and opens a private message from one;
  - an archiver on the map offers "Use this archiver" (the one in use says it
    is browsed from), so do the archivers in Accounts; the button asks the
    shell (XPRS_REMOTE.use) and the page opened next keeps the map's view.
"""
import json
import os
import subprocess
import sys
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from cdp import Cdp  # noqa: E402

ROOT = os.path.dirname(HERE)
A, B = 8785, 8786
PROF = os.path.expanduser('~/snap/chromium/common/webchat-acc-prof')
fails = 0


def check(ok, what):
    global fails
    print(('  [PASS] ' if ok else '  [FAIL] ') + what)
    fails += 0 if ok else 1


def station(port, call, remote):
    env = dict(os.environ, MOCK_CALL=call)
    if remote:
        env['MOCK_REMOTE'] = '1'
    return subprocess.Popen([sys.executable, os.path.join(ROOT, 'contract', 'mock_station.py'), str(port)], env=env)


def sent(port):
    with urllib.request.urlopen('http://127.0.0.1:%d/__sent' % port) as r:
        return json.loads(r.read())


def post(port, path, obj):
    req = urllib.request.Request('http://127.0.0.1:%d%s' % (port, path), data=json.dumps(obj).encode(), method='POST')
    with urllib.request.urlopen(req) as r:
        return r.read()


REMOTE = """window.XPRS_REMOTE={station:'X3MOCK',home:true,
 archivers:function(){return [{call:'X3ARCB',at:Math.floor(Date.now()/1000)-60}];},
 use:function(c){window.__used=c;return Promise.resolve(function(){sessionStorage.setItem('__went',c);});},
 ask:function(c,m,p,q,b){
   var u=(c==='X3ARCB'?'http://127.0.0.1:%d':'')+p+'?'+new URLSearchParams(q||{});
   return fetch(u,{method:m,body:b==null?undefined:b}).then(function(r){return r.text().then(function(t){
     var j=null;try{j=JSON.parse(t);}catch(e){}return {status:r.status,json:j,text:t};});});}};
window.prompt=function(){return 'x';};window.confirm=function(){return true;};""" % B

a, b = station(A, 'X3MOCK', True), station(B, 'X3ARCB', False)
time.sleep(1)
c = Cdp(os.environ.get('WEBCHAT_BROWSER', 'chromium'), PROF)
E = c.eval
try:
    c.attach()
    c.send('Page.addScriptToEvaluateOnNewDocument', {'source': REMOTE})
    c.load('http://127.0.0.1:%d/' % A)
    c.wait("typeof mycall!=='undefined'&&/^X1/.test(mycall)&&!!sess", 20)
    c.wait("curRoom==='global'", 15)
    check(E("curRoom") == 'global', 'Local is private from the internet: the page starts on Global')

    first = E("mycall")
    check(E("accList().map(function(a){return a.call}).join()") == first, 'the identity in use is listed under Accounts')
    c.wait("accHold().length>=2", 30)
    hold = E("accHold().join()")
    check(hold == 'X3MOCK,X3ARCB', 'A offered, then B offered too: archivers ' + hold)
    mb = lambda port: [w for w in sent(port) if w.startswith('t:mailbox ') and ' hold:X3MOCK,X3ARCB ' in w]
    for _ in range(20):
        if mb(A) and mb(B):
            break
        time.sleep(.5)
    check(len(mb(A)) >= 1 and len(mb(B)) >= 1, 'the signed t:mailbox reached both archivers: %d on A, %d on B' % (len(mb(A)), len(mb(B))))
    if not (mb(A) and mb(B)):
        print('    A got', [w[:70] for w in sent(A) if w.startswith('t:mailbox')], 'B got', [w[:70] for w in sent(B) if w.startswith('t:mailbox')])
    check(any(w.startswith('t:identity f:' + first) for w in sent(B)), 'B was told the identity first')
    check(E("JSON.parse(localStorage.getItem('xprs_hold')).join()") == hold, 'xprs_hold says where the shell opens /in/ next time')

    # Mail that only B keeps.
    post(B, '/__inject', {'from': 'X1PEER', 'to': first, 'wire': 't:message f:X1PEER d:%s ts:2026-11-25_10:00:00 m:kept by B' % first})
    E("otherMail()")
    c.wait("!!dmPeers['X1PEER']", 15)
    E("switchRoom('dm:X1PEER')"); time.sleep(1)
    check('kept by B' in E("el('msgs').innerText"), 'mail kept by the second archiver is shown')
    time.sleep(2)
    check(any(w.startswith('t:receipt f:' + first) for w in sent(B)), 'and its receipt goes to that archiver')

    E("openView('accounts')"); time.sleep(.5)
    check('X3ARCB' in E("el('v-accounts').innerText"), 'Accounts shows the archivers')
    E("accNew()"); time.sleep(.5)
    second = E("mycall")
    check(second != first and E("accList().length") == 2, 'a new identity is added and used: ' + second)
    E("accUse('%s')" % first); time.sleep(.5)
    check(E("mycall") == first, 'the first is used again')
    check(E("accHold().join()") == hold, 'with its own archivers')
    E("accDrop('%s')" % second); time.sleep(.3)
    check(E("accList().length") == 1, 'the second is removed')

    # A person whose archivers were chosen on another device: only B knows
    # (12.9.5). A, which does not, offers itself; the page asks the other
    # archivers first, takes the person's own list and declares nothing.
    third = E("(function(){var k=randKey();window.__k3=k;return callsignFromNpub(npubEncode(pubkeyX(k)));})()")
    post(B, '/__mailbox', {'call': third, 'hold': ['X3ARCB', 'X3FAR1']})
    E("stSet('xprs_ext','0');useKey(window.__k3);accFresh()")
    c.wait("mycall==='%s'&&accHold().join()==='X3ARCB,X3FAR1'" % third, 40)
    check(E("accHold().join()") == 'X3ARCB,X3FAR1', 'a new browser finds the person\'s archivers on another archiver: ' + E("accHold().join()"))
    check(E("JSON.parse(localStorage.getItem('xprs_hold')).join()") == 'X3ARCB,X3FAR1', 'and the shell opens /in/ on them next time')
    time.sleep(2)
    check(not [w for w in sent(A) + sent(B) if w.startswith('t:mailbox f:' + third)],
          'no mailbox is declared over the person\'s own')
    # Known to the station in use: taken from the session at once.
    fourth = E("(function(){var k=randKey();window.__k4=k;return callsignFromNpub(npubEncode(pubkeyX(k)));})()")
    post(A, '/__mailbox', {'call': fourth, 'hold': ['X3FAR2']})
    E("useKey(window.__k4);accFresh()")
    c.wait("mycall==='%s'&&accHold().join()==='X3FAR2'" % fourth, 40)
    check(E("accHold().join()") == 'X3FAR2', 'the station in use names the person\'s archivers: taken as they are')
    E("accUse('%s')" % first); time.sleep(1)
    check(E("mycall") == first and E("accHold().join()") == hold, 'the first identity keeps its own archivers')

    # The map: an identity with a place and a key, and one hiding its digits.
    E("""(function(){var k=new Uint8Array(32);k[31]=9;var n=npubEncode(pubkeyX(k)),now=Math.floor(Date.now()/1000);
      [{ts:now-30,type:'identity',from:'X1MAPA',to:'',sig:'verified',wire:'t:identity f:X1MAPA ts:x nick:Ana pos:49.41,8.69 acc:100 k:'+n+' sig:x'},
       {ts:now-60,type:'identity',from:'X1MAPB',to:'',sig:'verified',wire:'t:identity f:X1MAPB ts:x pos:49\\u2588\\u2588,8\\u2588\\u2588 acc:100000 sig:x'}]
      .forEach(function(r){fetch('/__row',{method:'POST',body:JSON.stringify(r)});});})()""")
    time.sleep(.5)
    E("mapAskedAt=0;openView('map')")
    ok = c.wait("!!mapByCall('X1MAPA')&&!!mapByCall('X1MAPB')&&!!document.querySelector('.leaflet-container')", 30)
    check(ok, 'the Map view draws: ' + E("(el('mapcount')||{}).textContent"))
    check(E("document.querySelectorAll('.mapcnt').length") >= 1, 'a station hiding its digits shares a square marker')
    check(E("!!document.querySelector('#maplist [onclick*=X1MAPA]')"), 'a station with a key has Message')
    E("mapWrite('X1MAPA')"); time.sleep(.5)
    check(E("curRoom") == 'dm:X1MAPA' and E("tab") == 'chat', 'Message opens the private conversation')

    # Another archiver as the base: from the map, and from Accounts.
    E("""(function(){var now=Math.floor(Date.now()/1000);
      [{ts:now-20,type:'service',from:'X3ARCB',to:'',wire:'t:service f:X3ARCB ts:x serve:archive,relay pos:48.13,11.57 acc:1000'},
       {ts:now-25,type:'service',from:'X3MOCK',to:'',wire:'t:service f:X3MOCK ts:x serve:archive pos:38.72,-9.14 acc:1000'}]
      .forEach(function(r){fetch('/__row',{method:'POST',body:JSON.stringify(r)});});})()""")
    time.sleep(.5)
    E("mapAskedAt=0;openView('map')")
    c.wait("!!mapByCall('X3ARCB')&&!!mapMarks['X3ARCB']", 30)
    check('Use this archiver' in E("mapPop(mapByCall('X3ARCB'))"), 'an archiver on the map offers "Use this archiver"')
    check('Browsing from here' in E("mapPop(mapByCall('X3MOCK'))"), 'the archiver in use says it is browsed from')
    check(E("mapMarks['X3MOCK'].options.color") == '#FFC107', 'and its marker stands out')
    E("openView('accounts')"); time.sleep(.5)
    check(E("!!document.querySelector('#v-accounts button[onclick*=\"baseSwitch(\\'X3ARCB\"]')"), 'Accounts: Use beside the other archiver')
    check(not E("!!document.querySelector('#v-accounts button[onclick*=\"baseSwitch(\\'X3MOCK\"]')"), 'never beside the one in use')
    E("openView('map')"); time.sleep(.5)
    E("mapObj.setView([48.1,11.5],8);mapFocus('X3ARCB')"); time.sleep(1)
    E("document.querySelector('.leaflet-popup button.mapall').click()")
    c.wait("sessionStorage.getItem('__went')==='X3ARCB'", 10)
    check(E("window.__used") == 'X3ARCB', 'the button asks the shell to use X3ARCB')
    kept = E("sessionStorage.getItem('xprs.in.view')") or ''
    check('"z":' in kept, 'the map view is kept for the page opened next: ' + kept)
    E("location.reload()")
    c.wait("typeof mapObj!=='undefined'&&!!mapObj", 30)
    check(E("mapObj.getZoom()") >= 8 and abs(E("mapObj.getCenter().lat") - 48.13) < 1,
          'the page opened again shows the map where it was')
finally:
    c.close()
    a.terminate()
    b.terminate()
print('ALL PASS' if not fails else '%d FAILED' % fails)
sys.exit(1 if fails else 0)
