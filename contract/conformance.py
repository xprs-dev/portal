#!/usr/bin/env python3
"""The station API, black-box: what every engine behind the web chat must do.

    python3 contract/conformance.py http://127.0.0.1:18080

One page, many engines (a Dart server or phone, an ESP32 board, the mock):
this drives the API the page uses (spec/API-HTTP.md, XPRS.md 10.10) from
outside, with keys of its own, signing with the page's crypto (sign.js), and
says where an engine deviates. It must be run from the station's own network
(the claim is refused from elsewhere), against a station with no
administrator yet (or one this suite claimed before: it releases it at the
end).

What it checks: /api/services names the station and what the page may
offer; a session is a signed nonce, and only the right key gets one; the
administrator is claimed once, from the network; settings; moderators are
appointed, accept with their own signature, remove messages and send people
away, and the station enforces that on history and send; hosted rooms are
created, listed by visibility, joined by acceptance, posted to and filed;
alerts are gated by the setting; files by reference, where the station
says it keeps them, are stored only under their own hash and served back.
"""
import base64
import hashlib
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
BASE = sys.argv[1].rstrip('/') if len(sys.argv) > 1 else 'http://127.0.0.1:8780'
fails = 0


def check(ok, what, extra=''):
    global fails
    print(('  [PASS] ' if ok else '  [FAIL] ') + what + (('  -- ' + str(extra)) if (extra and not ok) else ''))
    fails += 0 if ok else 1


def sign(priv, canonical):
    return subprocess.check_output(['node', os.path.join(HERE, 'sign.js'), priv, canonical], text=True)


def npub(priv):
    return subprocess.check_output(['node', os.path.join(HERE, 'sign.js'), '--npub', priv], text=True)


def wire_id(wire):
    return subprocess.check_output(['node', os.path.join(HERE, 'sign.js'), '--id', wire], text=True)


def http(method, path, body=None, query=''):
    url = BASE + path + (('?' + query) if query else '')
    data = None if body is None else (body if isinstance(body, bytes) else json.dumps(body).encode())
    req = urllib.request.Request(url, data=data, method=method)
    if data is not None:
        req.add_header('Content-Type', 'application/json')
    # A board verifies a signature in a few hundred milliseconds, and the C3
    # under QEMU in several seconds, one request at a time: be patient, and
    # when its backlog resets a connection, ask again.
    for attempt in range(6):
        try:
            with urllib.request.urlopen(req, timeout=180) as r:
                return r.status, json.loads(r.read().decode() or '{}')
        except urllib.error.HTTPError as e:
            try:
                return e.code, json.loads(e.read().decode() or '{}')
            except Exception:
                return e.code, {}
        except (ConnectionResetError, ConnectionRefusedError, urllib.error.URLError, TimeoutError, OSError) as e:
            if attempt == 5:
                raise
            print('  (%s %s: %s; asking again)' % (method, path, e), file=sys.stderr)
            time.sleep(3 + 3 * attempt)
            req = urllib.request.Request(url, data=data, method=method)
            if data is not None:
                req.add_header('Content-Type', 'application/json')


def files(caps):
    """GET/POST /api/xprs/file/<ref> (API-HTTP.md, XPRS.md 7.7)."""
    data = os.urandom(512)
    ref = base64.urlsafe_b64encode(hashlib.sha256(data).digest()).decode().rstrip('=') + '.png'
    check(caps.get('max', 0) >= 512, 'it says how large a file it keeps', caps)
    check(http('GET', '/api/xprs/file/' + ref)[0] == 404, 'a file it does not hold is 404')
    check(http('POST', '/api/xprs/file/' + ref, os.urandom(512))[0] == 400, 'bytes that do not hash to the reference are refused')
    check(http('POST', '/api/xprs/file/not-a-ref.png', data)[0] == 400, 'so is a value that is not a reference')
    st, d = http('POST', '/api/xprs/file/' + ref, data)
    check(st == 200 and d.get('size') == 512, 'the right bytes are kept', d)
    req = urllib.request.Request(BASE + '/api/xprs/file/' + ref)
    with urllib.request.urlopen(req, timeout=60) as r:
        got, ctype = r.read(), r.headers.get('Content-Type', '')
    check(got == data and ctype.startswith('image/png'), 'and served back with their type', ctype)


