// page/xprs_md.js against the shared formatted-text vectors (XPRS.md 4.11),
// which core's lib/src/util/xprs_md.dart (the server's and the app's reader)
// answers the same way. The vectors live in core: ../core/test/xprs_md_vectors.json
// (or XPRS_MD_VECTORS=path).
//   node test/md_vectors_test.js
const fs = require('fs');
const path = require('path');
const file = process.env.XPRS_MD_VECTORS ||
  path.join(__dirname, '..', '..', 'core', 'test', 'xprs_md_vectors.json');
if (!fs.existsSync(file)) {
  console.log('  [SKIP] no ' + file + ' (check out xprs-dev/core beside portal)');
  process.exit(0);
}
const src = fs.readFileSync(path.join(__dirname, '..', 'page', 'xprs_md.js'), 'utf8');
const md = new Function(src + ';return {mdRender};')();
const esc = (s, q) => { let r = s.replace(/&/g, '&amp;'); if (q) r = r.replace(/"/g, '&quot;'); return r.replace(/</g, '&lt;'); };
const opts = {
  img: (r, a) => '<img src="' + r + '" alt="' + esc(a, true) + '">',
  file: (r, l) => '<a data-ref="' + r + '">' + esc(l) + '</a>',
  mention: c => '<span class="at">@' + c + '</span>',
};
let fails = 0;
for (const v of JSON.parse(fs.readFileSync(file, 'utf8')).vectors) {
  const html = md.mdRender(v.input, opts), plain = md.mdRender(v.input, {});
  const ok = html === v.html && plain === v.plain;
  console.log((ok ? '  [PASS] ' : '  [FAIL] ') + v.name);
  if (!ok) { fails++; console.log('    want ' + v.html + '\n    got  ' + html); }
}
process.exit(fails ? 1 : 0);
