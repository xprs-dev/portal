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
            'page': {'tabs': ['chat', 'traffic', 'alerts'], 'config': False, 'app': '/app',
                     'session': True, 'admin': True, 'moderation': True,
                     'rooms': True, 'alerts': 'moderators'}}
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
         'kind': m.get('kind', 'chat'), 'shared': False,
         'visibility': m['visibility'], 'posting': m['posting'], 'role': role,
         'can_post': bool(who) and (not members_only or role in ('member', 'mod'))}
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
SETTINGS = {'local_private': True, 'who_may_post': 'everyone', 'who_may_alert': 'moderators'}
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
        elif u.path == '/api/rooms' and (parse_qs(u.query).get('topics') or [''])[0]:
            room = parse_qs(u.query)['topics'][0]
            if room not in ROOMS:
                return self._send(404, {'ok': False, 'error': 'no such room'})
            if ROOMS[room].get('kind') != 'forum':
                return self._send(400, {'ok': False, 'error': 'not a forum room'})
            self._send(200, {'ok': True, 'room': room, 'topics': forum_topics(room)})
        elif u.path == '/api/rooms':
            tok = (parse_qs(u.query).get('session') or [''])[0]
            who, admin = SESSIONS.get(tok), SESSIONS.get(tok) == ADMIN['call']
            self._send(200, {'ok': True, 'rooms': [
                room_json(c, who, admin) for c in sorted(ROOMS, key=lambda c: ROOMS[c]['name'])
                if admin or ROOMS[c]['visibility'] == 'public' or (c, who) in ROOM_ROLES]})
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
                    SETTINGS.update(b.get('settings') or {})
            return self._send(200, admin_state(b.get('session')))
        if path == '/api/rooms':
            b = json.loads(body or '{}')
            if SESSIONS.get(b.get('session')) != ADMIN['call']:
                return self._send(403, {'ok': False, 'error': "only the station's administrator manages rooms"})
            act, call = b.get('action'), b.get('call', '')
            if act == 'create':
                ROOM_N[0] += 1
                call = 'X5R%03X' % ROOM_N[0]
                vis = b.get('visibility', 'public')
                ROOMS[call] = {'name': b['name'], 'about': b.get('about', ''), 'visibility': vis,
                               'kind': b.get('kind', 'chat'),
                               'posting': 'members' if vis == 'private' else b.get('posting', 'anyone')}
                ROOM_ROLES[(call, ADMIN['call'])] = 'invited'
            elif call not in ROOMS:
                return self._send(404, {'ok': False, 'error': 'no such room'})
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
            if wire.startswith('t:moderate ') and ' d:X5' in wire:
                f = wire.split(' f:')[1].split(' ')[0]
                g = wire.split(' d:')[1].split(' ')[0]
                if ' accept:' in wire and ROOM_ROLES.get((g, f)) == 'invited':
                    ROOM_ROLES[(g, f)] = 'mod' if ' accept:mod' in wire else 'member'
                elif ROOM_ROLES.get((g, f)) != 'mod':
                    return self._send(403, {'ok': False, 'error': 'not a moderator here'})
                SENT.append(wire)
                return self._send(200, {'ok': True, 'id': 'abc123', 'wire': wire})
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
                if (m['visibility'] == 'private' or m['posting'] != 'anyone') \
                        and ROOM_ROLES.get((g, f)) not in ('member', 'mod'):
                    return self._send(403, {'ok': False, 'error': 'only members post in this room'})
                typ = wire[2:wire.index(' ')]
                if typ == 'blog' and m.get('kind') != 'forum':
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
            return self._send(200, {'ok': True, 'id': 'abc123', 'wire': wire})
        self._send(404, {'ok': False, 'error': 'not here'})


if __name__ == '__main__':
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8780
    ThreadingHTTPServer(('127.0.0.1', port), H).serve_forever()
