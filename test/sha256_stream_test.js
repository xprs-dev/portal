const fs=require('fs'),crypto=require('crypto'),vm=require('vm');
const ctx={};vm.createContext(ctx);vm.runInContext(fs.readFileSync(require('path').join(__dirname,'..','page','xprs_crypto.js'),'utf8'),ctx);
const hex=b=>Buffer.from(b).toString('hex');
for(const n of [0,1,55,56,63,64,65,1000,100003,3000000]){
  const d=new Uint8Array(n);for(let i=0;i<n;i++)d[i]=(i*31+7)&255;
  const st=ctx.sha256Init();let at=0,step=[1,7,64,1000,65537][n%5];
  while(at<n){ctx.sha256Update(st,d.subarray(at,Math.min(n,at+step)));at+=step;}
  const got=hex(ctx.sha256Final(st)),want=crypto.createHash('sha256').update(d).digest('hex'),one=hex(ctx.sha256(d));
  if(got!==want||one!==want){console.log('FAIL',n,got,want);process.exit(1);}
}
console.log('incremental sha256 ok');
