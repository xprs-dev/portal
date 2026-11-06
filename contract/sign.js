#!/usr/bin/env node
// Sign XPRS packets with the page's own crypto, for the conformance suite.
//
//   node contract/sign.js <priv-hex> <canonical packet>   -> the signed wire
//   node contract/sign.js --pub <priv-hex>                 -> x-only pubkey hex
//   node contract/sign.js --npub <priv-hex>                -> the npub
//   node contract/sign.js --id <wire>                      -> section 5 identifier
//
// The same xprsSign the page uses (page/xprs_crypto.js), so what the suite
// sends is exactly what a browser sends.
const fs = require('fs');
const path = require('path');
const src = fs.readFileSync(path.join(__dirname, '..', 'page', 'xprs_crypto.js'), 'utf8')
  .split('// ---- node test against the spec 9.1.2 worked example ----')[0];
const nodeCrypto = require('crypto');
const api = new Function('window', src + `
  return {xprsSign, u8, sha256, s2b, cat, n2b, b2n, hex, b85enc, pubkeyX, npubEncode};`)({});

const args = process.argv.slice(2);
function priv(h) { return BigInt('0x' + h); }
if (args[0] === '--pub') {
  process.stdout.write(api.hex(api.pubkeyX(api.n2b(priv(args[1]), 32))));
} else if (args[0] === '--npub') {
  process.stdout.write(api.npubEncode(api.pubkeyX(api.n2b(priv(args[1]), 32))));
} else if (args[0] === '--id') {
  const canon = args[1].replace(/ sig:[!-~]{60}/, '').replace(/ via:[A-Za-z0-9,\-]+/, '');
  process.stdout.write(api.hex(api.sha256(api.s2b(canon))).slice(0, 6));
} else {
  const canonical = args[1];
  const aux = new Uint8Array(nodeCrypto.randomBytes(32));
  const sig = ' sig:' + api.b85enc(api.xprsSign(canonical, priv(args[0]), aux));
  const i = canonical.indexOf(' m:');
  process.stdout.write(i >= 0 ? canonical.slice(0, i) + sig + canonical.slice(i) : canonical + sig);
}
