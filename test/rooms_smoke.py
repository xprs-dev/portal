#!/usr/bin/env python3
"""A hosted room in two browsers against a real station (the server edition
or a board): the administrator and a member.

    python3 tool/build.py && python3 test/rooms_smoke.py http://127.0.0.1:8099/

The station must be fresh (no administrator yet) and reached from its own
network, so the first browser can claim it. Checks:
  - the member joins, posts, and the room's moderator menu acts on the ROOM
    (d:<room>), not on the station (XPRS.md 10.4.1);
  - Close to new posts (10.4.2): the member sees why and cannot write; a
    moderator still can; Open lets the member write again;
  - Leave (10.3): the member is no longer one.
"""
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from cdp import Cdp  # noqa: E402

URL = sys.argv[1] if len(sys.argv) > 1 else 'http://127.0.0.1:8099/'
SHOTS = os.environ.get('SHOTS', '')
fails = 0


def check(ok, what):
    global fails
    print(('  [PASS] ' if ok else '  [FAIL] ') + what)
    fails += 0 if ok else 1


def shot(c, name):
    if not SHOTS:
        return
    import base64
    d = c.send('Page.captureScreenshot', {'format': 'png'})['data']
    with open(os.path.join(SHOTS, name + '.png'), 'wb') as f:
        f.write(base64.b64decode(d))


def phone(c):
    c.send('Emulation.setDeviceMetricsOverride',
           {'width': 412, 'height': 860, 'deviceScaleFactor': 1, 'mobile': True})


def room_note(c):
    return c.eval("document.getElementById('msgs').innerText") or ''