def ts(plus=0):
    return time.strftime('%Y-%m-%d_%H:%M:%S', time.gmtime(time.time() + plus))


class Person:
    def __init__(self, priv):
        self.priv, self.session = priv, None
        self.npub = npub(priv)
        # The callsign a key derives (XPRS.md 3), as the page makes it: a
        # board refuses an X1 identity whose callsign is not its key's.
        self.call = 'X1' + self.npub[5:9].upper()

    def send(self, canonical):
        return http('POST', '/api/xprs/send', {'wire': sign(self.priv, canonical)})

    def identity(self):
        return self.send('t:identity f:%s ts:%s k:%s' % (self.call, ts(), self.npub))

    def prove(self):
        st, d = http('GET', '/api/session')
        if st != 200:
            return st
        for _ in range(12):
            st, d2 = http('POST', '/api/session', {'wire': sign(self.priv, 't:session f:%s ts:%s m:%s' % (self.call, ts(), d['nonce']))})
            if st == 409:          # the station has not learned our key yet
                time.sleep(3)
                self.identity()
                st, d = http('GET', '/api/session')
                continue
            if st == 200:
                self.session = d2['session']
            return st
        return st

    def admin(self, action, **kw):
        return http('POST', '/api/admin', dict(action=action, session=self.session, **kw))

    def rooms(self, action=None, **kw):
        if action is None:
            return http('GET', '/api/rooms', query='session=' + (self.session or ''))
        return http('POST', '/api/rooms', dict(action=action, session=self.session, **kw))

    def state(self):
        return http('GET', '/api/admin', query='session=' + (self.session or ''))[1]

    def history(self, **q):
        if self.session:
            q['session'] = self.session
        return http('GET', '/api/xprs/history', query='&'.join('%s=%s' % kv for kv in q.items()))[1]


