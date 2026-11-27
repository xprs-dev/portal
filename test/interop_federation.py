#!/usr/bin/env python3
"""Archivers as one service: three server-edition stations on this machine.

What a network of archivers owes the people using it (XPRS.md 12.9, 12.12,
12.12.2, 10.10.3), checked from outside, on real stations joined only by
Reticulum. A is the hub the other two dial; B and C never meet except
through it. Each person below is a visitor of ONE station, with a key of
their own, signing with the page's crypto as a browser does.

  rooms       what is said in the Global room at one archiver is read at the
              others; what is said in its Regional and Local rooms stays
              there.
  who         a person's mailbox declaration made at one archiver is known
              at the others: they know who is cared for where.
  mail        a person at B writes to a person at C: B holds the message,
              learns that C is where she is, hands it over, and she reads it
              at C. Her receipt releases the copies held on the way
              back.
  files       a file kept at B is found from C by its hash alone: C says
              who holds it without being told, and can fetch it.
  moderator   a key on the published list removes a Global message at one
              archiver, and it goes from the others too (10.10.3).

Usage:
    python3 test/interop_federation.py --server ../server/build/xprs-server-linux-arm64
        [--keep] [--dir D] [--wait SECONDS] [--only rooms,who,mail,files,moderator]
        [--live http://127.0.0.1 [--live-hub 127.0.0.1:4242]]

With --live the station already running on this machine is A, the one the
other two dial: the real archiver takes part, with everything it is
connected to. The run then withdraws what it said in the public room.

The stations run with --no-lan and no public hub: nothing on the machine's
real network is heard or reached. --keep leaves folders and logs behind.
"""
import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import interop_archivers as ia          # noqa: E402  (the two-station harness)
from interop_archivers import check, http, get_json, ref_of   # noqa: E402

SIGN = os.path.join(HERE, '..', 'contract', 'sign.js')
PORTS = {'a': (18091, 14251), 'b': (18092, 14252), 'c': (18093, 14253)}
DEAD_PORT = 14259
MOD_KEY = '77' * 32         # the key every station here is told is listed


def sign(priv, canonical):
    return subprocess.check_output(['node', SIGN, priv, canonical], text=True)


def npub(priv):
    return subprocess.check_output(['node', SIGN, '--npub', priv], text=True)


def wire_id(wire):
    return subprocess.check_output(['node', SIGN, '--id', wire], text=True)


def ts(plus=0):
    return time.strftime('%Y-%m-%d_%H:%M:%S', time.gmtime(time.time() + plus))


def jget(url):
    return get_json(url)[1]


def jpost(url, obj):
    st, b = http('POST', url, json.dumps(obj).encode(), timeout=60)
    try:
        return st, json.loads(b)
    except Exception:
        return st, {}


class Person:
    """A visitor of one station: a key, the callsign it derives, a session."""

    def __init__(self, name, priv, home):
        self.name, self.priv, self.home = name, priv, home
        self.npub = npub(priv)
        self.call = 'X1' + self.npub[5:9].upper()
        self.session, self.reply = None, {}

    def send(self, canonical, at=None):
        return jpost((at or self.home).base + '/api/xprs/send', {'wire': sign(self.priv, canonical)})

    def identity(self, at=None):
        return self.send('t:identity f:%s ts:%s k:%s' % (self.call, ts(), self.npub), at)

    def prove(self, at=None):
        s = at or self.home
        for _ in range(12):
            st, d = get_json(s.base + '/api/session')
            if st != 200:
                return st
            st, d2 = jpost(s.base + '/api/session', {'wire': sign(
                self.priv, 't:session f:%s ts:%s m:%s' % (self.call, ts(), d['nonce']))})
            if st == 409:           # the station has not learned our key yet
                time.sleep(2)
                self.identity(s)
                continue
            if st == 200:
                self.session, self.reply = d2['session'], d2
            return st
        return st

    def mail(self, at=None):
        s = at or self.home
        return get_json('%s/api/xprs/mail?call=%s&session=%s' % (s.base, self.call, self.session or ''))


def history(s, **q):
    return jget(s.base + '/api/xprs/history?' + '&'.join('%s=%s' % kv for kv in q.items())).get('rows', [])


