#!/usr/bin/env python3
"""A station that speaks just enough of spec/API-HTTP.md for the web chat.

    python3 contract/mock_station.py [port]

Serves dist/chat_page.html at / (gzipped, as both editions do), the
/api/services answer an app host gives (`page.tabs`, `page.app`), a history of
public rows, and POST /api/xprs/send, which it records. It exists so the page
can be tested without a board and without a phone.
"""
import gzip
import json
import os
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SENT = []
ROWS = [{
    'ts': int(time.time()) - 60, 'bearer': 'lan', 'rssi': 0, 'from': 'X1ARKL',
    'to': '', 'type': 'message', 'sig': 'verified', 'own': False,
    'wire': 't:message f:X1ARKL ts:2026-10-15_09:00:00 scope:local m:hello from the mock',
}]
SERVICES = {'ok': True, 'station': 'X3MOCK', 'features': {}, 'serve': [],
            'page': {'tabs': ['chat', 'traffic'], 'config': False, 'app': '/app',
                     'session': True, 'admin': True}}
# /api/admin (the rules are WebChatApi's, tested in the core; this answers
# the shapes). MOCK_REMOTE makes every visitor one from the internet.
ADMIN = {'call': None}
SETTINGS = {'local_private': True, 'who_may_post': 'everyone'}
LOCAL = not os.environ.get('MOCK_REMOTE')


def admin_state(token):
    call = SESSIONS.get(token)
    you = call is not None and call == ADMIN['call']
    st = {'ok': True, 'admin': ADMIN['call'], 'you': you, 'local': LOCAL,
          'claimable': ADMIN['call'] is None and LOCAL}
    if you:
        st['settings'] = dict(SETTINGS)
    return st
SESSIONS = {}      # token -> callsign
NONCE = 'c0ffee0123456789'
ADDRESSED = []     # rows only a session may read (to be set by /__inject)
if os.environ.get('MOCK_FLOOD'):
    # A busy bridged channel: 200 regional messages newer than the local one,
    # so the newest page of everything holds no Local conversation at all.
    for i in range(200):
        ROWS.append({'ts': int(time.time()) - 50 + i // 10, 'bearer': 'lora',
                     'rssi': -90, 'from': 'MT%06X' % i, 'to': '', 'type': 'message',
                     'sig': 'none', 'own': False,
                     'wire': 't:message f:MT%06X ts:2026-10-15_09:01:%02d '
                             'scope:regional m:flood %d' % (i, i % 60, i)})


def room_of(r):
    """The room= filter: an undirected row, by the scope its author wrote."""
    if r['to'] and not r['to'].startswith('#'):
        return None
    head = r['wire'].split(' m:')[0] + ' '
    for room in ('local', 'regional'):
        if ' scope:%s ' % room in head:
            return room
    return 'global'