def main():
    seed = int(time.time()) & 0xffff
    alice = Person('11' * 31 + '%02x' % (seed & 255 or 1))
    bob = Person('22' * 31 + '%02x' % ((seed >> 8) & 255 or 2))
    carol = Person('33' * 31 + '%02x' % ((seed * 7) & 255 or 5))
    print('alice %s, bob %s, carol %s' % (alice.call, bob.call, carol.call))

    print('services')
    st, sv = http('GET', '/api/services')
    check(st == 200 and sv.get('ok'), '/api/services answers')
    page = sv.get('page') or {}
    station = sv.get('station', '')
    check(bool(station), 'it names the station', sv)
    check(page.get('session') is True and page.get('admin') is True, 'the page may offer a session and administration', page)
    check(page.get('moderation') is True and page.get('rooms') is True, 'and moderation and rooms', page)
    check(page.get('alerts') in ('moderators', 'everyone'), 'and says who may post alerts', page)
    check('chat' in page.get('tabs', []), 'the tabs include chat', page)

    if sv.get('file'):
        print('files by reference')
        files(sv['file'])

    print('sessions')
    for p in (alice, bob, carol):
        check(p.identity()[0] == 200, 'an identity is accepted: ' + p.call)
    time.sleep(2)
    check(alice.prove() == 200 and alice.session, 'the right key gets a session')
    st, d = http('GET', '/api/session')
    st2, _ = http('POST', '/api/session', {'wire': sign(bob.priv, 't:session f:%s ts:%s m:%s' % (alice.call, ts(), d['nonce']))})
    check(st2 == 403, "another key under alice's callsign is refused", st2)
    st2, _ = http('POST', '/api/session', {'wire': sign(alice.priv, 't:session f:%s ts:%s m:deadbeefdeadbeef' % (alice.call, ts()))})
    check(st2 == 403, 'a made-up challenge is refused', st2)
    check(bob.prove() == 200 and carol.prove() == 200, 'bob and carol have sessions too')

    print('mail')
    # A message to one callsign is mail, and mail belongs to its two parties
    # (XPRS.md 12.7): the station files it, serves it to a session proving
    # the sender or the recipient (and to its administrator), and to nobody
    # else -- not in history, not on /api/xprs/mail.
    note = 'conformance mail %d' % seed
    st, d = bob.send('t:message f:%s d:%s ts:%s m:%s' % (bob.call, carol.call, ts(), note))
    check(st == 200, "bob's message to carol is taken", d)
    has = lambda rows: any(note in r.get('wire', '') for r in rows)
    for _ in range(30):
        if has(carol.history(kind='message', limit='50').get('rows', [])):
            break
        time.sleep(1)
    check(has(carol.history(kind='message', limit='50').get('rows', [])), 'carol, the recipient, reads it in her history')
    check(has(bob.history(kind='message', limit='50').get('rows', [])), 'bob, the sender, reads it in his')
    check(not has(http('GET', '/api/xprs/history', query='kind=message&limit=50')[1].get('rows', [])), 'without a session it is not served')
    st, d = http('GET', '/api/xprs/mail', query='call=%s' % carol.call)
    check(st == 403, "nor is carol's mailbox, without her session", st)
    st, d = http('GET', '/api/xprs/mail', query='call=%s&session=%s' % (carol.call, bob.session))
    check(st == 403, "nor with somebody else's", st)
    st, d = http('GET', '/api/xprs/mail', query='call=%s&session=%s' % (carol.call, carol.session))
    check(st == 200 and has(d.get('rows', [])), 'with hers, the mailbox lists it', d if st != 200 else None)

    print('the administrator')
    s0 = alice.state()
    check(s0.get('local') is True, 'this suite runs from the station\'s network (local)', s0)
    if s0.get('admin'):
        print('  (the station has an administrator already: %s; this suite needs a station with none)' % s0['admin'])
        sys.exit(2)
    check(s0.get('claimable') is True, 'with no administrator, it is claimable')
    st, d = alice.admin('claim')
    check(st == 200 and d.get('admin') == alice.call and d.get('you') is True, 'alice claims it', d)
    check(d.get('role') == 'invited' and d.get('offer'), 'and is offered the moderator role', d)
    offer = d.get('offer', '')
    st, _ = alice.send('t:moderate f:%s d:%s ts:%s r:%s accept:mod' % (alice.call, station, ts(), offer))
    check(st == 200 and alice.state().get('role') == 'mod', 'which she accepts with her own signature')
    check(bob.admin('claim')[0] == 409, 'nobody else can claim it now')
    check('settings' not in bob.state(), 'and bob does not see the settings')
    st, d = alice.admin('set', settings={'local_private': False, 'who_may_post': 'everyone'})
    check(st == 200 and d['settings']['local_private'] is False, 'the administrator sets settings', d)
    check(alice.admin('set', settings={'who_may_alert': 'nobody'})[0] == 400, 'an unknown value is refused')

    print('moderation')
    st, d = alice.admin('appoint', call=bob.call)
    check(st == 200 and bob.call in d.get('invited', []), 'the administrator appoints bob', d)
    bs = bob.state()
    st, _ = bob.send('t:moderate f:%s d:%s ts:%s r:%s accept:mod' % (bob.call, station, ts(), bs.get('offer', '')))
    check(st == 200 and bob.state().get('role') == 'mod', 'bob accepts: a moderator')
    check(sorted(alice.state().get('moderators', [])) == sorted([alice.call, bob.call]), 'both are listed')
    spam = sign(carol.priv, 't:message f:%s ts:%s m:conformance spam %d' % (carol.call, ts(), seed))
    st, d = http('POST', '/api/xprs/send', {'wire': spam})
    check(st == 200, "carol's message is taken", d)
    spam_id = d.get('id') or wire_id(spam)
    # An archive files what it heard on its own schedule (the Dart core every
    # twenty seconds): wait for it rather than demand it at once.
    for _ in range(30):
        rows = carol.history(kind='message', limit='50').get('rows', [])
        if any(r.get('id') == spam_id or 'conformance spam %d' % seed in r.get('wire', '') for r in rows):
            break
        time.sleep(1)
    check(any(r.get('id') == spam_id or 'conformance spam %d' % seed in r.get('wire', '') for r in rows), 'and served in history, within thirty seconds')
    st, _ = bob.send('t:moderate f:%s d:%s ts:%s r:%s remove:message' % (bob.call, station, ts(), spam_id))
    check(st == 200, 'a moderator removes it')
    h = carol.history(kind='message', limit='50')
    check(not any('conformance spam %d' % seed in r.get('wire', '') for r in h.get('rows', [])), 'it is gone from history')
    check(spam_id in (h.get('moderation') or {}).get('removed', []), 'and listed under moderation.removed', h.get('moderation'))
    check(carol.send('t:moderate f:%s d:%s ts:%s revoke:%s' % (carol.call, station, ts(), bob.call))[0] == 403, 'carol, no moderator, cannot act')
    check(bob.send('t:moderate f:%s d:%s ts:%s grant:%s role:mod' % (bob.call, station, ts(), carol.call))[0] == 403, 'only the administrator appoints')
    st, _ = bob.send('t:moderate f:%s d:%s ts:%s revoke:%s until:%s' % (bob.call, station, ts(), carol.call, ts(3600)))
    check(st == 200, 'bob sends carol away for an hour')
    check(carol.send('t:message f:%s ts:%s m:let me back' % (carol.call, ts()))[0] == 403, 'carol cannot post')
    check(carol.send('t:sos f:%s ts:%s m:help' % (carol.call, ts()))[0] == 200, 'but her call for help is taken (10.7)')
    away = alice.state().get('away', [])
    check(any(a.get('call') == carol.call and a.get('until') for a in away), 'the administrator sees her, with until', away)
    st, d = alice.admin('lift', call=carol.call)
    check(st == 200 and not any(a.get('call') == carol.call for a in d.get('away', [])), 'and lifts it')
    check(carol.send('t:message f:%s ts:%s m:thanks' % (carol.call, ts()))[0] == 200, 'carol posts again')
    st, d = alice.admin('dismiss', call=bob.call)
    check(st == 200 and bob.call not in d.get('moderators', []), 'bob is dismissed', d)
    check(bob.send('t:moderate f:%s d:%s ts:%s r:%s remove:message' % (bob.call, station, ts(), spam_id))[0] == 403, 'and cannot act any more')

    print('hosted rooms')
    check(bob.rooms('create', name='Block C')[0] == 403, 'only the administrator creates a room')
    st, d = alice.rooms('create', name='Block C %d' % seed, about='residents', visibility='public', posting='members')
    check(st == 200 and d.get('room', '').startswith('X5'), 'the administrator creates one: an X5 group', d)
    room = d.get('room', '')
    mine = [r for r in d.get('rooms', []) if r['call'] == room]
    check(mine and mine[0].get('role') == 'invited' and mine[0].get('offer'), 'and is offered its moderator role', mine)
    st, _ = alice.send('t:moderate f:%s d:%s ts:%s r:%s accept:mod' % (alice.call, room, ts(), mine[0].get('offer', '') if mine else ''))
    check(st == 200, 'which she accepts')
    check(bob.send('t:message f:%s d:%s ts:%s m:hi' % (bob.call, room, ts()))[0] == 403, 'bob, no member, cannot post there')
    st, d = alice.rooms('add', call=room, member=bob.call)
    check(st == 200, 'the administrator adds bob')
    rb = [r for r in bob.rooms()[1].get('rooms', []) if r['call'] == room]
    check(rb and rb[0].get('role') == 'invited' and rb[0].get('can_post') is False, 'bob sees the invitation', rb)
    st, _ = bob.send('t:moderate f:%s d:%s ts:%s r:%s accept:member' % (bob.call, room, ts(), rb[0].get('offer', '') if rb else ''))
    rb = [r for r in bob.rooms()[1].get('rooms', []) if r['call'] == room]
    check(st == 200 and rb and rb[0].get('role') == 'member' and rb[0].get('can_post') is True, 'bob accepts: a member who may post')
    st, d = bob.send('t:message f:%s d:%s ts:%s m:hello room %d' % (bob.call, room, ts(), seed))
    check(st == 200, "bob's message is taken", d)
    for _ in range(30):
        hr = carol.history(kind='message,reaction', room=room, limit='50')
        if any('hello room %d' % seed in r.get('wire', '') for r in hr.get('rows', [])):
            break
        time.sleep(1)
    check(any('hello room %d' % seed in r.get('wire', '') for r in hr.get('rows', [])), 'a public room is read by anybody')
    check(not any('hello room %d' % seed in r.get('wire', '') for r in carol.history(kind='message', limit='50').get('rows', [])),
          'and its message is not in the open rooms')
    st, d = alice.rooms('update', call=room, visibility='private')
    check(st == 200 and [r for r in d['rooms'] if r['call'] == room][0]['posting'] == 'members', 'made private: members-only')
    check(not any(r['call'] == room for r in carol.rooms()[1].get('rooms', [])), 'a private room is not listed to carol')
    check(http('GET', '/api/xprs/history', query='room=%s&session=%s' % (room, carol.session))[0] == 404, 'nor served to her')
    check(any('hello room %d' % seed in r.get('wire', '') for r in bob.history(kind='message', room=room, limit='50').get('rows', [])), 'but to its member')
    st, _ = alice.send('t:moderate f:%s d:%s ts:%s revoke:%s' % (alice.call, room, ts(), bob.call))
    check(st == 200 and bob.send('t:message f:%s d:%s ts:%s m:again' % (bob.call, room, ts()))[0] == 403, 'a room moderator sends bob away')
    check(bob.send('t:blog f:%s d:%s ts:%s title:x m:y' % (bob.call, room, ts()))[0] == 403, 'a chat room takes no post')
    st, d = alice.rooms('close', call=room)
    check(st == 200 and not any(r['call'] == room for r in d.get('rooms', [])), 'closed')

    print('forum rooms')
    st, d = alice.rooms('create', name='Radio %d' % seed, kind='forum', visibility='public', posting='anyone')
    check(st == 200 and d.get('room', '').startswith('X5'), 'the administrator creates a forum room', d)
    forum = d.get('room', '')
    fr = [r for r in d.get('rooms', []) if r['call'] == forum]
    check(bool(fr) and fr[0].get('kind') == 'forum', 'listed with kind forum', fr)
    st, d = bob.send('t:blog f:%s d:%s ts:%s title:balun-%d tag:radio m:Which balun did the dipole get?' % (bob.call, forum, ts(), seed))
    check(st == 200, 'bob opens a topic: a titled post to the room', d)
    topic = d.get('id', '')
    check(carol.send('t:blog f:%s d:%s ts:%s m:no title and no r:' % (carol.call, forum, ts()))[0] == 400,
          'a post with neither a title nor r: is refused')
    st, d = carol.send('t:blog f:%s d:%s ts:%s r:%s m:A 1:1 current balun.' % (carol.call, forum, ts(1), topic))
    check(st == 200, 'carol comments: an untitled post naming the topic', d)
    st, d = http('GET', '/api/rooms', query='topics=%s&session=%s' % (forum, carol.session))
    tp = [t for t in d.get('topics', []) if t.get('id') == topic]
    check(st == 200 and bool(tp) and tp[0].get('replies') == 1 and tp[0].get('title') == 'balun-%d' % seed,
          'the index lists the topic with one reply', d)
    th = carol.history(room=forum, kind='blog', root=topic, limit='50').get('rows', [])
    check(len(th) == 2 and 'title:balun' in th[0].get('wire', '') and (' r:%s' % topic) in th[1].get('wire', ''),
          'the thread: the post, then the comment', th)
    # A split post (XPRS.md 7.6), signed once over the whole on its last part (9.1.1).
    head = 't:blog f:%s d:%s ts:%s title:split-%d' % (bob.call, forum, ts(2), seed)
    whole = sign(bob.priv, head + ' m:first half second half').strip()
    sig = whole.split(' sig:')[1].split(' ')[0]
    wid = wire_id(head + ' m:first half second half').strip()
    st, d = http('POST', '/api/xprs/send', {'wire': head + ' n:1/2 m:first half'})
    check(st == 202, 'the first part of a split post is held', d)
    st, d = http('POST', '/api/xprs/send', {'wire': head + ' n:2/2 sig:%s m:second half' % sig})
    check(st == 200 and d.get('id') == wid, 'the last part completes it: verified over the whole, filed', d)
    st, d = http('GET', '/api/rooms', query='topics=%s&session=%s' % (forum, carol.session))
    check(any(t.get('id') == wid for t in d.get('topics', [])), 'the index shows the whole, never a part', d)
    # A post to everybody (XPRS.md 18), from the page: one packet signed, or
    # parts each aired as given (API-HTTP.md, /api/xprs/send), the page joins them.
    one = sign(bob.priv, 't:blog f:%s ts:%s title:short-%d m:Fits one packet.' % (bob.call, ts(3), seed)).strip()
    check(http('POST', '/api/xprs/send', {'wire': one})[0] == 200, 'a signed post to everybody is aired')
    head = 't:blog f:%s ts:%s title:long-%d' % (bob.call, ts(4), seed)
    sig = sign(bob.priv, head + ' m:first half second half').strip().split(' sig:')[1].split(' ')[0]
    check(http('POST', '/api/xprs/send', {'wire': head + ' n:1/2 m:first half'})[0] == 200, 'a part goes out as given, unsigned')
    check(http('POST', '/api/xprs/send', {'wire': head + ' n:2/2 sig:%s m:second half' % sig})[0] == 200, 'and the last, signed over the whole')
    ws = []
    for _ in range(30):   # the archive files in batches
        st, d = http('GET', '/api/xprs/history', query='kind=blog&limit=200')
        ws = [r.get('wire', '') for r in d.get('rows', [])]
        if any(w.startswith(head + ' n:2/2') for w in ws):
            break
        time.sleep(1)
    check(any(w.startswith(head + ' n:1/2') for w in ws) and any(w.startswith(head + ' n:2/2') for w in ws),
          'both parts are in the blog feed within thirty seconds, for the page to join', [head] + [w for w in ws if 'long-' in w])
    check(http('POST', '/api/xprs/send', {'wire': 't:blog f:%s ts:%s title:bare-%d m:unsigned' % (bob.call, ts(5), seed)})[0] == 400,
          'an unsigned post that is not a part is refused')
    # The mesh settings (docs/plan-mesh-trust.md): shapes and bounds.
    st, d = alice.admin('set', settings={'reach_alerts': 'global', 'peers_mode': 'named', 'peers': 'x3town X3HUB', 'follow': 'X1ALIC'})
    sg = d.get('settings', {})
    check(st == 200 and sg.get('reach_alerts') == 'global' and sg.get('peers_mode') == 'named' and sg.get('peers') == 'X3TOWN X3HUB' and sg.get('follow') == 'X1ALIC',
          'the mesh settings are kept: a reach word, a mode, lists of callsigns', d)
    check(alice.admin('set', settings={'reach_posts': 'far'})[0] == 400, 'a reach is local, regional or global')
    check(alice.admin('set', settings={'peers': 'nope'})[0] == 400, 'a peer is a callsign')
    alice.admin('set', settings={'reach_alerts': 'regional', 'peers_mode': 'open', 'peers': '', 'follow': ''})
    # A mesh group (docs/plan-mesh-trust.md): one per station, held here or joined.
    st, d = alice.rooms('create', name='Valley %d' % seed, kind='mesh', visibility='private')
    mesh = d.get('room', '')
    mr = [r for r in d.get('rooms', []) if r['call'] == mesh]
    check(st == 200 and mr and mr[0].get('kind') == 'mesh' and mr[0].get('station_role') == 'owner', 'a mesh is created, held here', d)
    check(alice.rooms('create', name='Second', kind='mesh')[0] == 409, 'one mesh per station')
    check(alice.rooms('add', call=mesh, member='X3AAAA')[0] == 200, 'a station is invited')
    check(alice.rooms('accept', call=mesh)[0] == 409, 'and nothing is offered to the station that holds it')
    alice.rooms('close', call=mesh)
    # Sharing between stations (XPRS.md 10.10.1): the shapes; the exchange itself needs two stations.
    st, d = alice.rooms('share', call=forum, shared=True, peers=['X3MIRR'])
    sr = [r for r in d.get('rooms', []) if r['call'] == forum]
    check(st == 200 and sr and sr[0].get('shared') is True and sr[0].get('peers') == ['X3MIRR'], 'the owner shares the room with a named station', d)
    check(alice.rooms('sync', call=forum)[0] == 200, 'and may ask its peers now')
    st, d = alice.rooms('share', call=forum, mesh=True)
    sr = [r for r in d.get('rooms', []) if r['call'] == forum]
    check(st == 200 and sr and sr[0].get('mesh') is True and sr[0].get('shared') is True, 'shared with the mesh: every trusted station', d)
    alice.rooms('share', call=forum, shared=False)
    st, d = alice.rooms('mirror', call='X5M1RR', owner='X3OWNR', name='Theirs')
    mr = [r for r in d.get('rooms', []) if r['call'] == 'X5M1RR']
    check(st == 200 and mr and mr[0].get('mirrored') is True and mr[0].get('owner') == 'X3OWNR', 'a room another station holds is mirrored', d)
    st, d = alice.rooms('unmirror', call='X5M1RR')
    check(st == 200 and not any(r['call'] == 'X5M1RR' for r in d.get('rooms', [])), 'and let go')
    alice.rooms('close', call=forum)

    print('alerts')
    check(carol.send('t:warning f:%s kind:outage sev:watch ts:%s until:%s m:conformance' % (carol.call, ts(), ts(600)))[0] == 403,
          'by default a visitor may not post an alert')
    st, d = alice.send('t:warning f:%s kind:outage sev:watch ts:%s until:%s m:conformance %d' % (alice.call, ts(), ts(600), seed))
    check(st == 200, 'the administrator may', d)
    aid = d.get('id', '')
    check(alice.send('t:warning f:%s ts:%s r:%s remove:warning' % (alice.call, ts(), aid))[0] == 200, 'and withdraws her own')
    alice.admin('set', settings={'who_may_alert': 'everyone'})
    check(carol.send('t:warning f:%s kind:outage sev:watch ts:%s until:%s m:conformance' % (carol.call, ts(), ts(600)))[0] == 200,
          'opened to everyone, carol may')
    alice.admin('set', settings={'who_may_alert': 'moderators', 'local_private': True})

    print('release')
    st, d = alice.admin('release')
    check(st == 200 and d.get('admin') is None and d.get('claimable') is True, 'the administrator releases the station; it is claimable again', d)
    print('%d failure(s)' % fails if fails else 'all passed')
    sys.exit(1 if fails else 0)


main()
