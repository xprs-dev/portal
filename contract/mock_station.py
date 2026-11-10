#!/usr/bin/env python3
"""A station that speaks just enough of spec/API-HTTP.md for the web chat.

    python3 contract/mock_station.py [port] [archive-delay-seconds]

The delay holds what is sent out of history that long, as a real station's
archive does (it files its writes in batches, every 20 s in core).

Serves dist/chat_page.html at / (gzipped, as both editions do), the
/api/services answer an app host gives (`page.tabs`, `page.app`), a history of
public rows, POST /api/xprs/send, which it records, and files by reference
(GET/POST /api/xprs/file/<ref>, kept in memory). It exists so the page
can be tested without a board and without a phone.
"""
import base64
import gzip
import hashlib
import json
import re
import os
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SENT = []
ARCHIVE_DELAY = 0      # seconds a sent row waits before history shows it
FILES = {}             # sha256 hex -> (bytes, content type)
FILE_MAX = 2 * 1024 * 1024
FILE_TYPES = {'jpg': 'image/jpeg', 'jpeg': 'image/jpeg', 'png': 'image/png', 'gif': 'image/gif',
              'webp': 'image/webp', 'avif': 'image/avif', 'bmp': 'image/bmp', 'txt': 'text/plain',
              'md': 'text/markdown', 'pdf': 'application/pdf'}


def ref_sha(ref):
    """The SHA-256 hex a reference names (XPRS.md 7.7), or None."""
    m = re.fullmatch(r'([A-Za-z0-9_-]{43}|[0-9a-fA-F]{64})\.([a-z0-9]{1,8})', ref or '')
    if not m:
        return None
    h = m.group(1)
    if len(h) == 64:
        return h.lower()
    return base64.urlsafe_b64decode(h + '=').hex()


ROWS = [{
    'ts': int(time.time()) - 60, 'bearer': 'lan', 'rssi': 0, 'from': 'X1ARKL',
    'to': '', 'type': 'message', 'sig': 'verified', 'own': False,
    'wire': 't:message f:X1ARKL ts:2026-10-15_09:00:00 scope:local m:hello from the mock',
}]
SERVICES = {'ok': True, 'station': 'X3MOCK', 'features': {}, 'serve': [],
            'page': {'tabs': ['chat', 'traffic', 'alerts'], 'config': False, 'app': '/app',
                     'session': True, 'mailbox': True, 'admin': True, 'moderation': True,
                     'rooms': True, 'alerts': 'moderators'},
            'file': {'get': True, 'put': True, 'max': FILE_MAX}}
# MOCK_WIFI: a board, which joins an internet WiFi and lists `settings`.
if os.environ.get('MOCK_WIFI'):
    SERVICES['page']['tabs'] = SERVICES['page']['tabs'] + ['settings']
    SERVICES['page']['gallery'] = True   # a board with a card keeps photographs
WIFI_JOINS = []
WIFI = {'ok': True, 'ssid': 'home', 'up': True, 'internet': True, 'join': 'idle',
        'why': '', 'known': [{'ssid': 'home', 'internet': True}]}
# An active alert the station holds (XPRS.md 10.10.2).
ROWS.append({
    'id': '3c7e21', 'ts': int(time.time()) - 30, 'bearer': 'lora', 'rssi': -80,
    'from': 'X3RLY7', 'to': '', 'type': 'warning', 'sig': 'verified', 'own': False,
    'wire': 't:warning f:X3RLY7 kind:outage sev:watch ts:2026-11-06_18:00:00 m:power cut in block C',
})
# A post the station holds (XPRS.md 18), split in two parts (7.6).
for i, part in enumerate(('The wire ends are the whole job.', 'Everything else is decoration.')):
    ROWS.append({
        'id': 'b10%d' % i, 'ts': int(time.time()) - 600, 'bearer': 'lan', 'rssi': 0,
        'from': 'X1QZ3N', 'to': '', 'type': 'blog', 'sig': 'verified', 'own': False,
        'wire': 't:blog f:X1QZ3N ts:2026-08-08_14:26:40 title:antenna-notes tag:radio '
                'n:%d/2 m:%s' % (i + 1, part),
    })
