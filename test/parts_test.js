// A split chat message (page/chat_page.html joinPart): the n:k/N parts of one
// (f, ts) become one bubble once all are in, joined with one space (XPRS.md
// 6.6), the head of part 1 (file:) kept and n: dropped; a hole is not shown.
//   node test/parts_test.js
const fs = require('fs');
const path = require('path');
const page = fs.readFileSync(path.join(__dirname, '..', 'page', 'chat_page.html'), 'utf8');
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
const api = new Function('var partSets={};' + pick('baseCall') + pick('headField') +
  pick('joinPart') + 'return {joinPart};')();

let fails = 0;
function check(ok, what) { console.log((ok ? '  [PASS] ' : '  [FAIL] ') + what); if (!ok) fails++; }

const head = 't:message f:X106QR d:X58QRA ts:2026-11-23_20:11:17 file:abc.jpg size:8690';
const part = (k, of, m, sig) => ({from: 'X106QR', ts: 1, sig: sig || 'unsigned',
  wire: head + ' n:' + k + '/' + of + (k === of ? ' sig:S' : '') + ' m:' + m});

check(api.joinPart({from: 'A', wire: 't:message f:A m:hi'}).wire === 't:message f:A m:hi',
  'a whole message passes through');
check(api.joinPart(part(3, 3, 'c', 'verified')) === null, 'the last part alone is not shown');
check(api.joinPart(part(1, 3, 'a\u2028b')) === null, 'nor two of three');
const whole = api.joinPart(part(2, 3, 'x'));
check(whole && whole.wire === head + ' m:a\u2028b x c', 'all in: one message, parts joined in order');
check(whole && whole.sig === 'verified', "the whole carries the last part's signature state");
check(api.joinPart(part(1, 3, 'a\u2028b')) === whole, 'a repeated part gives the same message');
check(api.joinPart({from: 'A', wire: 't:message f:A n:9/2 m:x'}) === null, 'a part beyond its count is dropped');

if (fails) { console.log(fails + ' failed'); process.exit(1); }
console.log('all passed');
