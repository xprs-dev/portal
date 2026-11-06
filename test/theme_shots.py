#!/usr/bin/env python3
"""One screenshot per theme (page/chat_page.html THEMES), for looking at them.

    python3 tool/build.py && python3 test/theme_shots.py OUTDIR [desktop|phone]
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
PROF = os.path.expanduser('~/snap/chromium/common/webchat-theme-prof' if BROWSER == 'chromium'
                          else '~/.cache/webchat-theme-prof')
PORT = 8787
OUT = sys.argv[1]
MODES = sys.argv[2:] or ['desktop']
os.makedirs(OUT, exist_ok=True)
env = dict(os.environ)
env['MOCK_FORUM'] = '1'
station = subprocess.Popen([sys.executable, os.path.join(ROOT, 'contract', 'mock_station.py'),
                            str(PORT)], env=env)
time.sleep(1)
c = Cdp(BROWSER, PROF)
try:
    c.attach()
    for mode in MODES:
        w, h, mobile = (1100, 720, False) if mode == 'desktop' else (360, 740, True)
        c.send('Emulation.setDeviceMetricsOverride',
               {'width': w, 'height': h, 'deviceScaleFactor': 2 if mobile else 1, 'mobile': mobile})
        c.load('http://127.0.0.1:%d/' % PORT)
        c.wait("canSign()", 10)
        c.eval("adminSet({page_banner:'<b>Hill station</b>: on air from the ridge, weekdays after six.'})")
        c.eval("switchRoom('local')")
        for m in ('Anyone copy the net tonight?', 'Mast is up, 40 m dipole, listening on the usual.',
                  'Road to the ridge is clear again, took the bike up.'):
            c.eval("(document.getElementById('txt').value=%r,sendMsg())" % m)
            time.sleep(0.6)
        time.sleep(1.5)
        n = c.eval("THEMES.length")
        for i in range(n):
            name = c.eval("THEMES[%d].name" % i).lower().replace(' ', '_')
            c.eval("applyCss(THEMES[%d].css)" % i)
            time.sleep(0.4)
            png = base64.b64decode(c.send('Page.captureScreenshot')['data'])
            with open(os.path.join(OUT, '%s_%s.png' % (mode, name)), 'wb') as f:
                f.write(png)
finally:
    c.close()
    station.terminate()
print('shots in', OUT)