# Rooms the station hosts (10.10.1): call -> meta; the roster is ROOM_ROLES.
ROOMS = {}
ROOM_ROLES = {}   # (call, member) -> 'invited' | 'member' | 'mod'
ROOM_N = [0]


def room_json(call, who, admin):
    m = ROOMS[call]
    role = ROOM_ROLES.get((call, who), 'none')
    members_only = m['visibility'] == 'private' or m['posting'] != 'anyone'
    j = {'call': call, 'name': m['name'], 'about': m.get('about', ''),
         'kind': m.get('kind', 'chat'), 'mesh': m.get('mesh', False), 'shared': m.get('shared', False)}
    if m.get('shared'):
        j['peers'], j['seen'] = m.get('peers', []), m.get('seen', [])
    if m.get('mirrored'):
        j['mirrored'], j['owner'] = True, m['owner']
    if m.get('kind') == 'mesh':
        j['station_role'] = 'owner' if not m.get('mirrored') else ROOM_ROLES.get((call, 'X3MOCK'), 'none')
    j.update({
         'visibility': m['visibility'], 'posting': m['posting'], 'role': role,
         'can_post': bool(who) and (not members_only or role in ('member', 'mod'))})
    if role == 'invited':
        j['offer'] = 'b1b1b1'
    if admin or role == 'mod':
        for r, k in (('member', 'members'), ('mod', 'moderators'), ('invited', 'invited')):
            j[k] = sorted(c for (g, c), v in ROOM_ROLES.items() if g == call and v == r)
    return j
if os.environ.get('MOCK_FORUM'):
    # A forum room (XPRS.md 18.5) with a topic and a comment on it.
    ROOMS['X5F0RM'] = {'name': 'Radio', 'about': 'antennas and such', 'kind': 'forum',
                       'visibility': 'public', 'posting': 'anyone'}
    ROWS.append({'id': '5f2c1a', 'ts': int(time.time()) - 900, 'bearer': 'web', 'rssi': 0,
                 'from': 'X1RD89', 'to': 'X5F0RM', 'type': 'blog', 'sig': 'verified', 'own': False,
                 'wire': 't:blog f:X1RD89 d:X5F0RM ts:2026-08-08_16:02:10 title:balun-question tag:radio '
                         'm:Which balun did the dipole get, and did it matter?'})
    ROWS.append({'id': '9b7e44', 'ts': int(time.time()) - 300, 'bearer': 'web', 'rssi': 0,
                 'from': 'X1QZ3N', 'to': 'X5F0RM', 'type': 'blog', 'sig': 'verified', 'own': False,
                 'wire': 't:blog f:X1QZ3N d:X5F0RM ts:2026-08-08_16:40:00 r:5f2c1a '
                         'm:A 1:1 current balun. It was the wire, not the balun.'})


def forum_topics(room):
    """The index: titled posts, newest edition per author and title, replies counted."""
    posts = [r for r in ROWS if r['to'] == room and r['type'] == 'blog'
             and r.get('id') not in REMOVED and r['from'] not in AWAY]
    topics = {}
    for r in sorted(posts, key=lambda r: r['ts']):
        head = r['wire'].split(' m:')[0] + ' '
        if ' title:' not in head or ' remove:' in head:
            continue
        if ' n:' in head and ' n:1/' not in head:
            continue    # the mock files parts as rows; the first stands for the post
        title = head.split(' title:')[1].split(' ')[0]
        prev = topics.get((r['from'], title))
        topics[(r['from'], title)] = {
            'id': r['id'], 'title': title, 'from': r['from'], 'ts': r['ts'], 'replies': 0,
            'last': r['ts'], 'edited': prev is not None, 'ids': (prev['ids'] if prev else []) + [r['id']]}
    for r in posts:
        head = r['wire'].split(' m:')[0] + ' '
        if ' title:' in head or ' r:' not in head or ' remove:' in head:
            continue
        ref = (head.split(' root:')[1] if ' root:' in head else head.split(' r:')[1]).split(' ')[0]
        for t in topics.values():
            if ref in t['ids']:
                t['replies'] += 1
                t['last'] = max(t['last'], r['ts'])
    out = sorted(topics.values(), key=lambda t: -t['last'])[:100]
    for t in out:
        del t['ids']
    return out


