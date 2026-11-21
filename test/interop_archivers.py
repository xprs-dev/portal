#!/usr/bin/env python3
"""Archivers against each other: two server-edition stations on this machine.

The first scenario of the archiver interop run (app docs/plan-archiver-tests.md,
layer 3). It starts two throwaway stations, each with its own data folder,
ports and config, joined by a private Reticulum link (B dials A; no public
hub), and checks what one archiver owes another:

  files     a file of several pieces put on A is found on A by B, fetched BY
            PIECES (spec 7.7.2, 11.2), verified, and then served by B too;
            a file of one piece is fetched whole; a file nobody holds is
            refused, not waited for.
  readings  each station answers /api/xprs/archiver and /api/xprs/files to a
            caller on the machine, with the keys a conformance run reads.

Usage:
    python3 test/interop_archivers.py --server ../server/build/xprs-server-linux-arm64
        [--keep] [--dir /path/for/the/two/stations]

Both stations sit on the machine's LAN lane like any station, so they hear
and relay what is on the air there for as long as the run lasts (about a
minute). --keep leaves their folders and logs behind for reading.
"""
import argparse
import base64
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request

A_HTTP, A_RNS = 18081, 14241
B_HTTP, B_RNS = 18082, 14242
DEAD_PORT = 14249
failures = []


def check(ok, what, detail=''):
    print(('  ok   ' if ok else '  FAIL ') + what + (f'  [{detail}]' if detail and not ok else ''))
    if not ok:
        failures.append(what)
    return ok


