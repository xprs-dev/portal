#!/usr/bin/env python3
"""Build the web chat page for every edition from page/.

    python3 tool/build.py                 # dist/chat_page.html and .html.gz
    python3 tool/build.py --c OUT.c       # also the C array the firmware embeds

page/chat_page.html carries four markers: /*FONTFACE*/ (replaced by
page/logo-font.css), /*CRYPTO*/ (replaced by page/xprs_crypto.js with its node
test block stripped), /*SEAL*/ (page/xprs_seal.js, which builds on it) and
/*NOSTR*/ (page/xprs_nostr.js, which uses a NOSTR extension as the signer) and
/*MD*/ (page/xprs_md.js, the formatted text of XPRS.md 4.11). The result is one self-contained HTML file, which
the firmware stores gzipped and the app serves gzipped (Content-Encoding:
gzip); mtime is 0 so an unchanged page builds to identical bytes.
"""
import argparse
import gzip
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TEST_MARK = '// ---- node test against the spec 9.1.2 worked example ----'


def read(rel):
    with open(os.path.join(ROOT, rel), encoding='utf-8') as f:
        return f.read()


def build():
    html = read('page/chat_page.html')
    js = read('page/xprs_crypto.js')
    if TEST_MARK in js:
        js = js[:js.index(TEST_MARK)]
    html = html.replace('/*FONTFACE*/', read('page/logo-font.css').rstrip('\n'))
    html = html.replace('/*CRYPTO*/', js)
    html = html.replace('/*SEAL*/', read('page/xprs_seal.js'))
    html = html.replace('/*NOSTR*/', read('page/xprs_nostr.js'))
    html = html.replace('/*MD*/', read('page/xprs_md.js'))
    return html.encode('utf-8')


def c_bytes(b):
    return '\n'.join('    ' + ' '.join('0x%02x,' % c for c in b[i:i + 16])
                     for i in range(0, len(b), 16))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--c', metavar='FILE', help='also write the C array')
    ap.add_argument('--out', default=os.path.join(ROOT, 'dist'))
    a = ap.parse_args()
    raw = build()
    gz = gzip.compress(raw, compresslevel=9, mtime=0)
    os.makedirs(a.out, exist_ok=True)
    with open(os.path.join(a.out, 'chat_page.html'), 'wb') as f:
        f.write(raw)
    with open(os.path.join(a.out, 'chat_page.html.gz'), 'wb') as f:
        f.write(gz)
    if a.c:
        with open(a.c, 'w') as f:
            f.write('/* GENERATED from webchat/page by webchat/tool/build.py '
                    '-- edit those, not this.\n *\n'
                    ' * Stored gzipped and served with Content-Encoding: gzip.\n'
                    ' * %d bytes of page -> %d bytes of flash. */\n'
                    % (len(raw), len(gz)))
            f.write('#include <stddef.h>\n\n')
            f.write('const unsigned char XPRS_CHAT_PAGE_GZ[] = {\n')
            f.write(c_bytes(gz))
            f.write('\n};\n\nconst size_t XPRS_CHAT_PAGE_GZ_LEN = '
                    'sizeof(XPRS_CHAT_PAGE_GZ);\n')
    print('chat_page: %d bytes -> %d gzipped (%d%%)'
          % (len(raw), len(gz), 100 * len(gz) // len(raw)))


if __name__ == '__main__':
    main()