if os.environ.get('MOCK_BOARD'):
    # What the boards answer today: no `page`, so the page shows everything,
    # and no `station`: the page reads the callsign from /api/status.
    del SERVICES['page']
    del SERVICES['station']


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code, body, ctype='application/json', extra=None):
        if isinstance(body, (dict, list)):
            body = json.dumps(body).encode()
        self.send_response(code)
        self.send_header('Content-Type', ctype)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Access-Control-Allow-Origin', '*')
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        u = urlparse(self.path)
        if u.path == '/':
            raw = open(os.path.join(ROOT, 'dist', 'chat_page.html'), 'rb').read()
            self._send(200, gzip.compress(raw), 'text/html; charset=utf-8',
                       {'Content-Encoding': 'gzip'})
        elif u.path == '/app':
            self._send(200, b'<html><body>download page</body></html>', 'text/html')
        elif u.path == '/api/services':
            self._send(200, SERVICES)
        elif u.path == '/api/session':
            self._send(200, {'ok': True, 'nonce': NONCE})
        elif u.path == '/api/status':
            self._send(200, {'ok': True, 'callsign': 'X1BOARD', 'board': 'mock',
                             'uptime_s': 60})
        elif u.path == '/api/admin':
            self._send(200, admin_state((parse_qs(u.query).get('session') or [''])[0]))
        elif u.path == '/api/xprs/history':
            q = parse_qs(u.query)
            kinds = (q.get('kind') or [''])[0].split(',')
            pool = list(ROWS)
            if (q.get('session') or [''])[0] in SESSIONS:
                pool += ADDRESSED
            rows = [r for r in pool if not kinds[0] or r['type'] in kinds]
            call = (q.get('call') or [''])[0]
            if call:
                rows = [r for r in rows if r['from'] == call]
            room = (q.get('room') or [''])[0]
            if room:
                rows = [r for r in rows if room_of(r) == room]
            rows.sort(key=lambda r: -r['ts'])
            rows = rows[:int((q.get('limit') or ['30'])[0])]
            self._send(200, {'ok': True, 'count': len(rows), 'held': len(ROWS),
                             'time': 'synced', 'rows': rows})
        elif u.path == '/__sent':
            self._send(200, SENT)
        else:
            self._send(404, {'ok': False, 'error': 'not here'})

    def do_POST(self):
        n = int(self.headers.get('Content-Length') or 0)
        body = self.rfile.read(n).decode()
        path = urlparse(self.path).path
        if path == '/api/session':
            # The mock does not check the signature: the real host does
            # (WebChatApi, tested in the app). It checks the nonce.
            try:
                wire = json.loads(body)['wire']
            except Exception:
                return self._send(400, {'ok': False, 'error': 'malformed'})
            if ' m:' + NONCE not in wire:
                return self._send(403, {'ok': False, 'error': 'no such challenge'})
            token = 'tok%d' % (len(SESSIONS) + 1)
            SESSIONS[token] = wire.split(' f:')[1].split(' ')[0]
            return self._send(200, {'ok': True, 'session': token})
        if path == '/api/admin':
            b = json.loads(body or '{}')
            call, act = SESSIONS.get(b.get('session')), b.get('action')
            if call is None:
                return self._send(403, {'ok': False, 'error': 'prove your key first'})
            if act == 'claim':
                if ADMIN['call']:
                    return self._send(409, {'ok': False, 'error': 'taken'})
                if not LOCAL:
                    return self._send(403, {'ok': False, 'error': "claim it from the station's own network"})
                ADMIN['call'] = call
            elif act in ('set', 'release'):
                if call != ADMIN['call']:
                    return self._send(403, {'ok': False, 'error': 'not the administrator'})
                if act == 'release':
                    ADMIN['call'] = None
                else:
                    SETTINGS.update(b.get('settings') or {})
            return self._send(200, admin_state(b.get('session')))
        if path == '/__admin':
            return self._send(200, {'admin': ADMIN['call'], 'settings': SETTINGS})
        if path == '/__inject':
            # A row only a session may read: {"wire":..., "from":..., "to":...}
            r = json.loads(body)
            ADDRESSED.append({'ts': int(time.time()), 'bearer': 'lan', 'rssi': 0,
                              'from': r['from'], 'to': r.get('to', ''),
                              'type': r.get('type', 'message'), 'sig': 'verified',
                              'own': False, 'wire': r['wire']})
            return self._send(200, {'ok': True})
        if path == '/__row':
            ROWS.append(json.loads(body))
            return self._send(200, {'ok': True})
        if urlparse(self.path).path == '/api/xprs/send':
            try:
                wire = json.loads(body)['wire']
            except Exception:
                wire = body
            if not wire.startswith('t:') or ' f:' not in wire or len(wire) > 250:
                return self._send(400, {'ok': False, 'error': 'malformed'})
            SENT.append(wire)
            return self._send(200, {'ok': True, 'id': 'abc123', 'wire': wire})
        self._send(404, {'ok': False, 'error': 'not here'})


if __name__ == '__main__':
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8780
    ThreadingHTTPServer(('127.0.0.1', port), H).serve_forever()
