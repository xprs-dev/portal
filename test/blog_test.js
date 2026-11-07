// The Blog feed's fold (page/chat_page.html blogPosts): t:blog rows become
// posts, parts joined in order (XPRS.md 6.6), a set with a hole never shown,
// the newest edition per author and title shown as edited (18.1).
//   node test/blog_test.js
const fs = require('fs');
const path = require('path');
const dir = path.join(__dirname, '..', 'page');
const crypto = fs.readFileSync(path.join(dir, 'xprs_crypto.js'), 'utf8')
  .split('// ---- node test against the spec 9.1.2 worked example ----')[0];
const page = fs.readFileSync(path.join(dir, 'chat_page.html'), 'utf8');
const pick = name => {
  const i = page.indexOf('function ' + name + '(');
  if (i < 0) throw new Error('no ' + name + ' in the page');
  let depth = 0, j = page.indexOf('{', i);
  for (; j < page.length; j++) {
    if (page[j] === '{') depth++;
    else if (page[j] === '}' && --depth === 0) break;
  }
  return page.slice(i, j + 1);
};
const api = new Function('window', crypto + pick('wireId') + pick('baseCall') +
  pick('headField') + pick('blogPosts') + 'return {blogPosts};')({});

let fails = 0;
function check(ok, what) { console.log((ok ? '  [PASS] ' : '  [FAIL] ') + what); if (!ok) fails++; }

let n = 0;
const row = (ts, wire, from) => ({id: 'id' + (++n), ts, from: from || wire.split(' f:')[1].split(' ')[0],
  to: '', type: 'blog', sig: 'verified', own: false, wire});

const rows = [
  // the spec's three-part post, parts arriving out of order
  row(1754663200, 't:blog f:X1QZ3N ts:2026-08-08_14:26:40 title:antenna-notes n:2/3 m:The feed point was off centre.'),
  row(1754663200, 't:blog f:X1QZ3N ts:2026-08-08_14:26:40 title:antenna-notes n:3/3 m:About a decibel.'),
  row(1754663200, 't:blog f:X1QZ3N ts:2026-08-08_14:26:40 title:antenna-notes tag:radio n:1/3 m:I rebuilt the dipole.'),
  // a set with a hole: never shown
  row(1754663300, 't:blog f:X1QZ3N ts:2026-08-08_14:28:20 title:lost-middle n:1/2 m:first half'),
  // an older and a newer edition of one title, and somebody else's same title
  row(1754600000, 't:blog f:X1RD89 ts:2026-08-07_20:53:20 title:log m:the first version'),
  row(1754700000, 't:blog f:X1RD89 ts:2026-08-08_23:40:00 title:log m:the corrected version'),
  row(1754650000, 't:blog f:X1BOA3 ts:2026-08-08_10:46:40 title:log m:somebody else, same slug'),
  // untitled, and a withdrawal that is not a post
  row(1754660000, 't:blog f:X1BOA3 ts:2026-08-08_13:33:20 m:untitled thought'),
  row(1754661000, 't:blog f:X1BOA3 ts:2026-08-08_13:50:00 r:1a2b3c remove:blog'),
];
const posts = api.blogPosts(rows);
const by = t => posts.filter(p => p.title === t);
check(posts.length === 4, 'nine rows are four posts (' + posts.length + ')');
check(by('antenna-notes').length === 1 &&
      by('antenna-notes')[0].text === 'I rebuilt the dipole. The feed point was off centre. About a decibel.',
      'three parts join in order with one space, whatever order they arrived in');
check(by('antenna-notes')[0].tags === 'radio', 'the head part gives the tags');
check(by('lost-middle').length === 0, 'a set with a part missing is not shown');
const logs = by('log');
check(logs.length === 2, 'the same slug from two authors is two posts');
const rd = logs.find(p => p.from === 'X1RD89');
check(rd && rd.text === 'the corrected version' && rd.edited, 'the newest edition replaces the older and reads as edited');
check(logs.find(p => p.from === 'X1BOA3').edited === false, 'an only edition is not marked edited');
check(posts.filter(p => !p.title).length === 1 && posts.find(p => !p.title).text === 'untitled thought',
      'an untitled post is kept, a withdrawal is not a post');
check(posts.every((p, i) => i === 0 || posts[i - 1].ts >= p.ts), 'newest first');

