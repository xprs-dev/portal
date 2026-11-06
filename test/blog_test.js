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
process.exit(fails ? 1 : 0);
