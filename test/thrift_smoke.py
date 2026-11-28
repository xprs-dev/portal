#!/usr/bin/env python3
"""Thrift (the page over a Reticulum link, here ?thrifty=1 over HTTP).

    python3 tool/build.py && python3 test/thrift_smoke.py

  - on a station's own network nothing changed: the listing is read whole;
  - thrifty, a repeated read asks only for what is newer (since=) and gets
    no rows while nothing was said;
  - a packet that arrives is drawn at the next ask, and sent once (after=);
  - what was read stays in the browser: with the station's history blocked,
    a reload still draws the conversation and the blog;
  - a return visit asks by since= from its first ask: nothing read twice.
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
PROF = os.path.expanduser('~/snap/chromium/common/webchat-thrift-prof' if BROWSER == 'chromium'
                          else '~/.cache/webchat-thrift-prof')
PORT = 8792
URL = 'http://127.0.0.1:%d/' % PORT
fails = 0


def check(ok, what, extra=None):
    global fails
    print(('  [PASS] ' if ok else '  [FAIL] ') + what + (('  -- ' + str(extra)) if (extra and not ok) else ''))
    fails += 0 if ok else 1


def get(path):
    return json.loads(urllib.request.urlopen(URL + path, timeout=5).read())


def post(path, body=None):
    return urllib.request.urlopen(urllib.request.Request(URL + path, data=json.dumps(body or {}).encode()),
                                  timeout=5).read()


def chat_asks():
    return [a for a in get('__asks') if 'kind=message%2Creaction%2Cstatus' in a['q'] or
            'kind=message,reaction,status' in a['q']]


env = dict(os.environ)
env['MOCK_FORUM'] = '1'
station = subprocess.Popen([sys.executable, os.path.join(ROOT, 'contract', 'mock_station.py'),
                            str(PORT)], env=env)
time.sleep(1)
c = Cdp(BROWSER, PROF)
drawn = "document.getElementById('msgs').textContent.indexOf('hello from the mock')>=0"
try:
    c.attach()
    c.classic()

    print('on the station\'s own network')
    c.load(URL)
    check(c.wait(drawn), 'the conversation is drawn')
    time.sleep(4)
    a = chat_asks()
    check(len(a) >= 2 and all(x['since'] == '' for x in a), 'every read is the whole listing, as before', a[:3])
    check(c.eval("THRIFTY") is False and c.eval("tabMs('chat')") == 3000, 'the chat asks every three seconds')

    print('thrifty: the first visit')
    post('__asks_clear')
    c.load(URL + '?thrifty=1')
    check(c.wait(drawn), 'the conversation is drawn')
    check(c.eval("THRIFTY") is True and c.eval("tabMs('chat')") == 20000, 'the chat asks every twenty seconds')
    time.sleep(1)
    a = chat_asks()
    check(len(a) == 1 and a[0]['since'] == '' and a[0]['rows'] >= 1, 'read whole once', a)
    check(c.wait("!!sess", 10), 'the visitor proves their key')
    c.eval("tick()")
    time.sleep(1)
    a = chat_asks()
    check(len(a) == 2 and a[1]['since'] == '' and 'session=' in a[1]['q'],
          'and once more with the session, for the mail it adds', a)
    for _ in range(3):
        c.eval("tick()")
        time.sleep(0.6)
    a = chat_asks()
    check(len(a) == 5 and all(x['since'].isdigit() and x['rows'] <= 1 for x in a[2:]),
          'asked again and again: only what is newer, and next to nothing comes back', a)
    post('__row', {'id': 'n00001', 'ts': int(time.time()), 'bearer': 'lora', 'rssi': -71, 'from': 'X1NEW1',
                   'to': '', 'type': 'message', 'sig': 'verified', 'own': False,
                   'wire': 't:message f:X1NEW1 ts:2026-10-15_09:30:00 scope:local m:just arrived over the hill'})
    c.eval("tick()")
    check(c.wait("document.getElementById('msgs').textContent.indexOf('just arrived over the hill')>=0", 5),
          'a packet that arrives is drawn at the next ask')
    # The station files it once and tells it once (cursor / after): the
    # asks that follow reach back five minutes by since= and get nothing.
    post('__asks_clear')
    for _ in range(3):
        c.eval("tick()")
        time.sleep(0.6)
    a = chat_asks()
    check(len(a) == 3 and all('after=' in x['q'] for x in a) and sum(x['rows'] for x in a) == 0,
          'and is not sent again at the asks that follow', a)
    check(c.eval("document.querySelectorAll('#msgs .msg').length") ==
          c.eval("(function(){var s={},n=0,m=document.querySelectorAll('#msgs .msg');"
                 "for(var i=0;i<m.length;i++){var k=m[i].getAttribute('data-id');if(!s[k]){s[k]=1;n++;}}return n;})()"),
          'each message is drawn once')
    c.eval("switchRoom('blog')")
    check(c.wait("document.querySelectorAll('#msgs .post').length>=1"), 'the blog is drawn')
    posts = c.eval("document.querySelectorAll('#msgs .post').length")
    c.eval("switchRoom('local')")
    time.sleep(1.5)   # the listings reach IndexedDB

    print('thrifty: the station does not answer')
    c.send('Network.setBlockedURLs', {'urls': ['*leaflet*', '*api/xprs/history*']})
    c.load(URL + '?thrifty=1')
    check(c.wait(drawn, 6), 'the conversation is drawn from what the browser kept')
    check(c.eval("document.getElementById('msgs').textContent.indexOf('just arrived over the hill')>=0"),
          'with the packet that arrived last')
    c.eval("switchRoom('blog')")
    check(c.wait("document.querySelectorAll('#msgs .post').length===%d" % posts, 6), 'and the blog, post for post')

    print('thrifty: a return visit')
    c.send('Network.setBlockedURLs', {'urls': ['*leaflet*']})
    post('__asks_clear')
    c.load(URL + '?thrifty=1')
    check(c.wait(drawn, 6), 'the conversation is drawn')
    time.sleep(2)
    a = chat_asks()
    check(len(a) >= 1 and all(x['since'].isdigit() for x in a), 'its first ask is by since=: nothing read twice', a)
    every = get('__asks')
    whole = [x for x in every if x['since'] == '' and 'room=' in x['q'] and 'kind=reaction' not in x['q']]
    check(not whole, 'and so are the rooms\' own', whole)
    got = sum(x['rows'] for x in every)
    check(got <= 6, 'the station sent %d rows in all' % got, [x for x in every if x['rows']])
finally:
    c.close()
    station.terminate()
sys.exit(1 if fails else 0)