# /api/admin (the rules are WebChatApi's, tested in the core; this answers
# the shapes). MOCK_REMOTE makes every visitor one from the internet.
ADMIN = {'call': None}
SETTINGS = {'local_private': True, 'who_may_post': 'everyone', 'who_may_alert': 'moderators',
            'reach_alerts': 'regional', 'reach_posts': 'regional', 'reach_chat': 'global',
            'follow': '', 'peers_mode': 'open', 'peers': ''}
LOCAL = not os.environ.get('MOCK_REMOTE')


# XPRS.md 10.10, the shapes only (the rules are WebChatApi's): callsign ->
# 'invited' | 'mod'; removed message ids; callsigns sent away.
ROLES, REMOVED, AWAY = {}, [], []
OFFER = 'a0a0a0'


def admin_state(token):
    call = SESSIONS.get(token)
    you = call is not None and call == ADMIN['call']
    st = {'ok': True, 'admin': ADMIN['call'], 'you': you, 'local': LOCAL,
          'claimable': ADMIN['call'] is None and LOCAL,
          'station': 'X3MOCK', 'role': ROLES.get(call, 'none')}
    if st['role'] == 'invited':
        st['offer'] = OFFER
    if you:
        st['settings'] = dict(SETTINGS)
    if you or st['role'] == 'mod':
        st['moderators'] = sorted(c for c, r in ROLES.items() if r == 'mod')
        st['invited'] = sorted(c for c, r in ROLES.items() if r == 'invited')
        st['away'] = [{'call': c} for c in AWAY]
    return st
SESSIONS = {}      # token -> callsign
NONCE = 'c0ffee0123456789'
ADDRESSED = []     # rows only a session may read (to be set by /__inject)
KEYS = {}          # callsign -> x-only pubkey bytes, from t:identity k:npub
MAILBOX = {}       # callsign -> hold: list from its verified t:mailbox
SERVED = set()     # visitors this station offered itself to (12.8.3 step zero)

# The page's signature scheme (page/xprs_crypto.js xprsSign): sig = e16 || s32,
# e16 the first sixteen bytes of tagged('XPRS/challenge', rx || px || digest),
# digest = sha256 of the wire without sig:/via:. Verified with the curve of
# test/bip340_ref.py: R = s*G - e*P must give back the same e16.
import importlib.util as _ilu
_ref = None
def _curve():
    global _ref
    if _ref is None:
        spec = _ilu.spec_from_file_location('bip340_ref', os.path.join(os.path.dirname(__file__), '..', 'test', 'bip340_ref.py'))
        _ref = _ilu.module_from_spec(spec); spec.loader.exec_module(_ref)
    return _ref
B85 = '0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ.-+=^!/*?&<>()[]%$#@,;_'
def b85dec(t):
    out = b''
    for i in range(0, len(t), 5):
        v = 0
        for c in t[i:i + 5]: v = v * 85 + B85.index(c)
        out += v.to_bytes(4, 'big')
    return out
BC = 'qpzry9x8gf2tvdw0s3jn54khce6mua7l'
def npub_px(npub):
    data = [BC.index(c) for c in npub.split('1', 1)[1][:-6]]
    acc = bits = 0; out = bytearray()
    for v in data:
        acc = (acc << 5) | v; bits += 5
        while bits >= 8:
            bits -= 8; out.append((acc >> bits) & 255)
    return bytes(out)
def tagged(tag, m):
    t = hashlib.sha256(tag.encode()).digest(); return hashlib.sha256(t + t + m).digest()
