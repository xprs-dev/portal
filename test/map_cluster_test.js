// The map's markers (page/chat_page.html mapCluster, mapKind): stations near
// each other ON THE SCREEN are one bubble, so the same stations merge when
// the map is far out and come apart when it is close; and what a station is,
// for the filter over the map, whatever machine it runs on.
//   node test/map_cluster_test.js
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
const api = new Function(pick('mapCluster') + pick('mapKind') + 'return {mapCluster, mapKind};')();

let fails = 0;
function check(ok, what) { console.log((ok ? '  [PASS] ' : '  [FAIL] ') + what); if (!ok) fails++; }

// Web Mercator in pixels, as Leaflet's project() at zoom z.
const project = z => ll => {
  const s = 256 * Math.pow(2, z), lat = ll[0] * Math.PI / 180;
  return { x: (ll[1] + 180) / 360 * s, y: (1 - Math.log(Math.tan(lat) + 1 / Math.cos(lat)) / Math.PI) / 2 * s };
};
// The screenshot's stations: two squares near Mannheim, one near Darmstadt,
// the archiver near Weinheim.
const pts = [
  { call: 'X1AAA', ll: [49.5, 8.5] }, { call: 'X1BBB', ll: [49.5, 8.5] },
  { call: 'X1CCC', ll: [49.75, 8.65] },
  { call: 'X1DDD', ll: [48.78, 9.18] },               // Stuttgart, further off
];
const sizes = cs => cs.map(c => c.pts.length).sort((a, b) => b - a).join(',');

let cs = api.mapCluster(pts, project(6), 44);
check(sizes(cs) === '3,1', 'zoomed out (6): the two squares near each other are one bubble of 3: ' + sizes(cs));
cs = api.mapCluster(pts, project(4), 44);
check(sizes(cs) === '4', 'further out (4): everything one bubble of 4: ' + sizes(cs));
cs = api.mapCluster(pts, project(10), 44);
check(sizes(cs) === '2,1,1', 'close (10): apart, and one square\'s two stay one bubble: ' + sizes(cs));
cs = api.mapCluster(pts, project(18), 44);
check(cs.find(c => c.pts.length === 2), 'stations in the very same square never come apart (listed instead)');
check(api.mapCluster([], project(5), 44).length === 0, 'nothing placed: no bubble');

// A thousand stations in one area: one pass, a handful of bubbles.
const many = [];
for (let i = 0; i < 1000; i++) many.push({ call: 'X1' + i, ll: [49 + (i % 40) * 0.01, 8 + Math.floor(i / 40) * 0.01] });
const t0 = Date.now();
cs = api.mapCluster(many, project(8), 44);
check(cs.length < 10 && cs.reduce((n, c) => n + c.pts.length, 0) === 1000,
  'a thousand stations: ' + cs.length + ' bubbles, none lost, ' + (Date.now() - t0) + ' ms');

check(api.mapKind({ call: 'X3PTZM', serve: ['archive'] }) === 'archive', 'a server that archives: an archiver');
check(api.mapKind({ call: 'X1ABC', serve: ['archive', 'files'] }) === 'archive', 'any callsign announcing serve:archive is an archiver');
check(api.mapKind({ call: 'X1ABC', serve: [] }) === 'people', 'a person');
check(api.mapKind({ call: 'X3BRD', serve: ['relay'] }) === 'other', 'a board that relays: another station');

if (fails) { console.log(fails + ' failed'); process.exit(1); }
console.log('all passed');
