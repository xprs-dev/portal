#!/usr/bin/env python3
"""Load the built page in headless Chromium against the mock station.

    python3 tool/build.py && python3 test/smoke.py

Two stations: one like the Android host (`page` in /api/services: only Chat
and Traffic, a Get the app link) and one like the boards today (no `page`: the
page shows everything it always did and no app link). Chromium is the snap
one, which can write only under ~/snap/chromium/common.
"""
import os
import shutil
import re
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# WEBCHAT_BROWSER=google-chrome where the snap Chromium cannot reach the mock
# (it renders a data: URL and dumps an empty page for 127.0.0.1).
BROWSER = os.environ.get('WEBCHAT_BROWSER', 'chromium')
PROF = os.path.expanduser('~/snap/chromium/common/webchat-prof' if BROWSER == 'chromium'
                          else '~/.cache/webchat-prof')


def dom(port):
    shutil.rmtree(PROF, ignore_errors=True)   # the page keeps its room and key in localStorage
    os.makedirs(PROF, exist_ok=True)
    return subprocess.run(
        [BROWSER, '--headless=new', '--no-sandbox', '--disable-gpu',
         '--user-data-dir=' + PROF, '--virtual-time-budget=6000', '--dump-dom',
         'http://127.0.0.1:%d/' % port],
        capture_output=True, text=True, timeout=90).stdout


def station(port, board, flood=False):
    env = dict(os.environ)
    if board:
        env['MOCK_BOARD'] = '1'
    if flood:
        env['MOCK_FLOOD'] = '1'
    p = subprocess.Popen([sys.executable, os.path.join(ROOT, 'contract', 'mock_station.py'),
                          str(port)], env=env)
    time.sleep(1)
    return p


fails = 0


def check(ok, what):
    global fails
    print(('  [PASS] ' if ok else '  [FAIL] ') + what)
    fails += 0 if ok else 1


for board, port in ((False, 8781), (True, 8782)):
    print('board station' if board else 'app host')
    p = station(port, board)
    try:
        d = dom(port)
    finally:
        p.terminate()
    check('hello from the mock' in d, 'a public row from /api/xprs/history is drawn')
    check('data-r="blog"' in d, 'the Feed lists Blog, under Social and Alerts')
    hidden = lambda t: bool(re.search(r'data-tab="%s"[^>]*style="display: none' % t, d))
    link = re.search(r'id="getapp" class="([^"]*)" href="([^"]*)"', d)
    admin_btn = re.search(r'id="adminbtn" style="([^"]*)"', d)
    if board:
        check(not hidden('devices'), 'every tab shows, as on the boards today')
        check(link is not None and 'hide' in link.group(1), 'no Get the app link')
        check('id="stcall" title="the station you are using">(X1BOARD)<' in d,
              'the title names the station, read from /api/status')
        check(admin_btn is not None and 'none' in admin_btn.group(1),
              'no Administration on a host that has none')
    else:
        check('id="stcall" title="the station you are using">(X3MOCK)<' in d,
              'the title names the station: XPRS (X3MOCK)')
        check(admin_btn is not None and 'none' not in admin_btn.group(1),
              'the menu offers Administration')
        check(hidden('devices'), 'a tab the host does not serve is hidden')
        check(not hidden('traffic'), 'a tab it serves stays')
        check(link is not None and link.group(1) == '' and link.group(2) == '/app',
              'Get the app links to the host\'s download page')
print('a station whose newest 200 messages are all one busy room')
p = station(8783, True, flood=True)
try:
    d = dom(8783)
finally:
    p.terminate()
check('hello from the mock' in d, 'the Local room still shows its archive (asked for by room=)')
check('settings</a>' not in d, 'no settings link under the chat')
sys.exit(1 if fails else 0)