def xprs_verified(wire, px):
    m = re.search(r' sig:([!-~]{60})', wire)
    if not m: return False
    sig = b85dec(m.group(1))
    canon = re.sub(r' sig:[!-~]{60}', '', wire); canon = re.sub(r' via:[A-Za-z0-9,\-]+', '', canon)
    digest = hashlib.sha256(canon.encode()).digest()
    e16, s = sig[:16], int.from_bytes(sig[16:48], 'big')
    r = _curve()
    e = int.from_bytes(e16, 'big')
    Pt = r.lift(int.from_bytes(px, 'big'))
    R = r.add(r.mul(s), r.mul((r.N - e) % r.N, Pt))
    if R is None: return False
    rx = R[0].to_bytes(32, 'big')
    return tagged('XPRS/challenge', rx + px + digest)[:16] == e16
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
            sv = dict(SERVICES)
            if 'page' in sv:   # what the administrator set, as the station reports it
                sv['page'] = dict(sv['page'], alerts=SETTINGS['who_may_alert'],
                                  **{k[5:]: v for k, v in SETTINGS.items() if k.startswith('page_')})
            self._send(200, sv)
        elif u.path == '/api/session':
            self._send(200, {'ok': True, 'nonce': NONCE})
        elif u.path == '/api/wifi' and os.environ.get('MOCK_WIFI'):
            self._send(200, WIFI)
        elif u.path == '/__offline':     # test hook: the station loses the internet
            WIFI.update(up=False, internet=None)
            self._send(200, WIFI)
        elif u.path == '/api/status':
            self._send(200, {'ok': True, 'callsign': 'X1BOARD', 'board': 'mock',
                             'uptime_s': 60})
        elif u.path == '/api/admin':
            self._send(200, admin_state((parse_qs(u.query).get('session') or [''])[0]))
        elif u.path == '/api/rooms' and (parse_qs(u.query).get('topics') or [''])[0]:
            room = parse_qs(u.query)['topics'][0]
            if room not in ROOMS:
                return self._send(404, {'ok': False, 'error': 'no such room'})
            if ROOMS[room].get('kind') not in ('forum', 'gallery'):
                return self._send(400, {'ok': False, 'error': 'not a forum room'})
            self._send(200, {'ok': True, 'room': room, 'topics': forum_topics(room)})
        elif u.path == '/api/rooms':
            tok = (parse_qs(u.query).get('session') or [''])[0]
            who, admin = SESSIONS.get(tok), SESSIONS.get(tok) == ADMIN['call']
            self._send(200, {'ok': True, 'rooms': [
                room_json(c, who, admin) for c in sorted(ROOMS, key=lambda c: ROOMS[c]['name'])
                if admin or ROOMS[c]['visibility'] == 'public' or (c, who) in ROOM_ROLES]})
        elif u.path == '/api/xprs/mail':
            q = parse_qs(u.query)
            call = (q.get('call') or [''])[0]
            who = SESSIONS.get((q.get('session') or [''])[0])
            if not call:
                return self._send(400, {'ok': False, 'error': 'mail needs call='})
            if not who or (who != call and who != ADMIN['call']):
                return self._send(403, {'ok': False, 'error': 'mail needs a session for that callsign'})
            rows = [r for r in ADDRESSED if r['to'] == call]
            self._send(200, {'ok': True, 'count': len(rows), 'held': len(ROWS) + len(ADDRESSED),
                             'time': 'synced', 'rows': rows})
        elif u.path == '/api/xprs/history':
            q = parse_qs(u.query)
            kinds = (q.get('kind') or [''])[0].split(',')
            pool = [r for r in ROWS if r.get('_at', 0) <= time.time()]
            # Mail is its two parties' (XPRS.md 12.7): a session proving one
            # of them, or the administrator's, reads it; nobody else does.
            who = SESSIONS.get((q.get('session') or [''])[0])
            if who:
                pool += [r for r in ADDRESSED
                         if who == ADMIN['call'] or r['to'] == who or r['from'] == who]
            rows = [r for r in pool if not kinds[0] or r['type'] in kinds]
            call = (q.get('call') or [''])[0]
            if call:
                rows = [r for r in rows if r['from'] == call]
            room = (q.get('room') or [''])[0]
            if room in ROOMS:
                tok = (q.get('session') or [''])[0]
                who = SESSIONS.get(tok)
                if ROOMS[room]['visibility'] == 'private' and who != ADMIN['call'] \
                        and (room, who) not in ROOM_ROLES:
                    return self._send(404, {'ok': False, 'error': 'no such room'})
                rows = [r for r in rows if r['to'] == room]
            elif room:
                rows = [r for r in rows if room_of(r) == room]
            else:
                # The general listing is the undirected shelf: a hosted room's
                # rows are read by room= only, as the real engine serves them.
                rows = [r for r in rows if not r['to'].startswith('X5')]
            rows = [r for r in rows if r.get('id') not in REMOVED and r['from'] not in AWAY]
            rows.sort(key=lambda r: -r['ts'])
            root = (q.get('root') or [''])[0]
            if root:
                # A thread (XPRS.md 7.4, 18.5): the post and what names it, oldest first.
                def names(r):
                    head = r['wire'].split(' m:')[0] + ' '
                    return r.get('id') == root or (' r:%s ' % root) in head or (' root:%s ' % root) in head
                rows = [r for r in rows if names(r)][::-1]
            rows = rows[:int((q.get('limit') or ['30'])[0])]
            self._send(200, {'ok': True, 'count': len(rows), 'held': len(ROWS),
                             'time': 'synced', 'rows': rows,
                             'moderation': {'removed': REMOVED, 'away': AWAY}})
        elif u.path.startswith('/api/xprs/file/'):
            ref = u.path[len('/api/xprs/file/'):]
            sha = ref_sha(ref)
            if not sha:
                return self._send(400, {'ok': False, 'error': 'not a file reference'})
            if sha not in FILES:
                return self._send(404, {'ok': False, 'error': 'not held'})
            data, ctype = FILES[sha]
            self._send(200, data, ctype, {'Cache-Control': 'public, max-age=31536000, immutable',
                                          'ETag': '"%s"' % sha})
        elif u.path == '/__sent':
            self._send(200, SENT)
        else:
            self._send(404, {'ok': False, 'error': 'not here'})

    def do_POST(self):
        n = int(self.headers.get('Content-Length') or 0)
        raw = self.rfile.read(n)
        path = urlparse(self.path).path
        if path == '/api/wifi' and os.environ.get('MOCK_WIFI'):
            f = parse_qs(raw.decode())
            who = SESSIONS.get((f.get('session') or [''])[0])
            # The station's rule: online, only the administrator moves it.
            if WIFI['up'] and WIFI['internet'] is not False and who != ADMIN['call']:
                return self._send(403, {'ok': False, 'error': 'the station is online: '
                                        'only its administrator changes its network'})
            WIFI_JOINS.append((f.get('ssid') or [''])[0])
            return self._send(200, {'ok': True, 'join': 'joining'})
        if path == '/__wifi_joins':
            return self._send(200, WIFI_JOINS)
        if path.startswith('/api/xprs/file/'):
            ref = path[len('/api/xprs/file/'):]
            sha = ref_sha(ref)
            if not sha:
                return self._send(400, {'ok': False, 'error': 'not a file reference'})
            if len(raw) > FILE_MAX:
                return self._send(413, {'ok': False, 'error': 'larger than this station keeps'})
            if hashlib.sha256(raw).hexdigest() != sha:
                return self._send(400, {'ok': False, 'error': 'the bytes do not match the reference'})
            FILES[sha] = (raw, FILE_TYPES.get(ref.rsplit('.', 1)[1], 'application/octet-stream'))
            return self._send(200, {'ok': True, 'ref': ref, 'size': len(raw)})
        body = raw.decode()
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
            call = wire.split(' f:')[1].split(' ')[0]
            SESSIONS[token] = call
            # Whose mailbox this visitor has, and this station's offer to be
            # it when they have none (XPRS.md 12.8.3 step zero, 9.12).
            holders = list(MAILBOX.get(call, []))
            if not holders and call in SERVED: holders = [SERVICES['station']]
            reply = {'ok': True, 'session': token, 'call': call, 'holders': holders,
                     'mail': len([r for r in ADDRESSED if r['to'] == call])}
            if not holders:
                SERVED.add(call); reply['offer'] = SERVICES['station']
            return self._send(200, reply)
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
                ROLES[call] = 'invited'
            elif act in ('appoint', 'dismiss', 'lift'):
                if call != ADMIN['call']:
                    return self._send(403, {'ok': False, 'error': 'not the administrator'})
                who = b.get('call', '')
                if act == 'appoint':
                    ROLES[who] = 'invited'
                else:
                    ROLES.pop(who, None) if act == 'dismiss' else None
                    if act == 'lift' and who in AWAY:
                        AWAY.remove(who)
            elif act in ('set', 'release'):
                if call != ADMIN['call']:
                    return self._send(403, {'ok': False, 'error': 'not the administrator'})
                if act == 'release':
                    ADMIN['call'] = None
                else:
                    for k, v in (b.get('settings') or {}).items():
                        # The same shapes the station checks (API-HTTP.md).
                        if k.startswith('reach_') and v not in ('local', 'regional', 'global'):
                            return self._send(400, {'ok': False, 'error': '%s must be local, regional or global' % k})
                        if k == 'peers_mode' and v not in ('open', 'named'):
                            return self._send(400, {'ok': False, 'error': 'peers_mode must be open or named'})
                        if k in ('peers', 'follow'):
                            calls = [c for c in re.split(r'[\s,]+', str(v).upper()) if c]
                            for c in calls:
                                if not (re.match(r'^X[1-5][A-Z0-9]{2,5}$', c) or (k == 'follow' and re.match(r'^NPUB1[A-Z0-9]{58}$', c))):
                                    return self._send(400, {'ok': False, 'error': '%s: %s is not a callsign' % (k, c)})
                            v = ' '.join(c.lower() if c.startswith('NPUB1') else c for c in calls)
                        if k.startswith('page_') and v == '':
                            SETTINGS.pop(k, None)   # emptied: gone
                        else:
                            SETTINGS[k] = v
            return self._send(200, admin_state(b.get('session')))
        if path == '/api/rooms':
            b = json.loads(body or '{}')
            if SESSIONS.get(b.get('session')) != ADMIN['call']:
                return self._send(403, {'ok': False, 'error': "only the station's administrator manages rooms"})
            act, call = b.get('action'), b.get('call', '')
            if act in ('create', 'mirror') and b.get('kind') == 'mesh' and any(r.get('kind') == 'mesh' for r in ROOMS.values()):
                return self._send(409, {'ok': False, 'error': 'this station is already in a mesh'})
            if act == 'create':
                ROOM_N[0] += 1
                call = 'X5R%03X' % ROOM_N[0]
                vis = b.get('visibility', 'public')
                ROOMS[call] = {'name': b['name'], 'about': b.get('about', ''), 'visibility': vis,
                               'kind': b.get('kind', 'chat'),
                               'posting': 'members' if vis == 'private' else b.get('posting', 'anyone')}
                if b.get('kind') != 'mesh':
                    ROOM_ROLES[(call, ADMIN['call'])] = 'invited'
            elif act == 'accept':
                if ROOM_ROLES.get((call, 'X3MOCK')) != 'invited':
                    return self._send(409, {'ok': False, 'error': 'nothing offered to this station'})
                ROOM_ROLES[(call, 'X3MOCK')] = 'member'
            elif act == 'mirror':
                ROOMS[call] = {'name': b.get('name') or call, 'about': '', 'kind': b.get('kind', 'forum'),
                               'visibility': 'public', 'posting': 'anyone', 'mirrored': True, 'owner': b['owner']}
            elif call not in ROOMS:
                return self._send(404, {'ok': False, 'error': 'no such room'})
            elif act == 'share':
                ROOMS[call]['mesh'] = bool(b.get('mesh'))
                ROOMS[call]['shared'] = bool(b.get('shared')) or bool(b.get('mesh'))
                ROOMS[call]['peers'] = [p.upper() for p in b.get('peers', [])]
            elif act == 'unmirror':
                del ROOMS[call]
            elif act == 'sync':
                pass
            elif act == 'update':
                for k in ('name', 'about', 'visibility', 'posting', 'kind'):
                    if k in b:
                        ROOMS[call][k] = b[k]
                if ROOMS[call]['visibility'] == 'private':
                    ROOMS[call]['posting'] = 'members'
            elif act == 'close':
                del ROOMS[call]
            elif act in ('add', 'appoint', 'remove'):
                m = b.get('member', '')
                if act == 'remove':
                    ROOM_ROLES.pop((call, m), None)
                else:
                    ROOM_ROLES[(call, m)] = 'invited'
            who = SESSIONS.get(b.get('session'))
            return self._send(200, {'ok': True, 'room': call, 'rooms': [
                room_json(c, who, True) for c in ROOMS]})
        if path == '/__admin':
            return self._send(200, {'admin': ADMIN['call'], 'settings': SETTINGS,
                                    'roles': ROLES, 'removed': REMOVED, 'away': AWAY,
                                    'rooms': ROOMS,
                                    'room_roles': {'%s %s' % k: v for k, v in ROOM_ROLES.items()}})
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
            if wire.startswith('t:identity '):
                f = wire.split(' f:')[1].split(' ')[0]
                k = re.search(r' k:(npub1[a-z0-9]+)', wire)
                if k: KEYS[f] = npub_px(k.group(1))
            if wire.startswith('t:mailbox ') or wire.startswith('t:receipt '):
                f = wire.split(' f:')[1].split(' ')[0]
                if f not in KEYS:
                    return self._send(409, {'ok': False, 'error': 'identity unknown'})
                if not xprs_verified(wire, KEYS[f]):
                    return self._send(400, {'ok': False, 'error': 'forged'})
                SENT.append(wire)
                if wire.startswith('t:mailbox '):
                    h = re.search(r' hold:([A-Za-z0-9,\-]+)', wire)
                    if h: MAILBOX[f] = h.group(1).split(',')
                else:
                    rid = re.search(r' r:([0-9a-f]+)', wire)
                    if rid:
                        ADDRESSED[:] = [r for r in ADDRESSED if r.get('id') != rid.group(1)]
                return self._send(200, {'ok': True, 'id': 'x%05x' % len(SENT), 'wire': wire})
            if wire.startswith('t:moderate ') and ' d:X5' in wire:
                f = wire.split(' f:')[1].split(' ')[0]
                g = wire.split(' d:')[1].split(' ')[0]
                if ' accept:' in wire and ROOM_ROLES.get((g, f)) == 'invited':
                    ROOM_ROLES[(g, f)] = 'mod' if ' accept:mod' in wire else 'member'
                elif ROOM_ROLES.get((g, f)) != 'mod':
                    return self._send(403, {'ok': False, 'error': 'not a moderator here'})
                SENT.append(wire)
                return self._send(200, {'ok': True, 'id': 'abc123', 'wire': wire})
            if wire.startswith('t:blog ') and ' d:' not in wire.split(' m:')[0]:
                # A post to everybody (XPRS.md 18), aired as given: a part
                # (7.6) carries no signature of its own, so none is asked of it.
                f = wire.split(' f:')[1].split(' ')[0]
                part = ' n:' in wire.split(' m:')[0] + ' '
                if not part and ' sig:' not in wire:
                    return self._send(400, {'ok': False, 'error': 'unsigned'})
                SENT.append(wire)
                ROWS.append({'id': 'b%05x' % len(SENT), 'ts': int(time.time()), 'bearer': 'lan',
                             'rssi': 0, 'from': f, 'to': '', 'type': 'blog',
                             'sig': 'unverified' if part else 'verified', 'own': False, 'wire': wire,
                             '_at': time.time() + ARCHIVE_DELAY})
                return self._send(200, {'ok': True, 'id': 'b%05x' % len(SENT), 'wire': wire})
            if wire.startswith('t:warning ') or wire.startswith('t:info '):
                f = wire.split(' f:')[1].split(' ')[0]
                if ' remove:' not in wire and SETTINGS['who_may_alert'] != 'everyone' \
                        and f != ADMIN['call'] and ROLES.get(f) != 'mod':
                    return self._send(403, {'ok': False, 'error': 'on this station only moderators post alerts'})
                SENT.append(wire)
                ROWS.append({'id': 'a%05x' % len(SENT), 'ts': int(time.time()), 'bearer': 'lan',
                             'rssi': 0, 'from': f, 'to': '', 'type': wire[2:wire.index(' ')],
                             'sig': 'verified', 'own': False, 'wire': wire})
                return self._send(200, {'ok': True, 'id': 'a%05x' % len(SENT), 'wire': wire})
            if ' d:X5' in wire:
                f = wire.split(' f:')[1].split(' ')[0]
                g = wire.split(' d:')[1].split(' ')[0]
                m = ROOMS.get(g)
                if m is None:
                    return self._send(404, {'ok': False, 'error': 'no such room'})
                typ = wire[2:wire.index(' ')]
                if m.get('kind') == 'gallery':
                    # API-HTTP.md: the room's staff adds events and pictures,
                    # readers like.
                    staff = f == ADMIN['call'] or ROOM_ROLES.get((g, f)) == 'mod'
                    if typ not in ('blog', 'message', 'file', 'reaction'):
                        return self._send(403, {'ok': False, 'error': 'a gallery takes events, pictures and likes'})
                    if typ != 'reaction' and not staff:
                        return self._send(403, {'ok': False, 'error': 'only the moderators add events and pictures here'})
                elif (m['visibility'] == 'private' or m['posting'] != 'anyone') \
                        and ROOM_ROLES.get((g, f)) not in ('member', 'mod'):
                    return self._send(403, {'ok': False, 'error': 'only members post in this room'})
                if typ == 'blog' and m.get('kind') not in ('forum', 'gallery'):
                    return self._send(403, {'ok': False, 'error': 'posts go in a forum room'})
                SENT.append(wire)
                # The mock files a part as a row like any other (the real engine
                # holds a split post until its last part verifies, 9.1.1).
                ROWS.append({'id': 'r%05x' % len(SENT), 'ts': int(time.time()), 'bearer': 'web',
                             'rssi': 0, 'from': f, 'to': g, 'type': typ,
                             'sig': 'verified', 'own': False, 'wire': wire})
                return self._send(200, {'ok': True, 'id': 'r%05x' % len(SENT), 'wire': wire})
            if wire.startswith('t:moderate '):
                f = wire.split(' f:')[1].split(' ')[0]
                if ' accept:mod' in wire and ROLES.get(f) == 'invited':
                    ROLES[f] = 'mod'
                elif ROLES.get(f) != 'mod':
                    return self._send(403, {'ok': False, 'error': 'not a moderator here'})
                elif ' remove:message' in wire:
                    REMOVED.append(wire.split(' r:')[1].split(' ')[0])
                elif ' revoke:' in wire:
                    AWAY.append(wire.split(' revoke:')[1].split(' ')[0])
            SENT.append(wire)
            # A message to one callsign is mail (XPRS.md 12.1): held for its
            # two parties, read only through a session proving one of them.
            head = wire.split(' m:')[0]
            if wire.startswith('t:message ') and ' d:' in head and ' d:#' not in head:
                f = wire.split(' f:')[1].split(' ')[0]
                d = wire.split(' d:')[1].split(' ')[0]
                ADDRESSED.append({'id': 'm%05x' % len(SENT), 'ts': int(time.time()), 'bearer': 'lan',
                                  'rssi': 0, 'from': f, 'to': d, 'type': 'message',
                                  'sig': 'verified', 'own': False, 'wire': wire})
                return self._send(200, {'ok': True, 'id': 'm%05x' % len(SENT), 'wire': wire})
            return self._send(200, {'ok': True, 'id': 'abc123', 'wire': wire})
        self._send(404, {'ok': False, 'error': 'not here'})


if __name__ == '__main__':
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8780
    ARCHIVE_DELAY = float(sys.argv[2]) if len(sys.argv) > 2 else 0
    ThreadingHTTPServer(('127.0.0.1', port), H).serve_forever()
