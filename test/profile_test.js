// The person's archivers, from the network (page/chat_page.html
// profileArchivers, holdersOf, profileAround; XPRS.md 9.12, 12.9.5): the
// declaration the archivers know is the account's list, this browser's copy
// only stands while its own fresh declaration may still be on its way, a
// list taken from the network is never re-declared, and a station that knows
// none is not believed before the other archivers in reach were asked.
//   node test/profile_test.js
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

let fails = 0;
function check(ok, what) { console.log((ok ? '  [PASS] ' : '  [FAIL] ') + what); if (!ok) fails++; }

// entry: this browser's account record; around: what other archivers answer.
function run(j, entry, around) {
  const env = { entry: Object.assign({ call: 'X1ME' }, entry || {}), sets: [] };
  const R = around === undefined ? null : {
    archivers: () => Object.keys(around).map(c => ({ call: c })),
  };
  const f = new Function('env', 'R',
    'var mycall="X1ME",stationCall="X3BASE",tab="chat",sessHolders=null,PROFILE_FRESH_MS=600000,PROFILE_ASK=6;' +
    'function baseCall(c){return String(c).split("-")[0];}' +
    'function accEntry(){return env.entry;}function accHold(){return env.entry.hold||[];}' +
    'function accSet(f){env.sets.push(f);for(var k in f)env.entry[k]=f[k];}' +
    'function loadAccounts(){}function remote(){return R;}' +
    'function remoteSession(c){return Promise.resolve(R.__answers[c]);}' +
    pick('sameList') + pick('holdersOf') + pick('profileAround') + pick('profileArchivers') +
    'return function(j){return new Promise(function(ok){profileArchivers(j,function(m,a){ok({mine:m,adopted:!!a});});});};');
  if (R) R.__answers = around;
  return f(env, R)(j).then(r => Object.assign(r, { env }));
}

(async () => {
  let r = await run({ holders: ['X3A', 'X3B-1'] }, {});
  check(r.mine.join() === 'X3A,X3B' && r.adopted, 'a new browser takes the list the station knows, SSIDs dropped');
  check(r.env.entry.hold.join() === 'X3A,X3B' && r.env.entry.chosen === 1, 'kept as the account\'s, and the person\'s choice');

  r = await run({ holders: ['X3A'] }, { hold: ['X3A'], said: 'X3A', saidAt: Date.now() - 86400000 });
  check(r.mine.join() === 'X3A' && !r.adopted && !r.env.sets.length, 'the same list: this page\'s own, nothing changed');

  r = await run({ holders: ['X3OLD'] }, { hold: ['X3NEW'], said: 'X3NEW', saidAt: Date.now() - 60000 });
  check(r.mine.join() === 'X3NEW' && !r.adopted, 'declared here a minute ago: the station may not have it yet');

  r = await run({ holders: ['X3OTHER'] }, { hold: ['X3MINE'], said: 'X3MINE', saidAt: Date.now() - 3 * 86400000 });
  check(r.mine.join() === 'X3OTHER' && r.adopted, 'changed on another device since: the network\'s list wins');

  r = await run({ holders: [], offer: 'X3BASE' }, {}, { X3P: { offer: 'X3P', holders: [] }, X3Q: { holders: ['X3Q', 'X3R'] } });
  check(r.mine.join() === 'X3Q,X3R' && r.adopted, 'the station knows none: another archiver in reach does');

  r = await run({ holders: [], offer: 'X3BASE' }, {}, { X3P: { offer: 'X3P', holders: [] }, X3Q: null });
  check(r.mine.length === 0 && !r.adopted, 'nobody knows any: the station\'s offer stands (empty here, the caller adds it)');

  r = await run({ holders: [], offer: 'X3BASE' }, {});
  check(r.mine.length === 0 && !r.adopted, 'a station\'s own page: only what it knows');

  r = await run({ holders: [] }, { hold: ['X3MINE'] }, {});
  check(r.mine.join() === 'X3MINE' && !r.adopted, 'a station that knows none does not empty this browser\'s list');

  if (fails) { console.log(fails + ' failed'); process.exit(1); }
  console.log('all passed');
})();
