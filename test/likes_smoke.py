#!/usr/bin/env python3
"""Likes (XPRS.md 7.5) on everything that can be liked, in headless Chromium.

    python3 tool/build.py && python3 test/likes_smoke.py

  - a message has a heart on its bubble: a tap sends add:like, another
    remove:like, and the count follows at once;
  - a blog post has one on its card; the like is filed by the station and
    read back after a reload, counted once;
  - a forum topic and its comments have one each; the like names the
    category in d:, as a post to it does.
"""
import json
import os
import subprocess
import sys
import time
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from cdp import Cdp  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BROWSER = os.environ.get('WEBCHAT_BROWSER', 'chromium')
PROF = os.path.expanduser('~/snap/chromium/common/webchat-likes-prof' if BROWSER == 'chromium'
                          else '~/.cache/webchat-likes-prof')
PORT = 8791
URL = 'http://127.0.0.1:%d/' % PORT
fails = 0


def check(ok, what, extra=None):
    global fails
    print(('  [PASS] ' if ok else '  [FAIL] ') + what + (('  -- ' + str(extra)) if (extra and not ok) else ''))
    fails += 0 if ok else 1


def sent():
    return json.loads(urllib.request.urlopen(URL + '__sent', timeout=5).read())


env = dict(os.environ)
env['MOCK_FORUM'] = '1'
station = subprocess.Popen([sys.executable, os.path.join(ROOT, 'contract', 'mock_station.py'),
                            str(PORT)], env=env)
time.sleep(1)
c = Cdp(BROWSER, PROF)
try:
    c.attach()
    c.classic()
    c.load(URL)
    check(c.wait("canSign()", 10), 'the page has a key')

    print('a message')
    heart = "document.querySelector('#msgs .msg .likes')"
    check(c.wait("!!" + heart), 'a bubble carries a heart')
    check(c.eval(heart + ".textContent") == '♡', 'empty while nobody likes it')
    mid = c.eval("document.querySelector('#msgs .msg').getAttribute('data-id')")
    c.eval(heart + ".click()")
    check(c.wait(heart + ".textContent==='♥ 1'&&/\\bon\\b/.test(" + heart + ".className)"),
          'a tap: filled, counted, at once')
    check(c.wait("true") and any(w.startswith('t:reaction ') and ' add:like r:' + mid in w for w in sent()),
          'add:like went to the station, naming the message', sent()[-2:])
    c.eval(heart + ".click()")
    check(c.wait(heart + ".textContent==='♡'"), 'a second tap takes it back')
    time.sleep(0.5)
    check(any(w.startswith('t:reaction ') and ' remove:like r:' + mid in w for w in sent()),
          'remove:like went to the station')
    c.eval("showMsgMenu({clientX:10,clientY:10,stopPropagation:function(){}},'" + mid + "','X1ARKL',false)")
    check(c.eval("document.getElementById('msgmenu').textContent.indexOf('Like')>=0"), 'the menu still offers it')
    c.eval("document.getElementById('msgmenu').style.display='none'")

    print('a blog post')
    c.eval("switchRoom('blog')")
    btn = "document.querySelector('#msgs .post .likebtn')"
    check(c.wait("!!" + btn), 'a post carries a heart')
    pid = c.eval(btn + ".getAttribute('data-like')")
    c.eval(btn + ".click()")
    check(c.wait(btn + ".textContent==='♥ 1'&&/\\bon\\b/.test(" + btn + ".className)"), 'liked: filled and counted')
    time.sleep(0.5)
    w = [x for x in sent() if x.startswith('t:reaction ') and ' r:' + pid in x]
    check(len(w) == 1 and ' add:like' in w[0] and ' d:' not in w[0] and ' sig:' in w[0],
          'a signed add:like for the post, to everybody', w)
    c.eval("likesAt={};loadBlogFeed(true)")
    time.sleep(1.5)
    check(c.eval(btn + ".textContent") == '♥ 1', 'read back from the station, it is still one like')
    c.load(URL)
    c.eval("switchRoom('blog')")
    check(c.wait(btn + "&&" + btn + ".textContent==='♥ 1'&&/\\bon\\b/.test(" + btn + ".className)", 10),
          'after a reload the station says who liked it: one, and it is this visitor')
    # Somebody else likes it too.
    urllib.request.urlopen(urllib.request.Request(URL + '__row', data=json.dumps({
        'id': 'feed01', 'ts': int(time.time()), 'bearer': 'lora', 'rssi': -80, 'from': 'X1RD89', 'to': '',
        'type': 'reaction', 'sig': 'verified', 'own': False,
        'wire': 't:reaction f:X1RD89 ts:2026-10-15_09:00:00 add:like r:' + pid}).encode()), timeout=5)
    c.eval("likesAt={};loadBlogFeed(true)")
    check(c.wait(btn + ".textContent==='♥ 2'", 5), 'another person\'s like is counted beside it')

    print('a forum topic and a comment')
    c.eval("switchRoom('f:X5F0RM')")
    check(c.wait("!!document.querySelector('#msgs .post.topic')"), 'the category lists its topic')
    c.eval("document.querySelector('#msgs .post.topic').click()")
    check(c.wait("document.querySelectorAll('#msgs .post .likebtn').length===2"),
          'the topic and its comment carry a heart each')
    fid = c.eval("document.querySelectorAll('#msgs .post .likebtn')[1].getAttribute('data-like')")
    c.eval("document.querySelectorAll('#msgs .post .likebtn')[1].click()")
    fb = "document.querySelector('#msgs .post .likebtn[data-like=\"" + fid + "\"]')"
    check(c.wait(fb + ".textContent==='♥ 1'"), 'the comment is liked')
    time.sleep(0.5)
    w = [x for x in sent() if x.startswith('t:reaction ') and ' r:' + fid in x]
    check(len(w) == 1 and ' d:X5F0RM ' in w[0] and ' add:like' in w[0], 'the like names the category in d:', w)
    c.eval("likesAt={};loadForum(true)")
    check(c.wait(fb + "&&" + fb + ".textContent==='♥ 1'", 5), 'read back with the topic, still one')
finally:
    c.close()
    station.terminate()
sys.exit(1 if fails else 0)
