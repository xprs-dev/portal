#!/usr/bin/env python3
"""A section says it is looking until the station answered, never that it is
empty before (headless Chromium against the mock, its answers held back).

    python3 tool/build.py && python3 test/look_smoke.py [SHOTS_DIR]

Over Reticulum (xprs.dev/in/<callsign>) an answer takes seconds. A group
said "No messages here yet", the Forum "No categories yet" and the Gallery
"needs storage: this one has none" for those seconds, then showed what
there was. Each is opened here with getJSON held, checked to say "Looking
for ...", then released and checked to show what the station has, or that
there is nothing, only then.
"""
import base64
import os
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from cdp import Cdp  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BROWSER = os.environ.get('WEBCHAT_BROWSER', 'chromium')
PROF = os.path.expanduser('~/snap/chromium/common/webchat-look-prof' if BROWSER == 'chromium'
                          else '~/.cache/webchat-look-prof')
PORT = 8787
SHOTS = sys.argv[1] if len(sys.argv) > 1 else None
fails = 0


def check(ok, what, extra=None):
    global fails
    print(('  [PASS] ' if ok else '  [FAIL] ') + what + (('  -- ' + str(extra)) if (extra and not ok) else ''))
    fails += 0 if ok else 1


env = dict(os.environ)
env['MOCK_FORUM'] = '1'
station = subprocess.Popen([sys.executable, os.path.join(ROOT, 'contract', 'mock_station.py'),
                            str(PORT)], env=env)
time.sleep(1)
c = Cdp(BROWSER, PROF)
LOOK = "document.getElementById('msgs').getAttribute('data-look')"
NONE = "document.getElementById('msgs').hasAttribute('data-none')"
TEXT = "document.getElementById('msgs').innerText"


def shot(name):
    if not SHOTS:
        return
    os.makedirs(SHOTS, exist_ok=True)
    with open(os.path.join(SHOTS, name + '.png'), 'wb') as f:
        f.write(base64.b64decode(c.send('Page.captureScreenshot')['data']))


try:
    c.attach()
    c.send('Emulation.setDeviceMetricsOverride',
           {'width': 360, 'height': 740, 'deviceScaleFactor': 2, 'mobile': True})
    c.load('http://127.0.0.1:%d/' % PORT)
    c.wait("canSign()&&svcKnown&&roomsLoaded&&chatLoaded&&roomReady.social", 15)
    # Answers held back until release(): what a slow link is, made exact.
    c.eval("var _gj=getJSON,_held=[];getJSON=function(u,cb,ms){_held.push(function(){_gj(u,cb,ms);});};"
           "function release(){var h=_held;_held=[];h.forEach(function(f){f();});}")

    print('a conversation')
    c.eval("followGroup('QUIETGRP',true);switchRoom('o:QUIETGRP')")
    check(c.eval(LOOK) == 'Looking for messages…', 'a group just opened is being looked for', c.eval(LOOK))
    check(not c.eval(NONE), 'and does not say it is empty')
    shot('look_group')
    c.eval("release()")
    check(c.wait(NONE + '&&!' + LOOK, 5), 'empty is said once the station answered')
    shot('none_group')
    c.eval("switchRoom('local');switchRoom('o:QUIETGRP')")
    check(c.eval(NONE + '&&!' + LOOK), 'and at once when it is opened again')
    c.eval("render({ts:%d,from:'X1OLDY',to:'QUIETGRP',type:'message',sig:'verified',"
           "wire:'t:message f:X1OLDY d:QUIETGRP ts:q m:first words'})" % int(time.time()))
    check(c.eval('!' + NONE + '&&!' + LOOK), 'a message ends both')

    print('the feeds')
    c.eval("release();blogLoaded=false;alertsLoaded=false;switchRoom('blog')")
    check(c.eval(LOOK) == 'Looking for posts…' and 'No posts' not in (c.eval(TEXT) or ''),
          'the Blog is looked for, not empty', c.eval(TEXT))
    c.eval("release()")
    check(c.wait('!' + LOOK + "&&blogLoaded", 5), 'then shows what the station has')
    c.eval("switchRoom('local');switchRoom('blog')")
    check(c.eval('!' + LOOK + "&&document.getElementById('msgs').children.length>0"),
          'opened again it shows the last answer at once')
    c.eval("release();switchRoom('alerts')")
    check(c.eval(LOOK) == 'Looking for alerts…' and 'No active' not in (c.eval(TEXT) or ''),
          'Alerts are looked for, not "No active alerts"', c.eval(TEXT))
    c.eval("release()")
    check(c.wait('!' + LOOK + "&&alertsLoaded", 5), 'then answered')

    print('the Forum and the Gallery')
    c.eval("release();roomsLoaded=false;hostedRooms=[];switchRoom('forum')")
    check(c.eval(LOOK) == 'Looking for categories…' and 'No categories' not in (c.eval(TEXT) or ''),
          'the Forum is looked for, not "No categories yet"', c.eval(TEXT))
    shot('look_forum')
    c.eval("release()")
    check(c.wait("document.querySelectorAll('#msgs .cat').length>0&&!" + LOOK, 5), 'then its categories')
    c.eval("release();switchRoom('f:X5F0RM')")
    check(c.eval(LOOK) == 'Looking for topics…' and 'No topics' not in (c.eval(TEXT) or ''),
          'a category is looked for, not "No topics yet"', c.eval(TEXT))
    c.eval("release()")
    check(c.wait("/balun/i.test(document.getElementById('msgs').innerText)&&!" + LOOK, 5), 'then its topics', c.eval(TEXT))
    c.eval("release();svcKnown=false;canGallery=false;switchRoom('gallery')")
    check(c.eval(LOOK) == 'Looking for gallery…' and 'needs storage' not in (c.eval(TEXT) or ''),
          'the Gallery waits for the station\'s services, not "needs storage"', c.eval(TEXT))
    c.eval("getJSON=_gj;release();getJSON('/api/services',applyServices)")
    check(c.wait("svcKnown&&!" + LOOK + "&&document.getElementById('msgs').children.length>0", 5),
          'and draws when they came', c.eval(TEXT))
finally:
    c.close()
    station.terminate()
sys.exit(1 if fails else 0)
