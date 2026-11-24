// Using a NOSTR signer (NIP-07, `window.nostr`: nos2x, Alby and the like) for
// the account behind a callsign. The extension never gives the page its key and
// signs only NOSTR events, so a packet is signed in the second form of XPRS.md
// 6.1.3: the extension signs a kind 24767 event whose content is the packet
// digest, and the 64-byte BIP-340 signature goes in `sig:` as 80 characters.
// Sealed bodies use its nip04, the same cipher as `x:` in another wrapping
// (6.2). Builds on xprs_crypto.js and xprs_seal.js, which come before it.

function nostrAvailable(){return !!(window.nostr&&window.nostr.getPublicKey);}

/* One request at a time to the extension, [fn](done) each. nos2x shows a popup
 * per request and queues the rest; a popup closing can deny the next one
 * before it is seen, and the login (identity, then session) asks twice at
 * once. A request that took long had a person answer a popup: the next waits
 * a moment, until that window is gone. */
var nostrBusy=false,nostrWaiting=[];
function nostrQueue(fn){
  nostrWaiting.push(fn);
  if(!nostrBusy)nostrNext(0);}
function nostrNext(gap){
  var fn=nostrWaiting.shift();
  if(!fn){nostrBusy=false;return;}
  nostrBusy=true;
  setTimeout(function(){
    var t0=Date.now(),over=false;
    var done=function(){if(over)return;over=true;nostrNext(Date.now()-t0>400?700:0);};
    try{fn(done);}catch(e){done();}
  },gap);}

/* "YYYY-MM-DD_hh:mm:ss" (UTC) -> epoch seconds, or 0. */
function tsEpoch(ts){
  var m=/^(\d{4})-(\d\d)-(\d\d)_(\d\d):(\d\d):(\d\d)$/.exec(ts||'');
  return m?Math.floor(Date.UTC(+m[1],+m[2]-1,+m[3],+m[4],+m[5],+m[6])/1000):0;}

/* The event the extension is asked to sign for [canonical] (the packet without
 * sig: and via:), and the id the verifier will compute for it. */
function nostrEventFor(pubHex,canonical){
  var m=canonical.match(/ ts:(\S+)/),created=tsEpoch(m&&m[1]);
  if(!created)return null;
  var content=hex(sha256(u8(canonical)));
  var ser='[0,"'+pubHex+'",'+created+',24767,[],"'+content+'"]';
  return {event:{kind:24767,created_at:created,tags:[],content:content},
          id:hex(sha256(u8(ser)))};}

/* Sign [canonical] through the extension: cb(wire) with sig: placed before m:
 * as the other form does, or cb(null,why). */
function nostrSignWire(canonical,pubHex,cb){
  var ev=nostrEventFor(pubHex,canonical);
  if(!ev){cb(null,'this packet has no time to sign');return;}
  var done=function(signed){
    /* Trust the signature only for the event we asked for: an extension that
     * changed the time or the content signed something else. */
    if(!signed||typeof signed.sig!=='string'||signed.sig.length!==128||
       (signed.id&&signed.id!==ev.id)||
       (signed.pubkey&&signed.pubkey!==pubHex)){cb(null,'the signer returned something else');return;}
    var sig=b85enc(unhexBytes(signed.sig));
    var i=canonical.indexOf(' m:');
    cb(i>=0?canonical.slice(0,i)+' sig:'+sig+canonical.slice(i):canonical+' sig:'+sig);};
  nostrQueue(function(next){
    var no=function(e){next();cb(null,(e&&e.message)||'the signer refused');};
    try{
      var r=window.nostr.signEvent(ev.event);
      if(r&&r.then)r.then(function(v){next();done(v);},no);
      else{next();done(r);}
    }catch(e){no(e);}
  });
}
function unhexBytes(h){var b=new Uint8Array(h.length/2);
  for(var i=0;i<b.length;i++)b[i]=parseInt(h.substr(2*i,2),16);return b;}

/* NIP-04's content is base64(ciphertext)?iv=base64(iv); `x:` is base64url, no
 * padding, of the vector followed by the ciphertext (6.2). Same bytes. */
var B64S='ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/';
function b64sEnc(b){var s='',i,n;
  for(i=0;i<b.length;i+=3){
    n=(b[i]<<16)|((i+1<b.length?b[i+1]:0)<<8)|(i+2<b.length?b[i+2]:0);
    s+=B64S[n>>18&63]+B64S[n>>12&63]+(i+1<b.length?B64S[n>>6&63]:'=')+(i+2<b.length?B64S[n&63]:'=');}
  return s;}
function b64sDec(s){var out=[],acc=0,bits=0,i,v;
  s=s.replace(/=+$/,'');
  for(i=0;i<s.length;i++){v=B64S.indexOf(s[i]);if(v<0)return null;
    acc=(acc<<6)|v;bits+=6;if(bits>=8){bits-=8;out.push((acc>>bits)&255);}}
  return new Uint8Array(out);}
function nip04ToX(content){
  var p=String(content).split('?iv='),ct=p[0]&&b64sDec(p[0]),iv=p[1]&&b64sDec(p[1]);
  return ct&&iv&&iv.length===16?b64uEnc(cat(iv,ct)):null;}
function xToNip04(x){
  var b=b64uDec(x);
  return b&&b.length>=32?b64sEnc(b.slice(16))+'?iv='+b64sEnc(b.slice(0,16)):null;}

/* Seal [text] to [peerHex] with the extension: cb(x) or cb(null). */
function nostrSeal(peerHex,text,cb){
  var n=window.nostr&&window.nostr.nip04;
  if(!n||!n.encrypt){cb(null);return;}
  nostrQueue(function(next){
    try{
      var r=n.encrypt(peerHex,text),f=function(c){next();cb(nip04ToX(c));};
      if(r&&r.then)r.then(f,function(){next();cb(null);});else f(r);
    }catch(e){next();cb(null);}
  });}
/* Open an `x:` value from [peerHex] with the extension: cb(text) or cb(null). */
function nostrOpen(peerHex,x,cb){
  var n=window.nostr&&window.nostr.nip04,c=xToNip04(x);
  if(!n||!n.decrypt||!c){cb(null);return;}
  nostrQueue(function(next){
    try{
      var r=n.decrypt(peerHex,c),f=function(t){next();cb(typeof t==='string'?t:null);};
      if(r&&r.then)r.then(f,function(){next();cb(null);});else f(r);
    }catch(e){next();cb(null);}
  });}
