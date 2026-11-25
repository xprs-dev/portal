// Another archiver as the page's base (page/chat_page.html mapUse, useBtn,
// baseSwitch, mapViewKept; in/shell.js XPRS_REMOTE.use): offered only where
// the page can reach other stations and only for archivers, never for the
// one in use; a switch keeps the map's view for the page opened on it, and
// one that does not answer changes nothing.
//   node test/base_switch_test.js
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

function world(R) {
  const store = {}, said = [];
  const env = {
    window: { XPRS_REMOTE: R },
    sessionStorage: {
      getItem: k => (k in store ? store[k] : null),
      setItem: (k, v) => { store[k] = String(v); },
      removeItem: k => { delete store[k]; },
    },
    snack: t => said.push(t),
    esc: t => String(t),
    baseCall: c => String(c).split('-')[0],
    mapObj: { getCenter: () => ({ lat: 12.5, lng: -70.25 }), getZoom: () => 7 },
  };
  const f = new Function('window', 'sessionStorage', 'snack', 'esc', 'baseCall', 'mapObj',
    'var stationCall="X1AAA-1",MAP_VIEW="xprs.in.view";' +
    pick('remote') + pick('canSwitch') + pick('useBtn') + pick('mapUse') + pick('baseSwitch') + pick('mapViewKept') +
    'return {mapUse, useBtn, baseSwitch, mapViewKept};');
  return { api: f(env.window, env.sessionStorage, env.snack, env.esc, env.baseCall, env.mapObj), store, said };
}
const archiver = c => ({ call: c, serve: ['archive', 'relay'] });
const tick = () => new Promise(r => setTimeout(r, 0));

(async () => {
  // A station's own page: no other station in reach, nothing offered.
  let w = world(undefined);
  check(w.api.mapUse(archiver('X1BBB')) === '' && w.api.useBtn('X1BBB') === '', 'a station\'s own page offers no switch');
  // xprs.dev before the shell could switch (an older shell): nothing either.
  w = world({ ask() {} });
  check(w.api.mapUse(archiver('X1BBB')) === '', 'a shell without use() offers no switch');

  // xprs.dev.
  let asked = null, went = 0;
  w = world({ ask() {}, use(c) { asked = c; return Promise.resolve(() => { went++; }); } });
  check(/Use this archiver/.test(w.api.mapUse(archiver('X1BBB'))), 'an archiver offers "Use this archiver"');
  check(w.api.mapUse({ call: 'X1CCC', serve: ['relay'] }) === '', 'a station that keeps nothing does not');
  check(/Browsing from here/.test(w.api.mapUse(archiver('X1AAA'))), 'the one in use says so, whatever its SSID');
  check(w.api.useBtn('X1AAA') === '' && /baseSwitch\('X1BBB'\)/.test(w.api.useBtn('X1BBB')), 'the archivers list: Use on the others only');

  w.api.baseSwitch('X1BBB');
  await tick();
  check(asked === 'X1BBB' && went === 1, 'the shell is asked, then the portal opened on it');
  const v = w.api.mapViewKept();
  check(v && v.lat === 12.5 && v.lon === -70.25 && v.z === 7, 'the map\'s view is kept for the page opened next');
  check(w.api.mapViewKept() === null, 'and used once');

  // One that does not answer: nothing kept, nothing opened, said why.
  went = 0;
  w = world({ ask() {}, use() { return Promise.reject(new Error('no link')); } });
  w.api.baseSwitch('X1DDD');
  await tick(); await tick();
  check(went === 0 && w.api.mapViewKept() === null, 'an archiver that does not answer changes nothing');
  check(/X1DDD cannot be reached from here right now; still on X1AAA-1/.test(w.said.join('|')), 'and the visitor is told: ' + w.said.slice(-1));

  if (fails) { console.log(fails + ' failed'); process.exit(1); }
  console.log('all passed');
})();
