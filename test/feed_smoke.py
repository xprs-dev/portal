#!/usr/bin/env python3
"""The feeds (Alerts, Blog, Forum) in headless Chromium, against the mock.

    python3 tool/build.py && python3 test/feed_smoke.py

  - a feed has no composer bar; a round + at the bottom right, offered to
    whom may add something there, opens a panel at the top of the feed;
  - Blog: the + writes a post, sent as parts past one packet, and the feed
    shows it joined;
  - Forum: always on the left; it opens on the categories, one click to a
    category's topics and a way back; the administrator's + creates one.
"""
import os
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from cdp import Cdp  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BROWSER = os.environ.get('WEBCHAT_BROWSER', 'chromium')
PROF = os.path.expanduser('~/snap/chromium/common/webchat-feed-prof' if BROWSER == 'chromium'
                          else '~/.cache/webchat-feed-prof')
PORT = 8785
fails = 0


def check(ok, what, extra=None):
    global fails
    print(('  [PASS] ' if ok else '  [FAIL] ') + what + (('  -- ' + str(extra)) if (extra and not ok) else ''))
    fails += 0 if ok else 1


env = dict(os.environ)
env['MOCK_FORUM'] = '1'
station = subprocess.Popen([sys.executable, os.path.join(ROOT, 'contract', 'mock_station.py'),
                            str(PORT)], env=env)
