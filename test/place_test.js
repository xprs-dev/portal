// Where the station is (page/chat_page.html posBarred, mapPos): the page
// writes the square a station airs exactly as the core's xprsPosAuthored
// (core/test/xprs_shared_position_test.dart, the same inputs), and reads it
// back to the middle of that square, as the map at xprs.dev/in/ does.
//   node test/place_test.js
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
const api = new Function(pick('posBarred') + pick('rangeText') + pick('mapPos') +
  'return {posBarred, rangeText, mapPos};')();

let fails = 0;
function check(ok, what) { console.log((ok ? '  [PASS] ' : '  [FAIL] ') + what); if (!ok) fails++; }
const B = '█';

// The core's worked values (xprs_shared_position_test.dart).
check(api.posBarred(38.70771234, -9.13654321, 100000) === '38' + B.repeat(5) + ',-9' + B.repeat(5),
  '100 km: whole degrees readable, the rest barred');
check(api.posBarred(38.7077, -9.1365, 10000) === '38.7' + B.repeat(3) + ',-9.1' + B.repeat(3), '10 km');
check(api.posBarred(38.7077, -9.1365, 1000) === '38.70' + B.repeat(2) + ',-9.13' + B.repeat(2), '1 km');
check(api.posBarred(38.7077, -9.1365, 100) === '38.707' + B + ',-9.136' + B, '100 m');
check(api.posBarred(38.7077, -9.1365, 10) === '38.7077,-9.1365', '10 m: nothing left to hide');
// X3PTZM, the live server.
const x = api.posBarred(49.6317, 8.6683, 100000);
check(x === '49' + B.repeat(5) + ',8' + B.repeat(5), 'the live server at 100 km: ' + x);
const c = api.mapPos(x);
check(c && c.lat === 49.5 && c.lon === 8.5 && c.range === '100 km', 'read back: the middle of its square, named as the app names it');
check(api.rangeText(100000) === '100 km' && api.rangeText(100) === '100 m', 'ranges as the app names them');

if (fails) { console.log(fails + ' failed'); process.exit(1); }
console.log('all passed');
