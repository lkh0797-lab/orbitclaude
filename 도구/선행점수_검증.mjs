// 선행 점수 표본 외 검증 — 보정에 쓴 14종목을 뺀 회사들로, 화면과 같은 JS(invLead)로 보고서마다 점수를 매기고 공시 뒤 수익률을 적는다.
// 뷰어(127.0.0.1:8765)가 떠 있어야 한다. 처음 여는 보고서는 서버가 브리핑을 새로 만들어 몇 초씩 걸린다.
// node 도구/선행점수_검증.mjs 코드들.txt 결과.json [동시 회사 수=3]   →  python 도구/선행점수_검증_분석.py 결과.json
import { spawn } from 'node:child_process';
import { mkdtempSync, writeFileSync, readFileSync, existsSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
const codes=readFileSync(process.argv[2],'utf8').split(/\s+/).filter(Boolean), out=process.argv[3]||'lead_oos.json', CONC=+(process.argv[4]||3);
const port=9900+Math.floor(Math.random()*90), prof=mkdtempSync(join(tmpdir(),'ld-'));
const edge=spawn('C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',['--headless=new',`--remote-debugging-port=${port}`,`--user-data-dir=${prof}`,'about:blank'],{stdio:'ignore'});
const sleep=ms=>new Promise(r=>setTimeout(r,ms));
let list; for(let i=0;i<50;i++){ try{ list=await (await fetch(`http://127.0.0.1:${port}/json/list`)).json(); break; }catch{ await sleep(200); } }
const ws=new WebSocket(list.find(t=>t.type==='page').webSocketDebuggerUrl); await new Promise(r=>ws.onopen=r);
let id=0; const pend=new Map(); ws.onmessage=e=>{ const m=JSON.parse(e.data); if(m.id&&pend.has(m.id)){ pend.get(m.id)(m); pend.delete(m.id); } };
const cdp=(method,params={})=>new Promise(r=>{ const i=++id; pend.set(i,r); ws.send(JSON.stringify({id:i,method,params})); });
await cdp('Page.navigate',{url:'http://127.0.0.1:8765/'}); await sleep(3000);
// 이어 달리기 — 이미 적은 회사는 건너뛴다
let rows=existsSync(out)?JSON.parse(readFileSync(out,'utf8')):[];
const done=new Set(rows.map(r=>r.code));
const todo=codes.filter(c=>!done.has(c));
console.log('할 회사', todo.length, '/ 이미', done.size);
const one=async code=>{
  const expr=`(async()=>{ const out=[];
    const co=await (await fetch('/api/company?code=${code}')).json();
    if(!co||!co.reports) return JSON.stringify(out);
    const reps=co.reports.filter(r=>!r.tag && r.stamp>='2015-01');
    if(!reps.length) return JSON.stringify(out);
    const full=await (await fetch('/api/invest?code=${code}&rcept='+reps[reps.length-1].rcept)).json();
    if(!full||!full.series) return JSON.stringify(out);
    for(const r of reps){
      let d; try{ d=await (await fetch('/api/invest?lite=1&code=${code}&rcept='+r.rcept)).json(); }catch(e){ continue; }
      if(!d||d.first||d.error) continue;
      d.series=full.series; d.arc=full.arc;
      const S=d.series, k=invPriceAt(S,+d.filed); if(k<0) continue;
      const ld=invLead(d);
      out.push({code:'${code}', stamp:r.stamp, label:r.label, filed:d.filed, L:ld.score, q:ld.q, story:ld.parts.story, tape:ld.parts.tape, mom:ld.parts.mom,
        f1:invFwd(S,k,21), f3:invFwd(S,k,63), f6:invFwd(S,k,126), f12:invFwd(S,k,250)});
    }
    return JSON.stringify(out); })()`;
  const r=await cdp('Runtime.evaluate',{expression:expr,awaitPromise:true,returnByValue:true});
  const v=r.result&&r.result.result&&r.result.result.value;
  return v?JSON.parse(v):null;
};
let n=0; const t0=Date.now();
const queue=todo.slice();
const worker=async()=>{ while(queue.length){ const code=queue.shift(); const arr=await one(code).catch(()=>null);
  n++; if(arr){ rows.push(...arr); } console.log(n+'/'+todo.length, code, arr?arr.length:'fail', Math.round((Date.now()-t0)/1000)+'s');
  if(n%5===0) writeFileSync(out, JSON.stringify(rows)); } };
await Promise.all(Array.from({length:CONC},worker));
writeFileSync(out, JSON.stringify(rows));
console.log('done', rows.length);
ws.close(); edge.kill(); process.exit(0);