time.sleep(1)
c = Cdp(BROWSER, PROF)
try:
    c.attach()
    c.load('http://127.0.0.1:%d/' % PORT)
    bar = "getComputedStyle(document.querySelector('.input-area')).display"
    fab = "getComputedStyle(document.getElementById('fab')).display"

    print('the banner and the logo')
    check(c.eval("getComputedStyle(document.getElementById('banner')).display") == 'none',
          'no banner until the station has one')
    c.eval("switchRoom('blog');showTab('traffic')")
    c.eval("document.querySelector('.header .logo').click()")
    check(c.eval("tab==='chat'&&curRoom==='local'"), 'the logo goes back to the chat')

    print('days in a conversation')
    c.eval("switchRoom('local')")
    now = int(time.time())
    c.eval("render({ts:%d,from:'X1OLDY',type:'message',sig:'verified',wire:'t:message f:X1OLDY ts:x scope:local m:three days ago'});"
           "render({ts:%d,from:'X1OLDY',type:'message',sig:'verified',wire:'t:message f:X1OLDY ts:y scope:local m:yesterday it was'});"
           "render({ts:%d,from:'X1OLDY',type:'message',sig:'verified',wire:'t:message f:X1OLDY ts:z scope:local m:and today'})" % (now - 3 * 86400, now - 86400, now))
    time.sleep(0.5)
    seps = c.eval("[].map.call(document.querySelectorAll('#msgs .daysep'),function(e){return e.textContent})") or []
    check('Yesterday' in seps and 'Today' in seps and len(seps) >= 3, 'a pill above each day: %s' % seps)
    order = c.eval("[].map.call(document.querySelectorAll('#msgs > *'),function(e){return e.className.indexOf('daysep')>=0?'|'+e.textContent:(e.innerText.indexOf('yesterday it was')>=0?'Y':e.innerText.indexOf('and today')>=0?'T':'')}).filter(function(x){return x}).join(' ')") or ''
    check('|Yesterday Y' in order and '|Today' in order and order.index('|Yesterday') < order.index('|Today'), 'each message under its own day: %s' % order)
    check(c.eval("/^\\d\\d:\\d\\d$/.test(document.querySelector('#msgs .msg .time').textContent)"), 'a bubble shows hours and minutes')

    print('the station\'s location')
    p = c.eval("JSON.stringify(snapPos(48.13721,11.57561,5))")
    check(p and '"r":5' in p and '48.13721' not in p, 'snapped to the centre of a 10 km square: %s' % p)
    check(c.eval("JSON.stringify(snapPos(48.13721,11.57561,0))") == '{"lat":48.13721,"lon":11.57561,"r":0}', 'exact is exact')
    check(c.eval("var a=snapPos(48.1301,11.5701,5),b=snapPos(48.1352,11.5748,5);a.lat===b.lat&&a.lon===b.lon"),
          'two places in one square give the same point')

    print('a narrow screen: the room drawer')
    c.send('Emulation.setDeviceMetricsOverride', {'width': 360, 'height': 740, 'deviceScaleFactor': 2, 'mobile': True})
    time.sleep(0.5)
    check(c.eval("getComputedStyle(document.getElementById('roombar')).display==='flex'&&document.getElementById('rb-name').textContent==='Local'"),
          'a bar names the room')
    check(c.eval("document.getElementById('side').getBoundingClientRect().right<=0"), 'the room list is off screen')
    c.eval("for(var i=0;i<40;i++){dmPeers['X1P'+(100+i)]=true;}dmUnread['X1P105']=2;renderSide()")
    c.eval("toggleSide()")
    time.sleep(0.4)
    check(c.eval("document.getElementById('side').classList.contains('open')&&document.getElementById('side').getBoundingClientRect().left===0"),
          'the bar opens it as a drawer')
    check(c.eval("document.querySelectorAll('#side .room').length>45&&document.getElementById('side').scrollHeight>document.getElementById('side').clientHeight"),
          'forty conversations scroll in it')
    check(c.eval("document.getElementById('rb-cnt').textContent") == '1', 'the bar counts who wrote and was not read')
    c.eval("document.querySelector('#side .room[data-r=\"dm:X1P105\"]').click()")
    time.sleep(0.4)
    check(c.eval("curRoom==='dm:X1P105'&&!document.getElementById('side').classList.contains('open')&&document.getElementById('rb-name').textContent==='X1P105'"),
          'a tap opens the conversation and closes the drawer')
    c.eval("switchRoom('local');for(var k in dmPeers)delete dmPeers[k];for(var k in dmUnread)delete dmUnread[k];renderSide()")
    c.send('Emulation.setDeviceMetricsOverride', {'width': 1100, 'height': 720, 'deviceScaleFactor': 1, 'mobile': False})
    time.sleep(0.5)

    print('the Blog feed')
    c.eval("switchRoom('blog')")
    check(c.eval(bar) == 'none', 'no composer bar on the Blog')
    check(c.wait("fabMode==='blog'&&" + fab + "!=='none'"), 'the + offers a post')
    check(c.wait("canSign()", 10), 'the page has a key before the first keystroke')
    check(c.eval("!!document.querySelector('#side .room[data-r=\"forum\"]')"), 'Forum is on the left, beside Blog')
    c.eval("fabClick()")
    check(c.wait("!!document.getElementById('bl-title')"), 'the + opens the post panel at the top of the feed')
    text = ' '.join(['The mast went up at nine and the first contact was a station two valleys over.'] * 6)
    c.eval("document.getElementById('bl-title').value='Field day';document.getElementById('bl-text').value=%r" % text)
    c.eval("blogPublish()")
    check(c.wait("!document.getElementById('composer')&&blogs.some(function(p){return p.title==='field-day';})", 15),
          'published: the feed shows the post, joined from its parts')
    check(c.eval("blogs.filter(function(p){return p.title==='field-day';})[0].text.length") == len(text),
          'the whole text came back')
    check(c.eval("document.querySelectorAll('#msgs .post').length") >= 2, 'the post is drawn with the mock\'s')

    print('Alerts and Forum, as a visitor')
    c.eval("switchRoom('alerts')")
    check(c.eval(bar) == 'none', 'no composer bar on Alerts')
    check(c.eval(fab) == 'none', 'no + for a visitor the station does not let post alerts')
    c.eval("switchRoom('forum')")
    check(c.wait("!!document.querySelector('#msgs .cat[data-r=\"f:X5F0RM\"]')"), 'Forum opens on its categories')
    check(c.eval(fab) == 'none', 'no + for a visitor')
    c.eval("document.querySelector('#msgs .cat[data-r=\"f:X5F0RM\"]').click()")
    check(c.wait("curRoom==='f:X5F0RM'&&document.getElementById('msgs').innerHTML.indexOf('Forum</button>')>=0"),
          'a category opens on its topics, with a way back')
    check(c.eval("document.querySelector('#side .room.on').getAttribute('data-r')") == 'forum', 'Forum stays lit')

    print('as the administrator')
    c.eval("openView('admin')")
    check(c.wait("!!document.getElementById('ad-claim')"), 'the station offers the claim')
    c.eval("document.getElementById('ad-claim').click()")
    check(c.wait("isStationAdmin===true", 10), 'claimed')
    check(c.wait("!!document.getElementById('ad-banner')", 5), 'Administration has the banner card')
    c.eval("document.getElementById('ad-banner').value='<b>Hill station</b> on air';adminSet({page_banner:document.getElementById('ad-banner').value})")
    check(c.wait("document.getElementById('bn-body').innerText.indexOf('Hill station')>=0", 5), 'the administrator writes the banner')
    c.eval("adminSet({page_css:':root{--accent:#6fc3ff}'});adminSet({page_logo:'<span>HILL</span>'})")
    check(c.wait("document.getElementById('logo').innerText==='HILL'&&getComputedStyle(document.querySelector('#side .room.on')).color==='rgb(111, 195, 255)'", 5),
          'and the logo and the stylesheet, which take effect at once')
    c.load('http://127.0.0.1:%d/' % PORT)
    check(c.wait("document.getElementById('bn-body').innerText.indexOf('Hill station')>=0&&document.getElementById('logo').innerText==='HILL'&&document.getElementById('st-css').textContent.indexOf('6fc3ff')>=0", 5),
          'and every visitor gets all three from the station')
    open_h = c.eval("document.getElementById('banner').offsetHeight")
    c.eval("bannerToggle()")
    check(c.eval("document.getElementById('banner').className") == 'min'
          and c.eval("document.getElementById('banner').offsetHeight") <= open_h, 'the arrow minimizes the banner')
    c.load('http://127.0.0.1:%d/' % PORT)
    check(c.wait("bannerDrawn.indexOf('Hill station')>=0&&document.getElementById('banner').className==='min'"),
          'minimized stays minimized after a reload')
    c.eval("document.getElementById('banner').click()")
    check(c.eval("document.getElementById('banner').className") == '', 'a click opens it again')
    c.eval("showTab('admin')")
    check(c.wait("document.querySelectorAll('#themes .theme').length===6", 5), 'the Look card offers six themes')
    c.eval("pickTheme(0)")
    check(c.eval("document.getElementById('ad-css').value.indexOf('--accent:#ffa86a')>0"), 'the default theme lists its whole palette to edit')
    c.eval("pickTheme(2)")
    check(c.eval("document.getElementById('ad-css').value===prettyCss(THEMES[2].css)&&document.getElementById('st-css').textContent===prettyCss(THEMES[2].css)&&document.querySelector('#themes .theme.on').textContent==='Cyberpunk'"),
          'picking one applies it and fills the stylesheet, the chip lit')
    time.sleep(1)
    c.load('http://127.0.0.1:%d/' % PORT)
    check(c.wait("document.getElementById('st-css').textContent===prettyCss(THEMES[2].css)", 5), 'saved by the pick alone: a visitor gets the theme')
    c.eval("showTab('admin')")
    check(c.wait("!!document.getElementById('ps-lat')", 5), 'Administration has the Location card')
    c.eval("document.getElementById('ps-lat').value='48.13721';document.getElementById('ps-lon').value='11.57561';document.getElementById('ps-r').value='5';posSave()")
    check(c.wait("getComputedStyle(document.getElementById('stpos')).display!=='none'&&document.getElementById('stpos').textContent.indexOf('5 km')>=0", 5),
          'saved: a pin beside the station\'s name, within 5 km')
    check(c.eval("document.getElementById('stpos').href.indexOf('openstreetmap.org')>0&&document.getElementById('stpos').href.indexOf('48.13721')<0"),
          'its link is the map at the square\'s centre, never the exact place')
    c.eval("adminSet({page_css:':root{--accent:#6fc3ff}'})")
    c.eval("showTab('chat')")
    c.send('Page.navigate', {'url': 'http://127.0.0.1:%d/' % PORT})
    check(c.wait("document.readyState!=='complete'&&!!document.getElementById('st-css')&&document.getElementById('st-css').textContent.indexOf('6fc3ff')>=0", 3)
          or c.eval("!!document.getElementById('st-css')&&document.getElementById('st-css').textContent.indexOf('6fc3ff')>=0"),
          'the last look is applied before the page has loaded, from this browser\'s memory')
    c.wait("document.readyState==='complete'&&!!document.getElementById('txt')", 10)
    time.sleep(1)
    check(c.eval("(document.getElementById('stpos')||{}).style&&document.getElementById('stpos').style.display!=='none'"), 'every visitor gets the pin from the station')
    c.eval("adminSet({page_logo:''});adminSet({page_css:''});adminSet({page_pos:''})")
    check(c.wait("document.getElementById('logo').innerText==='XPRS'", 5), 'emptied, the logo is XPRS again')
    c.eval("showTab('chat');switchRoom('forum')")
    check(c.wait("fabMode==='category'&&" + fab + "!=='none'"), 'the + offers a new category to the administrator')
    c.eval("fabClick()")
    check(c.wait("!!document.getElementById('fc-name')"), 'the category panel')
    c.eval("document.getElementById('fc-name').value='Antennas';document.getElementById('fc-about').value='Wire, masts, tuners';categoryCreate()")
    check(c.wait("curRoom.slice(0,2)==='f:'&&curRoom!=='f:X5F0RM'", 10), 'created and opened')
    check(c.wait("hostedByCall[curRoom.slice(2)]&&hostedByCall[curRoom.slice(2)].role==='mod'", 10),
          'the administrator moderates it without being asked')
    c.eval("switchRoom('forum')")
    check(c.wait("document.querySelectorAll('#msgs .cat').length===2"), 'two categories now')
    c.eval("switchRoom('alerts')")
    check(c.wait("fabMode==='alert'&&" + fab + "!=='none'"), 'the + offers an alert to the administrator')
    c.eval("fabClick()")
    check(c.wait("!!document.getElementById('al-text')"), 'the alert panel at the top of the feed')
    c.eval("document.getElementById('al-text').value='road closed at the bridge';postAlert()")
    check(c.wait("!document.getElementById('composer')&&document.getElementById('msgs').innerHTML.indexOf('road closed')>=0", 10),
          'posted: the feed shows it and the panel is gone')
finally:
    c.close()
    station.terminate()
sys.exit(1 if fails else 0)
