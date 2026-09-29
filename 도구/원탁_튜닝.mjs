// 원탁 엔진 튜닝 — 자료는 한 번만 받고 설정(INV_KNOB·INV_BIAS·INV_WT…)만 바꿔 평가. 종목을 반으로 나눠 train/test 상관도 낸다.
// node 도구/원탁_튜닝.mjs 도구/원탁_튜닝_설정예.json out.txt   (뷰어가 떠 있어야 한다)
import { spawn } from 'node:child_process';
import { mkdtempSync, readFileSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
const cfgs=JSON.parse(readFileSync(process.argv[2]||'configs.json','utf-8')), out=process.argv[3]||'tune.txt';
const codes='267260,042700,005930,000660,064400,009150,011070,007660,025860,056190,064350,373220,375500,403870'.split(',');
const port=9800+Math.floor(Math.random()*90), prof=mkdtempSync(join(tmpdir(),'tn-'));
const edge=spawn('C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',['--headless=new',`--remote-debugging-port=${port}`,`--user-data-dir=${prof}`,'about:blank'],{stdio:'ignore'});
const sleep=ms=>new Promise(r=>setTimeout(r,ms));
let list; for(let i=0;i<50;i++){ try{ list=await (await fetch(`http://127.0.0.1:${port}/json/list`)).json(); break; }catch{ await sleep(200); } }
const ws=new WebSocket(list.find(t=>t.type==='page').webSocketDebuggerUrl); await new Promise(r=>ws.onopen=r);
let id=0; const pend=new Map(); ws.onmessage=e=>{ const m=JSON.parse(e.data); if(m.id&&pend.has(m.id)){ pend.get(m.id)(m); pend.delete(m.id); } };
const cdp=(method,params={})=>new Promise(r=>{ const i=++id; pend.set(i,r); ws.send(JSON.stringify({id:i,method,params})); });
const ev=async e=>{ const r=await cdp('Runtime.evaluate',{expression:e,awaitPromise:true,returnByValue:true}); return r.result.result?r.result.result.value:JSON.stringify(r.result); };
await cdp('Page.navigate',{url:'http://127.0.0.1:8765/'}); await sleep(3000);
console.log(await ev(`(async()=>{ window.__D=[]; for(const code of ${JSON.stringify(codes)}){
  const co=await (await fetch('/api/company?code='+code)).json();
  const reps=co.reports.filter(r=>!r.tag&&r.stamp>='2015-01');
  const full=await (await fetch('/api/invest?code='+code+'&rcept='+reps[reps.length-1].rcept)).json();
  for(const r of reps){ const d=await (await fetch('/api/invest?lite=1&code='+code+'&rcept='+r.rcept)).json(); if(!d||d.first) continue;
    d.series=full.series; d.arc=full.arc; const S=d.series; const k=invPriceAt(S,+d.filed); if(k<0) continue;
    window.__D.push({code, d, f1:invFwd(S,k,21), f3:invFwd(S,k,63), f6:invFwd(S,k,126)}); } }
  return 'loaded '+window.__D.length; })()`));
const base=await ev(`JSON.stringify({S:INV_SENS,B:INV_BIAS,U:INV_UPSIDE,W:INV_WT,K:INV_KNOB})`);
let txt='';
for(const cf of cfgs){
  const res=await ev(`(()=>{ const B=${base}; const cf=${JSON.stringify(cf)};
    // 설정 되돌리고 덮어쓰기
    for(const k in B.S) Object.assign(INV_SENS[k],B.S[k]); Object.assign(INV_BIAS,B.B); Object.assign(INV_UPSIDE,B.U); Object.assign(INV_WT,B.W); Object.assign(INV_KNOB,B.K);
    if(cf.K) Object.assign(INV_KNOB,cf.K); if(cf.B) Object.assign(INV_BIAS,cf.B); if(cf.U) Object.assign(INV_UPSIDE,cf.U); if(cf.W) Object.assign(INV_WT,cf.W);
    if(cf.S) for(const k in cf.S) Object.assign(INV_SENS[k],cf.S[k]);
    const R=window.__D.map(x=>{ const b=invDebate(x.d, cf.v||2); return {code:x.code,M:b.M,verdict:b.verdict,f1:x.f1,f3:x.f3,f6:x.f6}; });
    const codes=[...new Set(R.map(r=>r.code))].sort(); const train=new Set(codes.filter((c,i)=>i%2===0));
    const rep=(rs,h)=>{ const all=invSpear(rs.map(r=>r.M),rs.map(r=>r[h]));
      const byc={}; rs.forEach(r=>(byc[r.code]=byc[r.code]||[]).push(r));
      const w=Object.values(byc).map(v=>invSpear(v.map(r=>r.M),v.map(r=>r[h]))).filter(x=>x!=null);
      return (all==null?'  -  ':(all>=0?'+':'')+all.toFixed(3))+'/'+(w.length?((w.reduce((a,b)=>a+b,0)/w.length)>=0?'+':'')+(w.reduce((a,b)=>a+b,0)/w.length).toFixed(3):'-'); };
    const tr=R.filter(r=>train.has(r.code)), te=R.filter(r=>!train.has(r.code));
    const vb={}; R.forEach(r=>{ (vb[r.verdict]=vb[r.verdict]||[]).push(r.f3); });
    const vs=Object.entries(vb).map(([k,v])=>k.replace(/ · .*/,'').slice(0,6)+' '+v.length+' '+(invMed(v)>=0?'+':'')+(invMed(v)||0).toFixed(1)).join(' | ');
    return (cf.name||'').padEnd(22)+' f3 all '+rep(R,'f3')+'  train '+rep(tr,'f3')+'  test '+rep(te,'f3')+'  f1 '+rep(R,'f1')+'  f6 '+rep(R,'f6')+'\\n      '+vs; })()`);
  console.log(res); txt+=res+'\n';
}
writeFileSync(out,txt);
ws.close(); edge.kill(); process.exit(0);