def http(method, url, body=None, timeout=200):
    req = urllib.request.Request(url, data=body, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()
    except Exception as e:  # refused, timed out
        return 0, str(e).encode()


def get_json(url):
    st, b = http('GET', url, timeout=10)
    try:
        return st, json.loads(b)
    except Exception:
        return st, {}


def ref_of(data, ext):
    return base64.urlsafe_b64encode(hashlib.sha256(data).digest()).decode().rstrip('=') + '.' + ext


class Station:
    def __init__(self, binary, root, name, http_port, rns_port, hub_port):
        self.dir = os.path.join(root, name)
        self.log = os.path.join(root, name + '.log')
        self.base = f'http://127.0.0.1:{http_port}'
        os.makedirs(self.dir)
        cfg = os.path.join(root, name + '.yaml')
        subprocess.run([binary, 'init-config', '--config', cfg], check=True,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.out = open(os.path.join(root, name + '.out'), 'wb')
        self.proc = subprocess.Popen(
            [binary, 'run', '--config', cfg, '--data-dir', self.dir,
             '--http-address', '127.0.0.1', '--http-port', str(http_port),
             '--rns-port', str(rns_port), '--hub', f'127.0.0.1:{hub_port}',
             '--nickname', 'interop-' + name, '--no-public-name', '--no-upnp',
             '--auto-update', 'off', '--log-file', self.log],
            cwd=root, stdout=self.out, stderr=subprocess.STDOUT)
        self.call = ''

    def wait_up(self, seconds=60):
        end = time.time() + seconds
        while time.time() < end:
            st, d = get_json(self.base + '/api/services')
            if st == 200 and d.get('station'):
                self.call = d['station']
                return True
            if self.proc.poll() is not None:
                return False
            time.sleep(1)
        return False

    def logged(self, text):
        try:
            with open(self.log, errors='replace') as f:
                return [line for line in f if text in line]
        except OSError:
            return []

    def stop(self):
        if self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(10)
            except subprocess.TimeoutExpired:
                self.proc.kill()
        self.out.close()


def readings(s):
    st, a = get_json(s.base + '/api/xprs/archiver')
    check(st == 200 and a.get('ok') and a.get('archiver') == s.call,
          f'{s.call}: the archiver reading names the station', a.get('archiver'))
    check(all(k in a for k in ('public', 'archivers', 'records', 'catchup', 'gossip', 'deposited')),
          f'{s.call}: and carries what a run reads', sorted(a)[:6])
    st, f = get_json(s.base + '/api/xprs/files')
    check(st == 200 and all(k in f for k in ('server', 'fetch', 'spool')),
          f'{s.call}: the files reading names both ends and the spool', sorted(f))


def fetch(b, holder, data, ext, seconds=150):
    sha = hashlib.sha256(data).hexdigest()
    t = time.time()
    st, body = http('POST', b.base + '/api/xprs/file', json.dumps(
        {'from': holder, 'sha256': sha, 'ext': ext, 'timeoutSeconds': seconds}).encode(),
        timeout=seconds + 30)
    try:
        d = json.loads(body)
    except Exception:
        d = {}
    return d.get('ok') is True, round(time.time() - t, 1), d


def files(a, b):
    # A file of several pieces: 900 kB is fourteen pieces of 64 kB and a short one.
    big = os.urandom(900 * 1024)
    ref = ref_of(big, 'jpg')
    sha8 = hashlib.sha256(big).hexdigest()[:8]
    st, body = http('POST', a.base + '/api/xprs/file/' + ref, big)
    check(st == 200, f'{a.call} keeps a 900 kB file', body[:80])
    # It advertises the file with its piece list (a holder others can find).
    end = time.time() + 30
    while time.time() < end and not a.logged(f'piece list for {sha8}'):
        time.sleep(1)
    check(bool(a.logged(f'piece list for {sha8} (15 pieces)')),
          f'{a.call} cut its piece list: 15 pieces')
    check(http('GET', b.base + '/api/xprs/file/' + ref)[0] == 404,
          f'{b.call} does not hold it yet')

    ok, took, d = fetch(b, a.call, big, 'jpg')
    check(ok, f'{b.call} fetched it from {a.call} in {took} s', d)
    check(bool(b.logged(f'piece swarm for {sha8}')),
          f'{b.call} took it BY PIECES (spec 7.7.2), not whole from one holder')
    check(bool(a.logged('(921600B) -> ' + b.call + ' (202)')),
          f'{a.call} answered the ask 202')
    st, got = http('GET', b.base + '/api/xprs/file/' + ref)
    check(st == 200 and got == big, f'{b.call} now holds the same bytes and serves them')
    end = time.time() + 30
    while time.time() < end and not b.logged(f'piece list for {sha8}'):
        time.sleep(1)
    check(bool(b.logged(f'piece list for {sha8} (15 pieces)')),
          f'{b.call} became a holder: it advertises the file with the same piece list')

    # A file of one piece needs no list and is fetched whole.
    small = os.urandom(20 * 1024)
    sref = ref_of(small, 'png')
    s8 = hashlib.sha256(small).hexdigest()[:8]
    check(http('POST', a.base + '/api/xprs/file/' + sref, small)[0] == 200,
          f'{a.call} keeps a 20 kB file')
    time.sleep(3)
    ok, took, d = fetch(b, a.call, small, 'png')
    check(ok, f'{b.call} fetched the one-piece file in {took} s', d)
    check(not a.logged(f'piece list for {s8}') and not b.logged(f'piece swarm for {s8}'),
          'a file of one piece has no piece list and no swarm')
    st, got = http('GET', b.base + '/api/xprs/file/' + sref)
    check(st == 200 and got == small, f'{b.call} serves it')

    # A file nobody holds is refused out loud, never waited for.
    ghost = os.urandom(1024)
    ok, took, d = fetch(b, a.call, ghost, 'bin', seconds=60)
    check(not ok and took < 30, f'a file {a.call} does not hold is refused in {took} s, not waited for', d)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--server', required=True, help='the server edition binary')
    ap.add_argument('--dir', help='where the two stations live (default: a temp folder)')
    ap.add_argument('--keep', action='store_true', help='leave the folders and logs')
    args = ap.parse_args()
    binary = os.path.abspath(args.server)
    root = os.path.abspath(args.dir) if args.dir else tempfile.mkdtemp(prefix='xprs-interop-')
    if args.dir:
        shutil.rmtree(root, ignore_errors=True)
        os.makedirs(root)
    # B dials A, as a station dials a hub; A dials nobody (its --hub names a
    # port nothing listens on, so it does not fall back to the public hubs).
    # Each dialling the other made two connections between them, and the
    # path to A then flipped from one to the other in the middle of a link
    # handshake: the request left on one and its proof came back on the other.
    a = Station(binary, root, 'a', A_HTTP, A_RNS, DEAD_PORT)
    b = Station(binary, root, 'b', B_HTTP, B_RNS, A_RNS)
    try:
        if not (check(a.wait_up(), 'station A is up') and check(b.wait_up(), 'station B is up')):
            return 1
        print(f'A is {a.call}, B is {b.call}; folders in {root}')
        # Two stations that know each other: each has heard the other's
        # Reticulum announce. (Asked in the first seconds after they meet, a
        # fetch still arrives, by the whole-file fallback after the piece
        # engine's 30 s wait for a holder it has no path to yet: measured
        # 35 s for 900 kB on 2026-11-21.)
        end = time.time() + 120
        while time.time() < end and not (
                b.logged('RNS: learned ' + a.call) and a.logged('RNS: learned ' + b.call)):
            time.sleep(1)
        check(bool(b.logged('RNS: learned ' + a.call)) and bool(a.logged('RNS: learned ' + b.call)),
              'each has learned the other over Reticulum')
        time.sleep(5)
        print('readings')
        readings(a)
        readings(b)
        print('files')
        files(a, b)
    finally:
        a.stop()
        b.stop()
        if not args.keep and not failures:
            shutil.rmtree(root, ignore_errors=True)
        elif failures:
            print(f'logs kept in {root}')
    print(f'\n{len(failures)} failure(s)' if failures else '\nall passed')
    return 1 if failures else 0


if __name__ == '__main__':
    sys.exit(main())
