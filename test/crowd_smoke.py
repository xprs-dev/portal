#!/usr/bin/env python3
"""Thousands of stations in one area, in headless Chromium against the mock.

    python3 tool/build.py && python3 test/crowd_smoke.py

1500 stations that state only their 100 km square, 100 archivers and 150 on
solar power among them (t:service serve:archive, source:solar), and one old
station past the pages the map reads. Checks:
  - the map reads older pages (history until=) beyond the newest 200;
  - the square is one marker with the count, drawn quickly;
  - its popup names the freshest six and offers "Show all N here", which
    opens the station list filtered to that square, 50 at a time, freshest
    first;
  - chips filter by what stations announce (Archivers, Solar);
  - a callsign the map does not know is asked for by name.
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
PORT = 8787
PROF = os.path.expanduser('~/snap/chromium/common/webchat-crowd-prof')
SHOTS = os.environ.get('SHOTS', '')
fails = 0


def check(ok, what):
    global fails
    print(('  [PASS] ' if ok else '  [FAIL] ') + what)
    fails += 0 if ok else 1


B = '█'
now = int(time.time())
rows = []
for i in range(1500):
    call = 'X1%04d' % i
    rows.append({'ts': now - 60 * i, 'type': 'identity', 'from': call, 'to': '', 'sig': 'verified',
                 'wire': 't:identity f:%s ts:x nick:n%d pos:49%s,8%s acc:100000 sig:x' % (call, i, B * 5, B * 5)})
    if i % 15 == 0:
        rows.append({'ts': now - 60 * i - 1, 'type': 'service', 'from': call, 'to': '', 'sig': 'verified',
                     'wire': 't:service f:%s serve:relay,archive count:100 ts:x sig:x' % call})
    elif i % 10 == 0:
        rows.append({'ts': now - 60 * i - 1, 'type': 'service', 'from': call, 'to': '', 'sig': 'verified',
                     'wire': 't:service f:%s serve:relay source:solar ts:x sig:x' % call})
rows.append({'ts': now - 9000000, 'type': 'identity', 'from': 'X1OLDY', 'to': '', 'sig': 'verified',
             'wire': 't:identity f:X1OLDY ts:x nick:Oldtimer pos:38.7,-9.1 acc:100 sig:x'})

mock = subprocess.Popen([sys.executable, os.path.join(ROOT, 'contract', 'mock_station.py'), str(PORT)])
time.sleep(1)
urllib.request.urlopen(urllib.request.Request('http://127.0.0.1:%d/__rows' % PORT,
                                              data=json.dumps(rows).encode(), method='POST')).read()
c = Cdp(os.environ.get('WEBCHAT_BROWSER', 'chromium'), PROF)
E = c.eval
try:
    c.attach()
    c.send('Emulation.setDeviceMetricsOverride', {'width': 412, 'height': 860, 'deviceScaleFactor': 2, 'mobile': True})
    c.load('http://127.0.0.1:%d/' % PORT)
    c.wait("typeof mapui!=='undefined'&&mapui&&mapAll.length>0", 30)
    c.wait("mapAll.length>=1500", 90)
    n = E("mapAll.length")
    check(n >= 1500, 'older pages read past the newest 200: %d stations known' % n)
    ms = E("(function(){var t=performance.now();mapDraw(mapRows);return Math.round(performance.now()-t);})()")
    check(ms < 400, 'all of them drawn in %d ms' % ms)
    cnt = E("Array.prototype.map.call(document.querySelectorAll('.mapcnt'),function(e){return e.textContent}).join()")
    check(len(cnt.split(',')) == 1 and cnt == '1.5k', 'one marker for the square: ' + cnt)
    E("document.querySelector('.mapcnt').click()"); time.sleep(1)
    names = E("document.querySelectorAll('.leaflet-popup-content hr').length")
    check(names <= 7, 'its popup names a few, not hundreds (%d dividers)' % names)
    check('Show all' in E("document.querySelector('.leaflet-popup-content').innerText"), 'and offers Show all')
    if SHOTS:
        open(os.path.join(SHOTS, 'crowd_popup.png'), 'wb').write(__import__('base64').b64decode(c.send('Page.captureScreenshot')['data']))
    E("document.querySelector('.mapall').click()"); time.sleep(1)
    check(E("tab") == 'map' and E("!!mapFilter.area"), 'Show all opens the list filtered to that square')
    check(E("document.querySelectorAll('#maplist .maprow').length") == 50, '50 at a time')
    first = E("document.querySelector('#maplist .maprow b').textContent")
    check(first == 'X10000', 'the freshest first: ' + first)
    chips = E("document.getElementById('mapchips').innerText.replace(/\\n/g,' ')")
    check('Archivers' in chips and 'Solar' in chips, 'chips from what they announce: ' + chips)
    if SHOTS:
        open(os.path.join(SHOTS, 'crowd_list.png'), 'wb').write(__import__('base64').b64decode(c.send('Page.captureScreenshot')['data']))
    E("mapTag('source:solar')"); time.sleep(.3)
    solar = E("mapAll.filter(mapMatch).length")
    check(solar > 0 and E("mapAll.filter(mapMatch).every(function(s){return s.source==='solar'})"), 'Solar keeps only solar stations: %d' % solar)
    E("mapTag('source:solar');mapArea('');var i=el('mapgo');i.value='X1OLDY';i.dispatchEvent(new Event('input'));"
      "i.dispatchEvent(new KeyboardEvent('keydown',{key:'Enter'}))")
    ok = c.wait("!!mapByCall('X1OLDY')", 15)
    check(ok, 'a callsign the map does not know is asked for by name')
finally:
    c.close()
    mock.terminate()
print('ALL PASS' if not fails else '%d FAILED' % fails)
sys.exit(1 if fails else 0)
