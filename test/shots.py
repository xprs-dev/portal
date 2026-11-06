#!/usr/bin/env python3
"""Screenshots of the page's feeds and panels, for looking at them.

    python3 tool/build.py && python3 test/shots.py OUTDIR [phone|desktop|landscape]

Headless Chromium against the mock (MOCK_FORUM=1), claimed as administrator,
so every panel is reachable: the Blog with its post panel open, the Forum's
categories and the category panel, the Alerts with the alert panel, and
Administration.
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
PROF = os.path.expanduser('~/snap/chromium/common/webchat-shots-prof' if BROWSER == 'chromium'
                          else '~/.cache/webchat-shots-prof')
PORT = 8786
OUT = sys.argv[1]
MODES = sys.argv[2:] or ['desktop', 'phone', 'landscape']
os.makedirs(OUT, exist_ok=True)


def shot(c, name):
    png = base64.b64decode(c.send('Page.captureScreenshot')['data'])
    with open(os.path.join(OUT, name + '.png'), 'wb') as f:
        f.write(png)


def size(c, mode):
    w, h, mobile = {'desktop': (1100, 720, False), 'phone': (360, 740, True),
                    'landscape': (740, 360, True)}[mode]
    c.send('Emulation.setDeviceMetricsOverride',
           {'width': w, 'height': h, 'deviceScaleFactor': 2 if mobile else 1, 'mobile': mobile})


env = dict(os.environ)
env['MOCK_FORUM'] = '1'
station = subprocess.Popen([sys.executable, os.path.join(ROOT, 'contract', 'mock_station.py'),
                            str(PORT)], env=env)
time.sleep(1)
c = Cdp(BROWSER, PROF)
try:
    c.attach()
    for mode in MODES:
        size(c, mode)
        c.load('http://127.0.0.1:%d/' % PORT)
        c.wait("canSign()", 10)
        shot(c, mode + '_chat')
        c.eval("showTab('admin')")
        if c.wait("!!document.getElementById('ad-claim')", 5):
            c.eval("document.getElementById('ad-claim').click()")
        c.wait("isStationAdmin===true", 10)
        c.eval("showTab('chat');switchRoom('blog')")
        c.wait("blogs.length>0", 5)
        shot(c, mode + '_blog')
        c.eval("fabClick()")
        c.wait("!!document.getElementById('bl-title')")
        c.eval("document.getElementById('bl-title').value='Field day';document.getElementById('bl-text').value='The mast went up at nine.'")
        shot(c, mode + '_blog_panel')
        c.eval("closeComposer();switchRoom('forum')")
        c.wait("document.querySelectorAll('#msgs .cat').length>0", 5)
        shot(c, mode + '_forum')
        c.eval("fabClick()")
        c.wait("!!document.getElementById('fc-name')")
        shot(c, mode + '_forum_panel')
        c.eval("closeComposer();switchRoom('f:X5F0RM')")
        c.wait("document.getElementById('msgs').innerText.indexOf('balun')>=0", 5)
        shot(c, mode + '_category')
        c.eval("switchRoom('alerts')")
        c.wait("fabMode==='alert'", 5)
        c.eval("fabClick()")
        c.wait("!!document.getElementById('al-text')")
        shot(c, mode + '_alerts_panel')
        c.eval("closeComposer();showTab('admin')")
        time.sleep(1.5)
        shot(c, mode + '_admin')
        c.eval("showTab('chat');switchRoom('local');toggleMenu()")
        time.sleep(0.5)
        shot(c, mode + '_menu')
        c.eval("showTab('chat');switchRoom('local')")
finally:
    c.close()
    station.terminate()
print('shots in', OUT)