def main():
    prof = os.path.expanduser('~/snap/chromium/common/rooms-smoke-')
    a = Cdp('chromium', prof + 'a')
    b = Cdp('chromium', prof + 'b')
    try:
        for c in (a, b):
            c.attach()
            phone(c)
            c.load(URL)
        time.sleep(4)  # past the look for an extension: each makes a key
        alice = a.wait('mycall')
        bob = b.wait('mycall')
        check(bool(alice and bob), 'two visitors with keys: %s %s' % (alice, bob))

        a.eval("(openView('admin'),1)")
        a.wait("!!document.getElementById('ad-claim')")
        a.eval("document.getElementById('ad-claim').click()")
        check(a.wait('isStationAdmin', 10), 'the first visitor claims the station')
        a.eval("(showTab('chat'),1)")

        a.eval("roomPost({action:'create',name:'Block C',visibility:'public',"
               "posting:'members'},function(j){window.__room=j.room;})")
        room = a.wait('window.__room', 10)
        check(bool(room), 'the administrator makes a room: %s' % room)
        a.eval("loadRooms(function(){})")
        # The page accepts the moderator offer the station makes its administrator.
        if a.wait("hostedByCall[%s]&&hostedByCall[%s].role==='invited'" % (json.dumps(room), json.dumps(room)), 5):
            a.eval("var h=hostedByCall[%s];acceptRoom(h.call,h.offer,h.offer_role)" % json.dumps(room))
        check(a.wait("loadRooms(function(){}),hostedByCall[%s]&&hostedByCall[%s].role==='mod'"
                     % (json.dumps(room), json.dumps(room)), 10), 'the administrator moderates it')

        # Bob is no member: he may ask to join (10.3), and only staff read it.
        b.eval("loadRooms(function(){switchRoom('g:'+%s)})" % json.dumps(room))
        check(b.wait("!el('txt').disabled&&el('txt').placeholder.indexOf('Ask to join')==0", 8),
              'a visitor who is no member is offered to ask to join')
        shot(b, 'room_ask')
        b.eval("el('txt').value='may I join?';sendMsg()")
        time.sleep(2)
        a.eval("loadRooms(function(){switchRoom('g:'+%s)})" % json.dumps(room))
        check(a.wait("!!document.querySelector('#msgs [data-grant]')", 10),
              'the administrator sees the request, with Invite')
        shot(a, 'room_request')
        a.eval("document.querySelector('#msgs [data-grant]').click()")
        time.sleep(1.5)
        b.eval("loadRooms(function(){switchRoom('g:'+%s)})" % json.dumps(room))
        b.wait("!!document.querySelector('#msgs .roomnote button')")
        b.eval("document.querySelector('#msgs .roomnote button').click()")
        check(b.wait("loadRooms(function(){}),hostedByCall[%s]&&hostedByCall[%s].role==='member'"
                     % (json.dumps(room), json.dumps(room)), 10), 'the member joins with Join')

        b.eval("(switchRoom('g:'+%s),1)" % json.dumps(room))
        time.sleep(1)
        check('Leave' in room_note(b) and 'Close to new posts' not in room_note(b),
              'a member is offered Leave, not Close')
        b.eval("el('txt').value='hello block';sendMsg()")
        time.sleep(2)

        a.eval("(switchRoom('g:'+%s),1)" % json.dumps(room))
        check(a.wait("document.getElementById('msgs').innerText.indexOf('hello block')>=0", 10),
              'the administrator reads the member\'s message')
        shot(a, 'room_admin')
        check(a.eval("modHere()") and a.eval("modTarget()") == room,
              'its moderator menu is the room\'s and acts on the room')
        # Delete for everyone: the act names the room.
        mid = a.eval("(function(){for(var i=0;i<allRows.length;i++){var r=allRows[i];"
                     "if((r.wire||'').indexOf('hello block')>=0)return r.id;}return ''})()")
        sent = []
        a.eval("window.__w=[];var _pw=postWire;postWire=function(w,cb){__w.push(w);_pw(w,cb)};"
               "window.confirm=function(){return true};1")
        a.eval("modDelete(%s)" % json.dumps(mid))
        sent = a.wait("__w.length&&__w", 8) or []
        check(any(' d:%s ' % room in w and 'remove:message' in w for w in sent),
              'Delete for everyone is signed d:%s' % room)

        # Close to new posts, from the room's own line.
        a.eval("(switchRoom('g:'+%s),1)" % json.dumps(room))
        a.wait("[].some.call(document.querySelectorAll('#msgs .roomnote button'),function(e){"
               "return e.textContent==='Close to new posts'})")
        a.eval("[].filter.call(document.querySelectorAll('#msgs .roomnote button'),function(e){"
               "return e.textContent==='Close to new posts'})[0].click()")
        check(a.wait("loadRooms(function(){}),hostedByCall[%s].state==='closed'" % json.dumps(room), 10),
              'the moderator closes the room to new posts')
        b.eval("loadRooms(function(){switchRoom('g:'+%s)})" % json.dumps(room))
        check(b.wait("document.getElementById('msgs').innerText.indexOf('closed to new posts')>=0", 8)
              and b.eval("el('txt').disabled"),
              'the member sees it closed, and the box is off')
        shot(b, 'room_closed_member')
        a.eval("(switchRoom('g:'+%s),1)" % json.dumps(room))
        time.sleep(1)
        check(not a.eval("el('txt').disabled") and 'Open to posts' in room_note(a),
              'the moderator still writes, and is offered Open')
        shot(a, 'room_closed_mod')
        a.eval("[].filter.call(document.querySelectorAll('#msgs .roomnote button'),function(e){"
               "return e.textContent==='Open to posts'})[0].click()")
        b.eval("loadRooms(function(){})")
        check(b.wait("loadRooms(function(){}),hostedByCall[%s].state==='open'&&hostedByCall[%s].can_post"
                     % (json.dumps(room), json.dumps(room)), 10), 'opened: the member may write again')

        # An open group by name (XPRS.md 7.3): followed, written, read.
        b.eval("window.prompt=function(){return 'lisboa'};(switchRoom('onew'),1)")
        check(b.wait("curRoom==='o:LISBOA'&&myGroups.indexOf('LISBOA')>=0", 5),
              'a visitor follows the open group LISBOA by name')
        b.eval("el('txt').value='bom dia lisboa';sendMsg()")
        time.sleep(2)
        a.eval("window.prompt=function(){return 'LISBOA'};(switchRoom('onew'),1)")
        check(a.wait("document.getElementById('msgs').innerText.indexOf('bom dia lisboa')>=0", 12),
              'another visitor reads it in LISBOA')
        shot(a, 'group_open')

        # Leave.
        b.eval("window.confirm=function(){return true};(switchRoom('g:'+%s),leaveRoom(%s),1)"
               % (json.dumps(room), json.dumps(room)))
        check(b.wait("loadRooms(function(){}),hostedByCall[%s]&&hostedByCall[%s].role==='none'"
                     % (json.dumps(room), json.dumps(room)), 10), 'the member leaves')
    finally:
        a.close()
        b.close()
    print('FAILED' if fails else 'all passed')
    sys.exit(1 if fails else 0)


main()
