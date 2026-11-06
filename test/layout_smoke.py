#!/usr/bin/env python3
"""The composer stays on screen on a phone, whatever lies over the page.

    python3 tool/build.py && python3 test/layout_smoke.py [screenshot dir]

Some Android phones covered the message field with a bar, and nobody could
type. Three ways it happens, each emulated here in headless Chrome against
the mock station, driven over the DevTools protocol on a pipe (fds 3 and 4,
NUL-separated JSON), so no websocket module is needed:

  - a browser that draws under the navigation bar and says so (safe-area
    insets, with viewport-fit=cover);
  - a toolbar lying over the bottom of the page (the visual viewport is
    shorter than the layout one);
  - a WebView drawn under the bars that reports no inset (the page is as tall
    as the screen).

google-chrome, not the snap Chromium (it cannot reach 127.0.0.1).
"""
import base64
import os
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BROWSER = os.environ.get('WEBCHAT_BROWSER', 'google-chrome')
PROF = os.path.expanduser('~/.cache/webchat-layout-prof')
PORT = 8784
SHOTS = sys.argv[1] if len(sys.argv) > 1 else None


from cdp import Cdp

fails = 0


def check(ok, what):
    global fails
    print(('  [PASS] ' if ok else '  [FAIL] ') + what)
    fails += 0 if ok else 1


def shot(c, name):
    if not SHOTS:
        return
    png = base64.b64decode(c.send('Page.captureScreenshot')['data'])
    with open(os.path.join(SHOTS, 'layout_%s.png' % name), 'wb') as f:
        f.write(png)


def phone(c, height=740, screen=800):
    c.send('Emulation.setDeviceMetricsOverride',
           {'width': 360, 'height': height, 'deviceScaleFactor': 3, 'mobile': True,
            'screenWidth': 360, 'screenHeight': screen})
    c.send('Emulation.setTouchEmulationEnabled', {'enabled': True, 'maxTouchPoints': 5})


def load(c):
    c.send('Page.navigate', {'url': 'http://127.0.0.1:%d/' % PORT})
    for _ in range(100):
        if c.eval("document.readyState==='complete'&&!!document.getElementById('txt')"):
            break
        time.sleep(0.1)
    time.sleep(1.0)


# Where the message field ends, against what is visible.
FIELD = "document.getElementById('txt').getBoundingClientRect().bottom"

station = subprocess.Popen([sys.executable, os.path.join(ROOT, 'contract', 'mock_station.py'),
                            str(PORT)])
time.sleep(1)
c = Cdp(BROWSER, PROF)
try:
    c.attach()

    print('a phone, nothing over the page')
    phone(c)
    load(c)
    bottom, ih = c.eval(FIELD), c.eval('innerHeight')
    check(bottom is not None and bottom <= ih, 'the field ends on screen (%s <= %s)' % (bottom, ih))
    check(c.eval('scrollY') == 1, 'the document is still parked at 1 (pull-to-refresh)')
    shot(c, 'plain')

    print('drawn under a 48 px navigation bar, inset reported')
    try:
        c.send('Emulation.setSafeAreaInsetsOverride', {'insets': {'bottom': 48, 'top': 24}})
        load(c)
        bottom, ih = c.eval(FIELD), c.eval('innerHeight')
        check(bottom <= ih - 48, 'the field ends above the bar (%s <= %s)' % (bottom, ih - 48))
        shot(c, 'inset')
        c.send('Emulation.setSafeAreaInsetsOverride', {'insets': {}})
    except RuntimeError as e:
        print('  [SKIP] this Chrome cannot emulate safe-area insets (%s)' % e)

    print('a toolbar lying over the bottom 140 px')
    phone(c)
    load(c)
    c.eval("Object.defineProperty(visualViewport,'height',{get:function(){return 600},"
           "configurable:true});dispatchEvent(new Event('resize'));1")
    time.sleep(0.3)
    bottom = c.eval(FIELD)
    check(bottom <= 600, 'the field ends above the toolbar (%s <= 600)' % bottom)
    check(c.eval('scrollY') == 1, 'still parked after the resize')
    shot(c, 'toolbar')

    print('a WebView as tall as the screen, no inset reported')
    phone(c, height=800, screen=800)
    load(c)
    bottom, ih = c.eval(FIELD), c.eval('innerHeight')
    check(bottom <= ih - 48, 'the field ends above where the bar is (%s <= %s)' % (bottom, ih - 48))
    shot(c, 'edge')

    print('a desktop window: no guessed bar')
    c.send('Emulation.clearDeviceMetricsOverride')
    c.send('Emulation.setTouchEmulationEnabled', {'enabled': False})
    c.send('Emulation.setDeviceMetricsOverride',
           {'width': 1200, 'height': 800, 'deviceScaleFactor': 1, 'mobile': False})
    load(c)
    check(c.eval("document.documentElement.style.getPropertyValue('--sab')") == '',
          'no inset guessed')
finally:
    c.close()
    station.terminate()
sys.exit(1 if fails else 0)