def has(s, text, **q):
    return any(text in r.get('wire', '') for r in history(s, **dict({'limit': '200'}, **q)))


def until(fn, seconds, every=3):
    end = time.time() + seconds
    while time.time() < end:
        if fn():
            return True
        time.sleep(every)
    return bool(fn())


def took(t0):
    return '%d s' % round(time.time() - t0)


def seed_settings(root, name):
    """Before a station starts: the public rooms' moderators it will find
    kept (10.10.3), asked for just now, so it does not replace them with
    the published list."""
    d = os.path.join(root, name, '.local', 'share', 'xprs')
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, 'server_settings.json'), 'w') as f:
        json.dump({'xprs.publicMods.json': json.dumps({'moderators': [{'npub': npub(MOD_KEY)}]}),
                   'xprs.publicMods.asked': int(time.time() * 1000)}, f)


def start(binary, root, name, hub_port, hub_host='127.0.0.1'):
    """One station, its settings seeded before it starts."""
    http_port, rns_port = PORTS[name]
    s = ia.Station.__new__(ia.Station)
    s.dir = os.path.join(root, name)
    s.log = os.path.join(root, name + '.log')
    s.base = 'http://127.0.0.1:%d' % http_port
    os.makedirs(s.dir)
    seed_settings(root, name)
    cfg = os.path.join(root, name + '.yaml')
    subprocess.run([binary, 'init-config', '--config', cfg], check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    s.out = open(os.path.join(root, name + '.out'), 'wb')
    s.proc = subprocess.Popen(
        [binary, 'run', '--config', cfg, '--data-dir', s.dir,
         '--http-address', '127.0.0.1', '--http-port', str(http_port),
         '--rns-port', str(rns_port), '--hub', '%s:%d' % (hub_host, hub_port),
         '--nickname', 'fed-' + name, '--no-public-name', '--no-upnp', '--no-lan',
         '--auto-update', 'off', '--log-file', s.log],
        cwd=root, stdout=s.out, stderr=subprocess.STDOUT)
    s.call = ''
    s.name = name
    return s


class Live:
    """A station that is already running (the one installed on this machine):
    reached by its API, never started or stopped here. Its log is the
    service's journal."""

    def __init__(self, base, unit):
        self.base, self.unit, self.name, self.call = base.rstrip('/'), unit, 'a', ''
        self.since = time.strftime('%Y-%m-%d %H:%M:%S')

    def wait_up(self, seconds=20):
        st, d = get_json(self.base + '/api/services')
        self.call = d.get('station', '') if st == 200 else ''
        return bool(self.call)

    def logged(self, text):
        try:
            out = subprocess.run(['journalctl', '-u', self.unit, '--since', self.since, '--no-pager'],
                                 capture_output=True, text=True, timeout=30).stdout
        except Exception:
            return []
        return [line for line in out.splitlines() if text in line]

    def stop(self):
        pass


# ---- the scenarios ---------------------------------------------------------

said = []      # (who, identifier) of what was said in a public room, to withdraw


def wire_id_of(s, text):
    for r in history(s, limit='200'):
        if text in r.get('wire', ''):
            return r.get('id') or wire_id(r['wire'])
    return ''


def rooms(a, b, c, people, wait, seed):
    ana, bea, cat = people['ana'], people['bea'], people['cat']
    g = 'fed global %d' % seed
    r = 'fed regional %d' % seed
    l = 'fed local %d' % seed
    t0 = time.time()
    st, d = bea.send('t:message f:%s ts:%s scope:global m:%s' % (bea.call, ts(), g))
    check(st == 200, 'bea says something in the Global room at B', d)
    gid = d.get('id', '')
    st, d = bea.send('t:message f:%s ts:%s scope:regional m:%s' % (bea.call, ts(), r))
    check(st == 200, 'and in B\'s Regional room', d)
    st, d = bea.send('t:message f:%s ts:%s scope:local m:%s' % (bea.call, ts(), l))
    check(st == 200, 'and in B\'s Local room', d)
    check(until(lambda: has(b, g) and has(b, r) and has(b, l), 60), 'B serves all three to its own visitors')
    check(until(lambda: has(a, g, room='global'), wait), 'A, which B dials, reads the Global message (%s)' % took(t0))
    check(until(lambda: has(c, g, room='global'), wait),
          'C, which never met B, reads it too (%s)' % took(t0))
    # Regional and Local are the archiver's own: given the same time and
    # more, they are nowhere else. Asked every way a visitor can ask.
    time.sleep(20)
    for s in (a, c):
        check(not has(s, r) and not has(s, r, room='regional') and not has(s, r, kind='message'),
              '%s has nothing of B\'s Regional room' % s.name.upper())
        check(not has(s, l) and not has(s, l, room='local'),
              '%s has nothing of B\'s Local room' % s.name.upper())
    # And the other direction: what is said at C reaches B.
    g2 = 'fed global back %d' % seed
    t0 = time.time()
    st, d = cat.send('t:message f:%s ts:%s scope:global m:%s' % (cat.call, ts(), g2))
    check(st == 200 and until(lambda: has(b, g2, room='global'), wait),
          'what cat says in Global at C is read at B (%s)' % took(t0))
    g3 = 'fed global from a %d' % seed
    t0 = time.time()
    st, d = ana.send('t:message f:%s ts:%s scope:global m:%s' % (ana.call, ts(), g3))
    check(st == 200 and until(lambda: has(b, g3, room='global') and has(c, g3, room='global'), wait),
          'what ana says in Global at A is read at B and C (%s)' % took(t0))
    said.extend([(bea, gid), (cat, wire_id_of(c, g2)), (ana, d.get('id', ''))])
    return gid, g


def who(a, b, c, people, wait):
    bea, cat = people['bea'], people['cat']
    for p in (bea, cat):
        st = p.prove()
        check(st == 200, '%s has a session at %s' % (p.name, p.home.name.upper()), st)
        if p.reply.get('holders') == []:
            st, d = p.send('t:mailbox f:%s ts:%s hold:%s until:%s' % (p.call, ts(), p.home.call, ts(30 * 86400)))
            check(st == 200, '%s declares %s her mailbox' % (p.name, p.home.name.upper()), d)
        p.prove()
        check(p.reply.get('holders') == [p.home.call], 'and %s says it holds for her' % p.home.name.upper(), p.reply)
    t0 = time.time()
    knows = lambda s, p: p.home.call in (
        jget('%s/api/xprs/archiver?call=%s' % (s.base, p.call)).get('holders_of') or [])
    check(until(lambda: knows(b, cat), wait), 'B knows cat is cared for by C (%s)' % took(t0))
    check(until(lambda: knows(c, bea), wait), 'C knows bea is cared for by B (%s)' % took(t0))
    check(until(lambda: knows(a, cat) and knows(a, bea), wait), 'A knows both (%s)' % took(t0))


def mail(a, b, c, people, wait, seed):
    bea, cat = people['bea'], people['cat']
    note = 'fed mail %d' % seed
    t0 = time.time()
    st, d = bea.send('t:message f:%s d:%s ts:%s m:%s' % (bea.call, cat.call, ts(), note))
    check(st == 200, 'bea, at B, writes to cat, who is at C', d)
    mid = d.get('id', '')
    in_box = lambda: any(note in r.get('wire', '') for r in cat.mail()[1].get('rows', []))
    check(until(in_box, wait), 'cat finds it in her mailbox at C (%s)' % took(t0))
    check(not has(a, note) and not has(c, note) and not has(b, note),
          'and nobody without a session reads it anywhere')
    if mid:
        st, d = cat.send('t:receipt f:%s d:%s ts:%s r:%s s:ack' % (cat.call, bea.call, ts(), mid))
        check(st == 200, 'cat acknowledges it at C', d)
        # The receipt is mail too (12.8.3 step 5): it releases every held
        # copy on its way back and reaches the writer's own archiver, where
        # she reads it as mail addressed to her.
        released = lambda s: bool(s.logged('receipt from %s released' % cat.call))
        check(until(lambda: released(c), 30), 'which releases the copy C held')
        check(until(lambda: released(b), wait), 'and the copy B held, where it was written (%s)' % took(t0))


def mail_with_a(a, b, c, people, wait, seed):
    """The same, with the station everybody dials as one end."""
    ana, bea = people['ana'], people['bea']
    st = ana.prove()
    check(st == 200, 'ana has a session at A', st)
    if ana.reply.get('holders') == []:
        st, d = ana.send('t:mailbox f:%s ts:%s hold:%s until:%s' % (ana.call, ts(), a.call, ts(86400)))
        check(st == 200, 'ana declares A her mailbox', d)
    for who, to, at, note in ((bea, ana, 'A', 'fed mail to a %d' % seed), (ana, bea, 'B', 'fed mail from a %d' % seed)):
        t0 = time.time()
        st, d = who.send('t:message f:%s d:%s ts:%s m:%s' % (who.call, to.call, ts(), note))
        check(st == 200, '%s writes to %s' % (who.name, to.name), d)
        to.prove()
        in_box = lambda: any(note in r.get('wire', '') for r in to.mail()[1].get('rows', []))
        check(until(in_box, wait), '%s finds it in her mailbox at %s (%s)' % (to.name, at, took(t0)))
        if d.get('id'):
            to.send('t:receipt f:%s d:%s ts:%s r:%s s:ack' % (to.call, who.call, ts(), d['id']))


def files(a, b, c, wait):
    data = os.urandom(40 * 1024)
    ref = ref_of(data, 'png')
    sha = hashlib.sha256(data).hexdigest()
    st, body = http('POST', b.base + '/api/xprs/file/' + ref, data)
    check(st == 200, 'B keeps a 40 kB file', body[:80])
    check(http('GET', c.base + '/api/xprs/file/' + ref)[0] == 404, 'C does not hold it')
    t0 = time.time()

    def holders(s):
        d = jget('%s/api/xprs/files?sha256=%s' % (s.base, sha))
        return d.get('holders_of') or []
    check(until(lambda: b.call in holders(c), wait),
          'C knows, by the hash alone, that B holds it (%s)' % took(t0), holders(c))
    check(until(lambda: b.call in holders(a), wait),
          'A knows too (%s)' % took(t0), holders(a))
    # And so C fetches it without being told where from.
    st, body = http('POST', c.base + '/api/xprs/file', json.dumps(
        {'sha256': sha, 'ext': 'png', 'timeoutSeconds': 120}).encode(), timeout=150)
    try:
        d = json.loads(body)
    except Exception:
        d = {}
    check(d.get('ok') is True, 'C fetches it from whoever holds it (%s)' % took(t0), d)
    st, got = http('GET', c.base + '/api/xprs/file/' + ref)
    check(st == 200 and got == data, 'and serves the same bytes')


def moderator(a, b, c, people, wait, seed, gid, text):
    listed = npub(MOD_KEY)
    for s in (a, b, c):
        pm = jget(s.base + '/api/admin').get('public_moderators')
        check(pm == [listed], '%s honours the listed key' % s.name.upper(), pm)
    if not gid:
        return check(False, 'a Global message to remove')
    check(has(a, text) and has(c, text), 'the Global message is at A and C')
    mod = Person('mod', MOD_KEY, c)
    t0 = time.time()
    st, d = mod.send('t:moderate f:%s ts:%s r:%s remove:message' % (mod.call, ts(), gid))
    check(st == 200, 'the moderator removes it at C', d)
    check(until(lambda: not has(c, text), 30), 'it is gone at C')
    check(until(lambda: not has(a, text), wait), 'gone at A (%s)' % took(t0))
    check(until(lambda: not has(b, text), wait), 'gone at B, where it was said (%s)' % took(t0))
    # A late copy does not bring it back: B is asked for the room again.
    time.sleep(30)
    check(not has(a, text) and not has(b, text) and not has(c, text), 'and it stays gone')
    eve = people['ana']
    st, _ = eve.send('t:moderate f:%s ts:%s r:%s remove:message' % (eve.call, ts(), gid), a)
    check(st == 403, 'a key that is not listed removes nothing anywhere', st)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--server', required=True, help='the server edition binary')
    ap.add_argument('--dir', help='where the stations live (default: a temp folder)')
    ap.add_argument('--keep', action='store_true', help='leave the folders and logs')
    ap.add_argument('--wait', type=int, default=240, help='how long one crossing may take')
    ap.add_argument('--only', default='rooms,who,mail,files,moderator')
    ap.add_argument('--live', help='use this running station as A (its API, e.g. http://127.0.0.1)')
    ap.add_argument('--live-hub', default='127.0.0.1:4242', help='where B and C dial it')
    ap.add_argument('--live-unit', default='xprs-server', help='its systemd unit, for its log')
    args = ap.parse_args()
    only = set(args.only.split(','))
    binary = os.path.abspath(args.server)
    root = os.path.abspath(args.dir) if args.dir else tempfile.mkdtemp(prefix='xprs-fed-')
    if args.dir:
        shutil.rmtree(root, ignore_errors=True)
        os.makedirs(root)
    seed = int(time.time()) % 100000
    if args.live:
        # The real station takes part. What is said in its Global room is
        # read by real people, so the run says little, withdraws it at the
        # end, and leaves the moderator out (the key this test lists is not
        # one the real station believes).
        only.discard('moderator')
        a = Live(args.live, args.live_unit)
        host, port = args.live_hub.rsplit(':', 1)
        b = start(binary, root, 'b', int(port), hub_host=host)
        c = start(binary, root, 'c', int(port), hub_host=host)
    else:
        a = start(binary, root, 'a', DEAD_PORT)
        b = start(binary, root, 'b', PORTS['a'][1])
        c = start(binary, root, 'c', PORTS['a'][1])
    ss = (a, b, c)
    try:
        if not all(check(s.wait_up(), 'station %s is up' % s.name.upper()) for s in ss):
            return 1
        print('A is %s, B is %s, C is %s; folders in %s' % (a.call, b.call, c.call, root))
        if args.live:
            # B and C meet through the real station and whatever it is
            # joined to; that they can reach each other is what the
            # scenarios below show. Time for the announces to cross.
            time.sleep(45)
        else:
            met = lambda: all(x.logged('RNS: learned ' + y.call) for x in ss for y in ss if x is not y)
            check(until(met, 180), 'each has learned the other two over Reticulum',
                  [(x.name, y.name) for x in ss for y in ss if x is not y and not x.logged('RNS: learned ' + y.call)])
        people = {
            'ana': Person('ana', '11' * 31 + '%02x' % (seed % 250 + 1), a),
            'bea': Person('bea', '22' * 31 + '%02x' % (seed % 250 + 2), b),
            'cat': Person('cat', '33' * 31 + '%02x' % (seed % 250 + 3), c),
        }
        for p in people.values():
            check(p.identity()[0] == 200, '%s (%s) is known at %s' % (p.name, p.call, p.home.name.upper()))
        gid, text = '', ''
        if 'rooms' in only or 'moderator' in only:
            print('rooms')
            gid, text = rooms(a, b, c, people, args.wait, seed)
        if 'who' in only or 'mail' in only:
            print('who is cared for where')
            who(a, b, c, people, args.wait)
        if 'mail' in only:
            print('mail from a person at B to a person at C')
            mail(a, b, c, people, args.wait, seed)
        if 'mail' in only and args.live:
            print('mail to and from a person at A')
            mail_with_a(a, b, c, people, args.wait, seed)
        if 'files' in only:
            print('files by their hash')
            files(a, b, c, args.wait)
        if 'moderator' in only:
            print('the public rooms\' moderator')
            moderator(a, b, c, people, args.wait, seed, gid, text)
    finally:
        if args.live:
            # Its author takes back what the run said in the public room.
            for author, mid in said:
                if mid:
                    author.send('t:message f:%s ts:%s scope:global r:%s remove:message' % (author.call, ts(), mid))
            time.sleep(8)
        for s in ss:
            r = jget(s.base + '/api/xprs/archiver')
            f = jget(s.base + '/api/xprs/files')
            print('%s: handed on %s; file index %s; forwarder %s; archivers %s' % (
                s.name.upper(), r.get('handedOn'), f.get('index'), r.get('forwarder'), r.get('archivers')))
        for s in ss:
            s.stop()
        if not args.keep and not ia.failures:
            shutil.rmtree(root, ignore_errors=True)
        else:
            print('folders and logs kept in %s' % root)
    print('\n%d failure(s)' % len(ia.failures) if ia.failures else '\nall passed')
    return 1 if ia.failures else 0


if __name__ == '__main__':
    sys.exit(main())