// ---- formatted text (XPRS.md 4.11): page/xprs_md.js ----
const md = new Function('window', crypto + fs.readFileSync(path.join(dir, 'xprs_seal.js'), 'utf8') +
  fs.readFileSync(path.join(dir, 'xprs_md.js'), 'utf8') + pick('splitParts') +
  'return {mdRender, mdToWire, mdFromWire, mdRefs, refOf, isRef, splitParts, u8};')({});
const REF = 'nYxKzGm4vT2pQ8dW5jR7cL0aFbNs9hUe3oXiC6EkM1w.jpg';
const opts = {img: (r, a) => '<IMG ' + r + ' ' + a + '>', file: (r, l) => '<FILE ' + r + ' ' + l + '>',
              mention: c => '<CALL ' + c + '>'};
const R = t => md.mdRender(md.mdToWire(t), opts);
const wire = md.mdToWire('Line one  \n line two\n\n\nNext para\tend');
check(wire === 'Line one line two Next para end', 'newlines travel as U+2028 / U+2029, other controls a space');
check(!/[\n\r]/.test(wire), 'nothing in m: breaks the one-packet-per-line framing');
check(md.mdFromWire(wire) === 'Line one\nline two\n\nNext para end', 'and come back as newlines to edit');
check(R('a\nb\n\nc') === '<p>a<br>b</p><p>c</p>', 'a line break and a paragraph');
check(R('# Big\n## Mid') === '<h3>Big</h3><h4>Mid</h4>', 'headings');
check(R('**b** *i* _i_ ~~s~~ `c<d>`') === '<p><strong>b</strong> <em>i</em> <em>i</em> <del>s</del> <code>c&lt;d&gt;</code></p>', 'emphasis and code');
check(R('snake_case_name 2*3*4') === '<p>snake_case_name 2*3*4</p>', 'no emphasis inside a word');
check(R('- one\n- two\n\n1. a\n2. b') === '<ul><li>one</li><li>two</li></ul><ol><li>a</li><li>b</li></ol>', 'lists');
check(R('> said\n> more') === '<blockquote>said<br>more</blockquote>', 'a quote');
check(R('<script>alert(1)</script>') === '<p>&lt;script&gt;alert(1)&lt;/script&gt;</p>', 'HTML is text');
check(R('[x](javascript:alert(1))').indexOf('href') < 0, 'a javascript: link is not a link');
check(R('[x](https://a.b/?q="><img src=x onerror=1>)').indexOf('<img') < 0, 'a quote in a link cannot open an attribute');
check(R('[*x*](https://e.org/a?b=1&c=2)') ===
      '<p><a href="https://e.org/a?b=1&amp;c=2" target="_blank" rel="noopener nofollow"><em>x</em></a></p>', 'a link');
check(R('see https://e.org/x.') === '<p>see <a href="https://e.org/x" target="_blank" rel="noopener nofollow">https://e.org/x</a>.</p>', 'a bare address is a link, the full stop is not');
check(R('![the "mast"](' + REF + ')') === '<p><IMG ' + REF + ' the "mast"></p>', 'an image by its reference');
check(R('![x](file:' + REF + ')') === '<p>![x](file:' + REF + ')</p>', 'file: inside the text is not a reference (4.11)');
check(R('[log](' + REF.replace('.jpg', '.pdf') + ')') === '<p><FILE ' + REF.replace('.jpg', '.pdf') + ' log></p>', 'a file by its reference');
check(R('hi @X1QZ3N, me@example.com') === '<p>hi <CALL X1QZ3N>, me@example.com</p>', 'a mention, an address is not one');
check(md.mdRefs('![a](' + REF + ') [b](' + REF + ')').length === 1, 'the references, once each');
check(md.isRef(md.refOf(new Uint8Array([1, 2, 3]), 'PNG')) && md.refOf(new Uint8Array([1, 2, 3]), 'png') ===
      'A5BYxvLAy0ksUzsKTRTvd8wPeKvMztUofYShogEc-4E.png', 'a reference is the base64url SHA-256 and the type');
// The splitter cuts at spaces only and the join puts one back: the separators survive.
const long = md.mdToWire(Array.from({length: 25}, (_, i) => 'Line number ' + i + ' of the post').join('\n'));
const sp = md.splitParts('t:blog f:X1QZ3N ts:2026-08-08_14:26:40 title:long', long);
check(sp.parts && sp.parts.length > 1 && sp.parts.join(' ') === long, 'a split post rejoins to the same text, separators and all');
check(md.splitParts('t:blog f:X1QZ3N ts:2026-08-08_14:26:40 title:long', long + (' word').repeat(400)).why,
      'past nine packets it says why');
process.exit(fails ? 1 : 0);
