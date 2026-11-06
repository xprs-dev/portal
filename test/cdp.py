"""Headless Chrome driven over the DevTools protocol on a pipe (fds 3 and 4,
NUL-separated JSON): no websocket module needed. Shared by the browser smoke
tests (layout_smoke.py, feed_smoke.py).

    c = Cdp(browser, profile_dir); c.attach(); c.eval('1+1'); c.close()
"""
import json
import os
import shutil
import subprocess
import time


class Cdp:
    def __init__(self, browser, prof):
        shutil.rmtree(prof, ignore_errors=True)   # the page keeps its room and key
        os.makedirs(prof, exist_ok=True)
        to_chrome_r, self.w = os.pipe()
        self.r, from_chrome_w = os.pipe()

        # Chrome reads fd 3 and writes fd 4. The pipe ends may already be
        # numbered 3 or 4, so both are moved out of the way first.
        def fds():
            a, b = os.dup(to_chrome_r), os.dup(from_chrome_w)
            os.dup2(a, 3)
            os.dup2(b, 4)
        self.p = subprocess.Popen(
            [browser, '--headless=new', '--no-sandbox', '--disable-gpu',
             '--remote-debugging-pipe', '--user-data-dir=' + prof, 'about:blank'],
            pass_fds=(3, 4, to_chrome_r, from_chrome_w), preexec_fn=fds,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        os.close(to_chrome_r)
        os.close(from_chrome_w)
        self.buf = b''
        self.n = 0
        self.session = None

    def send(self, method, params=None, top=False):
        self.n += 1
        msg = {'id': self.n, 'method': method, 'params': params or {}}
        if self.session and not top:
            msg['sessionId'] = self.session
        os.write(self.w, json.dumps(msg).encode() + b'\0')
        while True:
            while b'\0' not in self.buf:
                chunk = os.read(self.r, 1 << 16)
                if not chunk:
                    raise RuntimeError('chrome went away')
                self.buf += chunk
            line, self.buf = self.buf.split(b'\0', 1)
            m = json.loads(line)
            if m.get('id') == self.n:
                if 'error' in m:
                    raise RuntimeError('%s: %s' % (method, m['error'].get('message')))
                return m.get('result', {})

    def eval(self, expr):
        r = self.send('Runtime.evaluate', {'expression': expr, 'returnByValue': True})
        return r.get('result', {}).get('value')

    def close(self):
        self.p.kill()
        self.p.wait()


    def attach(self):
        """A fresh page target, attached flat: every call after this goes to it."""
        tid = self.send('Target.createTarget', {'url': 'about:blank'}, top=True)['targetId']
        self.session = self.send('Target.attachToTarget', {'targetId': tid, 'flatten': True},
                                 top=True)['sessionId']
        self.send('Page.enable')

    def load(self, url, ready="document.readyState==='complete'&&!!document.getElementById('txt')"):
        self.send('Page.navigate', {'url': url})
        for _ in range(100):
            if self.eval(ready):
                break
            time.sleep(0.1)
        time.sleep(1.0)

    def wait(self, expr, seconds=8):
        """Poll [expr] until it is truthy; its value, or None when it never was."""
        for _ in range(int(seconds * 10)):
            v = self.eval(expr)
            if v:
                return v
            time.sleep(0.1)
        return None
