// 원탁 결론 vs 공시 뒤 주가 — 보고서마다 원탁을 다시 돌려 기록한다. 뷰어(127.0.0.1:8765)가 떠 있어야 한다.
// node 도구/원탁_백테스트.mjs 267260,042700,... out.json  →  python 도구/원탁_백테스트_분석.py out.json
import { spawn } from 'node:child_process';
import { mkdtempSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
const codes=(process.argv[2]||'267260').split(','), out=process.argv[3]||'bt.json';
const port=9900+Math.floor(Math.random()*90), prof=mkdtempSync(join(tmpdir(),'bt-'));
const edge=spawn('C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',['--headless=new',`--remote-debugging-port=${port}`,`--user-data-dir=${prof}`,'about:blank'],{stdio:'ignore'});
const sleep=ms=>new Promise(r=>setTimeout(r,ms));
let list; for(let i=0;i<50;i++){ try{ list=await (await fetch(`http://127.0.0.1:${port}/json/list`)).json(); break; }catch{ await sleep(200); } }
const ws=new WebSocket(list.find(t=>t.type==='page').webSocketDebuggerUrl); await new Promise(r=>ws.onopen=r);
let id=0; const pend=new Map(); ws.onmessage=e=>{ const m=JSON.parse(e.data); if(m.id&&pend.has(m.id)){ pend.get(m.id)(m); pend.delete(m.id); } };
const cdp=(method,params={})=>new Promise(r=>{ const i=++id; pend.set(i,r); ws.send(JSON.stringify({id:i,method,params})); });
await cdp('Page.navigate',{url:'http://127.0.0.1:8765/'}); await sleep(3000);
const rows=[];
for(const code of codes){
  const expr=`(async()=>{ const out=[];
    const co=await (await fetch('/api/company?code=${code}')).json();
    const reps=co.reports.filter(r=>!r.tag && r.stamp>='2015-01');
    const full=await (await fetch('/api/invest?code=${code}&rcept='+reps[reps.length-1].rcept)).json();
    for(const r of reps){
      let d; try{ d=await (await fetch('/api/invest?lite=1&code=${code}&rcept='+r.rcept)).json(); }catch(e){ continue; }
      if(!d||d.first) continue;
      d.series=full.series; d.arc=full.arc; d.regimes=full.regimes;
      if(!d.series) continue;
      const S=d.series, k=invPriceAt(S,+d.filed); if(k<0) continue;
      const A=(d.arc||[]).slice().sort((a,b)=>a.date.localeCompare(b.date));
      const nx=A.find(a=>a.date>d.filed);
      const ke=nx?invPriceAt(S,+nx.date-1):-1;
      const [y,m]=r.stamp.split('-'); const qe=+(y+m+(m==='03'||m==='12'?'31':'30'));
      const kq=invPriceAt(S,qe), kp=(()=>{ const pv=A.filter(a=>a.date<d.filed).pop(); return pv?invPriceAt(S,+pv.date):-1; })();
      // ty 는 엔진 1 논거 무게로 잰다 — 선행 점수(INV_LEAD)를 보정한 자와 같게
      const b=invDebate(d), b1=invDebate(d,1);
      const ty={}; b1.args.forEach(a=>{ ty[a.type]=(ty[a.type]||0)+a.sign*a.w; });
      out.push({code:'${code}', name:co.name, stamp:r.stamp, label:r.label, filed:d.filed, M:b1.M, M2:b.M, L:b.lead?b.lead.score:null, verdict:b1.verdict, verdict2:b.verdict,
        c:Object.fromEntries(b.agents.map(g=>[g.k,g.c])), ty,
        f1:invFwd(S,k,21), f3:invFwd(S,k,63), f6:invFwd(S,k,126), fnext: ke>k?(S.p[ke]/S.p[k]-1)*100:null,
        pre: kq>=0&&kq<k?(S.p[k]/S.p[kq]-1)*100:null, prevc: kp>=0&&kp<k?(S.p[k]/S.p[kp]-1)*100:null,
        lag: (Date.UTC(+d.filed.slice(0,4),+d.filed.slice(4,6)-1,+d.filed.slice(6,8))-Date.UTC(+String(qe).slice(0,4),+String(qe).slice(4,6)-1,+String(qe).slice(6,8)))/864e5,
        per: d.ttm?d.ttm.per:null, g: d.ttm?d.ttm.g:null, a: d.ttm?d.ttm.a:null });
    }
    return JSON.stringify(out); })()`;
  const r=await cdp('Runtime.evaluate',{expression:expr,awaitPromise:true,returnByValue:true});
  const v=r.result&&r.result.result&&r.result.result.value;
  if(v){ const arr=JSON.parse(v); rows.push(...arr); console.log(code, arr.length); writeFileSync(out, JSON.stringify(rows)); }
  else console.log(code, 'fail', JSON.stringify(r.result&&r.result.exceptionDetails||r).slice(0,300));
}
writeFileSync(out, JSON.stringify(rows));
console.log('done', rows.length);
ws.close(); edge.kill(); process.exit(0);
