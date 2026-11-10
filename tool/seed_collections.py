#!/usr/bin/env python3
"""Fill a station's Gallery, Music and Library from a folder of files, through
the page itself (headless Chromium), as a moderator would: the page makes the
previews (a photo's, a film's frame), hashes, uploads and posts.

    seed_collections.py MANIFEST.json --station http://127.0.0.1 \
        --signer 'sudo -u xprs env HOME=/var/lib/xprs-server /opt/xprs-server/xprs-server sign'

The signer is a command that reads canonical wires on stdin and writes them
signed, one a line (the server's `xprs-server sign`): the page signs with it
as the station, which is the station's operator (API-HTTP.md, /api/admin).
--as is the callsign the signer signs for.

The manifest:
    {"gallery": [{"name": "...", "about": "...", "folders": [
        {"title": "...", "about": "...", "files": ["photos/a.jpg", ...]}]}],
     "music": [...], "library": [...]}
paths relative to the manifest's folder.
"""
import argparse
import http.server
import json
import mimetypes
import os
import subprocess
import sys
import threading
import time
import urllib.parse

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'test'))
from cdp import Cdp  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument('manifest')
ap.add_argument('--station', default='http://127.0.0.1')
ap.add_argument('--signer', required=True)
ap.add_argument('--as', dest='call', required=True)
ap.add_argument('--browser', default=os.environ.get('WEBCHAT_BROWSER', '/usr/bin/chromium'))
ap.add_argument('--port', type=int, default=9939)
a = ap.parse_args()
root = os.path.dirname(os.path.abspath(a.manifest))
manifest = json.load(open(a.manifest))

signer = subprocess.Popen(a.signer, shell=True, stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
lock = threading.Lock()


class Helper(http.server.BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_GET(self):
        u = urllib.parse.urlparse(self.path)
        q = urllib.parse.parse_qs(u.query)
        if u.path == '/sign':
            with lock:
                signer.stdin.write(q['w'][0].replace('\n', ' ') + '\n')
                signer.stdin.flush()
                out = signer.stdout.readline().strip().encode()
            ctype = 'text/plain; charset=utf-8'
        elif u.path == '/file':
            p = os.path.realpath(os.path.join(root, q['p'][0]))
            if not p.startswith(root + os.sep):
                self.send_response(403)
                self.end_headers()
                return
            out = open(p, 'rb').read()
            ctype = mimetypes.guess_type(p)[0] or 'application/octet-stream'
        else:
            self.send_response(404)
            self.end_headers()
            return
        self.send_response(200)
        self.send_header('Content-Type', ctype)
        self.send_header('Content-Length', str(len(out)))
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()
        self.wfile.write(out)


srv = http.server.ThreadingHTTPServer(('127.0.0.1', a.port), Helper)
threading.Thread(target=srv.serve_forever, daemon=True).start()
H = 'http://127.0.0.1:%d' % a.port

c = Cdp(a.browser, '/tmp/seed-collections-profile-%d' % os.getpid())
try:
    c.attach()
    c.load(a.station + '/')
    # The page signs as the station, through the helper.
    c.eval("""(function(){
      mycall=%s;priv=1;extMode=false;sendIdentity=function(){};
      signAny=function(w,cb){fetch(%s+'/sign?w='+encodeURIComponent(w)).then(function(r){return r.text();})
        .then(function(t){cb(t.trim()||null);},function(){cb(null);});};
      window.__snacks=[];var os=snack;snack=function(t){window.__snacks.push(t);os(t);};
      sess='';ensureSession(0);return 1;})()""" % (json.dumps(a.call), json.dumps(H)))
    if not c.wait('!!sess', 20):
        sys.exit('no session as %s' % a.call)
    c.eval('isStationAdmin=true')
    print('session as', a.call)

    def until(expr, what, seconds=30):
        if not c.wait(expr, seconds):
            sys.exit('stuck: ' + what)

    for kind in ('gallery', 'music', 'library'):
        for cat in manifest.get(kind, []):
            c.eval("(switchRoom(%s),1)" % json.dumps(kind))
            until("canGallery&&!!el('gc-name')", kind + ' list')
            have = c.eval("(function(){var l=galRooms();for(var i=0;i<l.length;i++)if(l[i].name===%s)return l[i].call;return ''})()"
                          % json.dumps(cat['name']))
            if have:
                c.eval("(galOpen(%s),1)" % json.dumps(have))
            else:
                c.eval("(el('gc-name').value=%s,el('gc-about').value=%s,galNewCategory(),1)"
                       % (json.dumps(cat['name']), json.dumps(cat.get('about', ''))))
            until("!!galCat&&!!el('ge-title')", 'category ' + cat['name'])
            for fol in cat['folders']:
                c.eval("(galEvent=null,loadGallery(true),1)")
                until("!!el('ge-title')", 'folder form')
                slug = c.eval("slugOf(%s)" % json.dumps(fol['title']))
                fid = c.eval("""(function(){var x=new XMLHttpRequest();x.open('GET','/api/rooms?topics='+galCat+'&session='+encodeURIComponent(sess),false);x.send();
                  var t=(JSON.parse(x.responseText).topics||[]);for(var i=0;i<t.length;i++)if(t[i].title===%s)return t[i].id;return ''})()""" % json.dumps(slug))
                if fid:
                    c.eval("(galOpenEvent(%s,%s),1)" % (json.dumps(fid), json.dumps(slug)))
                else:
                    c.eval("(el('ge-title').value=%s,el('ge-about').value=%s,galNewEvent(),1)"
                           % (json.dumps(fol['title']), json.dumps(fol.get('about', ''))))
                until("!!galEvent&&!!el('gal-up')&&!!galRows", 'folder ' + fol['title'], 20)
                have_files = set(c.eval("galRows?Object.keys(galRows.orig).map(function(k){return galRows.orig[k].name}):[]") or [])
                for f in fol['files']:
                    if os.path.basename(f).lower().replace(' ', '-') in have_files or c.eval(
                            "slugOf(%s)+'.'+mdExtOf(%s,'')" % (json.dumps(os.path.splitext(os.path.basename(f))[0]), json.dumps(f))) in have_files:
                        print('  already there:', f)
                        continue
                    t0 = time.time()
                    # Picked as a person picks a file: a file input, so the
                    # page gets the file on disk, not a copy in memory.
                    c.eval("(function(){var i=document.getElementById('seedfile');if(!i){i=document.createElement('input');"
                           "i.type='file';i.id='seedfile';i.style.display='none';document.body.appendChild(i);}return 1;})()")
                    doc = c.send('DOM.getDocument', {'depth': 1})
                    node = c.send('DOM.querySelector', {'nodeId': doc['root']['nodeId'], 'selector': '#seedfile'})['nodeId']
                    c.send('DOM.setFileInputFiles', {'nodeId': node, 'files': [os.path.join(root, f)]})
                    c.eval("""(window.__seedDone=0,galUpload(document.getElementById('seedfile').files[0],galRoom(),galEvent,
                      function(){},function(){window.__seedDone=1;}),1)""")
                    until('window.__seedDone===1', 'upload ' + f, 1800)
                    said = c.eval("window.__snacks.splice(0).join(' | ')")
                    print('  %s / %s / %s: %s (%.1fs)%s' % (kind, cat['name'], fol['title'], f, time.time() - t0,
                                                         ('  the page said: ' + said) if said else ''))
    print('done')
finally:
    c.close()
    srv.shutdown()
    signer.stdin.close()
