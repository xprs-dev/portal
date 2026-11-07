// ---- formatted text (XPRS.md 4.11): a small markdown, read safely --------
// A t:blog's m: is markdown: paragraphs, headings, emphasis, lists, quotes,
// links and images. The wire carries no newline (one packet per line, parts
// joined by a space), so a line break travels as U+2028 and a paragraph break
// as U+2029. An image or a file is named by its content reference (7.7 `ref`:
// the SHA-256 as 43 base64url characters, a dot, the type) with no `file:`
// before it, so a slow link carries only the words and whoever can fetches
// the bytes by hash. Everything is escaped first; nothing typed becomes HTML.
var MD_LS='\u2028',MD_PS='\u2029';
var MD_IMG={jpg:1,jpeg:1,png:1,gif:1,webp:1,avif:1,bmp:1};
/* A content reference: base64url (what a sender writes) or 64 hex, a dot,
 * 1 to 8 lowercase letters or digits (7.7). */
function isRef(s){return /^(?:[A-Za-z0-9_-]{43}|[0-9a-f]{64})\.[a-z0-9]{1,8}$/.test(s||'');}
function refExt(r){return (r||'').split('.').pop();}
function isImageRef(r){return isRef(r)&&!!MD_IMG[refExt(r)];}
/* The reference a file gets: sha256 of its bytes as base64url, no padding. */
function refOf(bytes,ext){
  return b64uEnc(sha256(bytes))+'.'+String(ext||'bin').toLowerCase().replace(/[^a-z0-9]/g,'').slice(0,8);}
/* Composer text -> what m: carries: newlines become the separators, spaces
 * around them go (the splitter cuts only at a plain space and the join puts
 * one back, so a space beside a separator would be noise), other control
 * characters become a space. */
function mdToWire(t){
  return String(t||'').replace(/\r\n?/g,'\n').replace(/[ \t]*\n[ \t]*/g,'\n').trim()
    .replace(/\n{2,}/g,MD_PS).replace(/\n/g,MD_LS)
    .replace(/[\x00-\x1f\x7f]+/g,' ');}
/* And back, for editing a post again. */
function mdFromWire(t){return String(t||'').replace(/ ?\u2029 ?/g,'\n\n').replace(/ ?\u2028 ?/g,'\n');}
function mdEsc(t){return String(t==null?'':t).replace(/&/g,'&amp;').replace(/</g,'&lt;')
  .replace(/>/g,'&gt;').replace(/"/g,'&quot;').replace(/'/g,'&#39;');}
/* Every reference the text names, images and files, in order, once each. */
function mdRefs(text){
  var out=[],seen={},re=/\]\(([A-Za-z0-9_-]{43}\.[a-z0-9]{1,8}|[0-9a-f]{64}\.[a-z0-9]{1,8})\)/g,m;
  while((m=re.exec(String(text||''))))if(!seen[m[1]]){seen[m[1]]=1;out.push(m[1]);}
  return out;}
/* One line of text -> HTML. opts.img(ref, alt) and opts.file(ref, label) draw
 * the references; opts.mention(call) an @CALL (7.5.2). */
function mdInline(s,opts){
  var keep=[],put=function(h){keep.push(h);return '\u0000'+(keep.length-1)+'\u0000';};
  s=String(s).replace(/\u0000/g,'');
  s=s.replace(/`([^`]+)`/g,function(_,c){return put('<code>'+mdEsc(c)+'</code>');});
  s=s.replace(/!\[([^\]]*)\]\(([^)\s]+)\)/g,function(all,alt,r){
    if(!isRef(r))return all;
    return put(isImageRef(r)&&opts.img?opts.img(r,alt):opts.file?opts.file(r,alt||r):mdEsc(all));});
  s=s.replace(/\[([^\]]+)\]\(([^)\s]+)\)/g,function(all,label,u){
    if(isRef(u))return put(opts.file?opts.file(u,label):mdEsc(label));
    if(!/^https?:\/\/[^\s<>"']+$/i.test(u))return all;
    return put('<a href="'+mdEsc(u)+'" target="_blank" rel="noopener nofollow">'+mdEmph(mdEsc(label))+'</a>');});
  s=s.replace(/\bhttps?:\/\/[^\s<>"'()\u0000]+[^\s<>"'().,;:!?\u0000]/gi,function(u){
    return put('<a href="'+mdEsc(u)+'" target="_blank" rel="noopener nofollow">'+mdEsc(u)+'</a>');});
  if(opts.mention)s=s.replace(/(^|[^A-Za-z0-9_@])@([A-Z0-9][A-Z0-9\/-]*[A-Z0-9]|[A-Z0-9])(?![a-z])/g,
    function(_,pre,c){return pre+put(opts.mention(c));});
  s=mdEmph(mdEsc(s));
  return s.replace(/\u0000(\d+)\u0000/g,function(_,i){return keep[+i];});
}
/* Emphasis on escaped text: **bold**, *italic*, _italic_ (not inside a word,
 * so snake_case stays), ~~strike~~. */
function mdEmph(s){
  return s.replace(/\*\*(?=\S)([^*]*?\S)\*\*/g,'<strong>$1</strong>')
    .replace(/~~(?=\S)([^~]*?\S)~~/g,'<del>$1</del>')
    .replace(/(^|[^*\w])\*(?=\S)([^*]*?\S)\*(?![*\w])/g,'$1<em>$2</em>')
    .replace(/(^|[^\w])_(?=\S)([^_]*?\S)_(?!\w)/g,'$1<em>$2</em>');
}
/* The whole text -> HTML blocks. */
function mdRender(text,opts){
  opts=opts||{};
  var lines=String(text||'').replace(/\r\n?/g,'\n').replace(/ ?\u2029 ?/g,'\n\n').replace(/ ?\u2028 ?/g,'\n').split('\n');
  var out=[],para=[],list=null,quote=[],i,l,m;
  var inl=function(t){return mdInline(t,opts);};
  function flush(){
    if(para.length){out.push('<p>'+para.map(inl).join('<br>')+'</p>');para=[];}
    if(list){out.push('<'+list.tag+'>'+list.items.map(function(x){return '<li>'+inl(x)+'</li>';}).join('')+'</'+list.tag+'>');list=null;}
    if(quote.length){out.push('<blockquote>'+quote.map(inl).join('<br>')+'</blockquote>');quote=[];}
  }
  for(i=0;i<lines.length;i++){
    l=lines[i].replace(/^\s+|\s+$/g,'');
    if(!l){flush();continue;}
    if((m=/^(#{1,3})\s+(.+)$/.exec(l))){flush();out.push('<h'+(m[1].length+2)+'>'+inl(m[2])+'</h'+(m[1].length+2)+'>');continue;}
    if(/^(?:-{3,}|\*{3,}|_{3,})$/.test(l)){flush();out.push('<hr>');continue;}
    if((m=/^>\s?(.*)$/.exec(l))){if(para.length||list)flush();quote.push(m[1]);continue;}
    if((m=/^[-*+]\s+(.+)$/.exec(l))||(m=/^\d{1,3}[.)]\s+(.+)$/.exec(l))){
      var tag=/^\d/.test(l)?'ol':'ul';
      if(para.length||quote.length||(list&&list.tag!==tag))flush();
      if(!list)list={tag:tag,items:[]};
      list.items.push(m[1]);continue;}
    if(list||quote.length)flush();
    para.push(l);
  }
  flush();
  return out.join('');
}
