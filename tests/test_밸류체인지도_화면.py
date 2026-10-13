# -*- coding: utf-8 -*-
"""밸류체인 한 장 화면(웹/index.html vcBoard) — 헤드리스 크롬에 index.html 을 file:// 로 띄우고 fetch 를 가짜로 바꿔
판 하나를 붙여 누른다. 서버 · 실제 캐시는 쓰지 않는다. 크롬 · node(22+, WebSocket 내장)가 없으면 건너뛴다.

보는 것(리뷰 ui-1 ~ ui-4):
- 심층 칸 노드 요청이 걸린 사이 폴링이 새 판(stale → fresh)을 그려도 응답이 오면 새 칸이 값을 그린다('불러오는 중…'에 멈추지 않는다).
- 매트릭스 안 회사도 /api/vcmap/node 근거 줄(어느 보고서 · 어느 표 · 몇 %)을 받는다. '후속주 B군 n점' 줄은 위 칸과 겹쳐 뺀다.
- 매입처 칩은 이은 상장사 이름(co) — 적힌 이름은 풍선에. 같은 칸의 '나를 매출처로 적은' 줄은 칩 없이 근거만.
- 거르기 칩 · 더 보기 · 심층 칸 × 뒤에 초점이 body 로 떨어지지 않는다.

2차(근거 객체 · 리뷰 ui-1 ~ ui-4, 2026-10-13):
- › 탭 이동은 목표 탭을 먼저 켜고 pick 한다 — 그 회사 밸류체인 한 장(/api/vcmap · /api/valuechain)을 서버에 만들게 하지 않는다. 수집 안 한 회사(404)면 탭을 되돌린다.
- › 단추는 ↗ 와 같은 꼴(전역 .go 규칙에 밀리지 않는다) · hover 에도 글자가 남는다(CDP 로 실제 마우스를 올려 잰다).
- 근거 줄 링크 · 머리 띠 vbA 는 http(s) 스킴만 — 'dart.fss.or.kr/x' · 'javascript:' 는 글자만.
- 출처 글은 11.5px · AA 4.5:1(라이트 · 다크 — 다크는 prefers-color-scheme 을 흉내 내 다시 잰다), 좁은 폭에서 링크 단추 24px · 사이 8px."""
import os, json, shutil, socket, subprocess
import pytest

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HTML = os.path.join(BASE, "웹", "index.html")
CHROMES = [os.environ.get("CHROME") or "", r"C:\Program Files\Google\Chrome\Application\chrome.exe",
           r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
           r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe", r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"]
CHROME = next((p for p in CHROMES if p and os.path.isfile(p)), None)
NODE = shutil.which("node")

FILM = "컴포넌트 원재료 FILM 매입처 · 매입 비중 24.9% · 보고서 표기 'COSMO' (2026 반기 · 주요 원재료)"
SELLER = "코스모신소재가 삼성전기를 매출처로 적음 · FILM"


def _row(code, name, group, score, link, ev=None):
    e = {"link": link, "fund": ["확장 유지"], "attn": [], "lag": [], "safe": ["위험 꼬리표 없음"]}
    e.update(ev or {})
    return {"code": code, "name": name, "group": group, "score": score, "stars": 3, "why": name + " 근거",
            "parts": {"link": 3, "fund": 4, "attn": 3, "lag": 3, "safe": 5}, "ev": e,
            "px": {"px": 1000, "dd52": -5.0, "r1m": 1.0, "r3m": 2.0, "r6m": 3.0}, "phase": "확장 유지", "old": False, "flags": []}


# 2차 — 근거 객체 {t,src,date,url,go,more}. 스킴 없는 url · javascript: 는 링크를 달면 안 되고(ui-3), go 는 › 단추(ui-1 · ui-2)
EV2 = {"fund": [{"t": "확장 유지 · 가속B +3.0 · OPM 10.0% (2026Q2)", "src": "가속도 탭 · DART 분기 재무 (druck v4)", "date": "20260814", "go": {"tab": "druck"}}],
       "attn": [{"t": "FC-BGA 리포트 2건(180일)", "src": "최신 증권사 미표기 2026-10-08", "date": "20261008", "url": "dart.fss.or.kr/x",
                 "more": {"src": "A증권 2026-10-01", "date": "20261001", "url": "javascript:alert(1)"}},
                {"t": "리포트 목표가 평균 100,000원 → +50%", "src": "리포트 2건 180일 증권사별 최신 목표가 평균", "url": "https://t.me/companyreport/1",
                 "more": {"src": "B증권 2026-09-30", "date": "20260930", "url": "https://t.me/companyreport/2"}, "go": {"tab": "rep"}}],
       "safe": [{"t": "위험 꼬리표 없음", "src": "공시위험 · KIS 종목 상태 20261013"}]}
# /api/company — pick 이 받는 회사. 005070 만 수집한 회사, 나머지(900001 …)는 404
COMPANY = {"005070": {"code": "005070", "name": "코스모신소재", "from": "2020-03", "to": "2026-08", "count": 0, "bytes": 0, "reports": [], "sections": []}}


def board():
    rows = [_row("005070", "코스모신소재", "B", 18, ["삼성전기 매입처 · FILM"], EV2)]
    rows += [_row("9%05d" % i, "후보%d" % i, "C" if i % 2 else "D", 17 - i, ["테마"],
                  {"attn": [{"t": "리포트 1건", "src": "C증권 2026-09-01", "go": {"tab": "rep"}}]} if i == 1 else None) for i in range(14)]
    cnt = {g: sum(r["group"] == g for r in rows) for g in ("B", "C", "D", "Fake")}
    return {"v": 1, "code": "009150", "name": "삼성전기", "built": "2026-10-12 09:00:00",
            "head": {"leader": {"code": "009150", "name": "삼성전기"}, "story": {}, "triggers": [], "counts": dict(cnt, total=len(rows))},
            "net": {"owner": {"name": "삼성전자", "code": "005930", "pct": 23.69, "kind": "listed", "rel": "최대주주 본인", "src": "2026-06 반기보고서"},
                    "group": {"listed": 18}, "listed_subs": 0,
                    "holdings": [{"name": "삼성중공업", "code": "010140", "pct": 2.1, "purpose": "경영참여"}],
                    "products": [{"item": "수동소자", "seg": "컴포넌트", "pct": 45.9, "c": 0}],
                    "up": [{"seg": "컴포넌트", "c": 0, "label": "상류 · 컴포넌트 소재 · 장비",
                            "items": [{"item": "FILM", "pct": 24.9, "sup": [{"name": "COSMO", "code": "005070", "co": "코스모신소재"},
                                                                          {"name": "SHOEI", "code": None}]}],
                            "listed": [{"name": "코스모신소재", "code": "005070", "why": SELLER}]}],
                    "down": [{"kind": "customer", "name": "삼성전자", "code": "005930", "pct": 26.0, "why": "매출처 26.0% (2026 반기)"}],
                    "uses": ["스마트폰"], "peers": [{"code": "900001", "name": "후보1", "group": "C"}]},
            "matrix": rows, "src": {}, "note": "규칙 점수 · 검증 전 — 예측 아님"}


NODES = {
    "005070": {"code": "005070", "name": "코스모신소재", "collected": True, "px": {"px": 5000}, "phase": "확장 가속", "reports_n": 1, "flags": [],
               "rel": [FILM, SELLER, "후속주 B군 18점 — 삼성전기 공급사 · FILM", "삼성전기 매입처 · FILM"]},
    "010140": {"code": "010140", "name": "삼성중공업", "collected": True, "px": {"px": 20000, "dd52": -10.0}, "phase": "회복", "reports_n": 3,
               "flags": [], "rel": ["삼성전기 보유 2.10% · 경영참여 (2026-06 반기보고서 · 타법인출자 현황)"]},
}

# 헤드리스 크롬 몰기 — CDP(WebSocket). 결과 JSON 한 줄을 찍는다
HARNESS = r'''
const fs=require('fs'), {spawn}=require('child_process'), {pathToFileURL}=require('url');
const [,, PORT, HTML, FIX, PROF, CHROME]=process.argv;
if(typeof WebSocket!=='function'){ console.log(JSON.stringify({skip:'node 에 WebSocket 없음(22+ 필요)'})); process.exit(0); }
const P=JSON.parse(fs.readFileSync(FIX,'utf8'));
const sleep=ms=>new Promise(r=>setTimeout(r,ms));
const ch=spawn(CHROME,['--headless=new','--remote-debugging-port='+PORT,'--user-data-dir='+PROF,'--no-first-run','--no-default-browser-check','--disable-extensions','--window-size=1500,1200','about:blank'],{stdio:'ignore'});
const guard=setTimeout(()=>{ try{ ch.kill(); }catch(e){} console.log(JSON.stringify({error:'timeout'})); process.exit(3); },80000);
const STUB=`(()=>{ const P=${JSON.stringify(P)}; window.__P=P; window.__calls=[]; window.__next=null; window.__hold=null; window.__release=null;
  const R=o=>new Response(JSON.stringify(o),{headers:{'content-type':'application/json'}});
  window.fetch=u=>{ u=String(u); window.__calls.push(u);
    const m=u.match(/\\/api\\/vcmap\\/node\\?code=(\\w+)/);
    if(m){ const r=P.node[m[1]]||{error:'없음'}; if(window.__hold===m[1]) return new Promise(res=>{ window.__release=()=>res(R(r)); }); return Promise.resolve(R(r)); }
    if(/\\/api\\/vcmap\\?code=/.test(u)) return Promise.resolve(R(window.__next||P.board));
    const cm=u.match(/\\/api\\/company\\?code=(\\w+)/);
    if(cm){ const c=(P.company||{})[cm[1]]; return Promise.resolve(c?R(c):new Response('',{status:404})); }
    return new Promise(()=>{}); }; })();`;
const SCENARIO=`(async()=>{
  const W=async(f,n=100)=>{ for(let i=0;i<n;i++){ const v=f(); if(v) return v; await new Promise(r=>setTimeout(r,50)); } return null; };
  const txt=b=>((b.querySelector('.vbDet')||{}).textContent)||'';
  const calls=c=>window.__calls.filter(u=>u.indexOf('/api/vcmap/node?code='+c)>=0).length;
  if(typeof vcBoard!=='function') return {error:'vcBoard 없음'};
  const host=document.createElement('div'); host.style.cssText='position:relative;width:1400px'; document.body.prepend(host);
  const cp=o=>JSON.parse(JSON.stringify(o));
  const mount=async d=>{ S.tab='tl'; S.co={code:d.code,name:d.name}; S.vb=null; host.innerHTML='';
    const box=vcBoard({code:d.code},Promise.resolve(d)); host.appendChild(box); await W(()=>box.querySelector('.vbNote small')); return box; };
  const R={};
  let b=await mount(cp(window.__P.board));
  // ui-3 — 매입처 칩 이름
  const up=b.querySelector('.vbNode.up');
  R.upChips=[...up.querySelectorAll('button.vbCo')].map(x=>({t:x.textContent.trim(),title:x.title,code:x.dataset.code}));
  R.upWhy=[...up.querySelectorAll('.w')].map(x=>x.textContent);
  // ui-2 — 매트릭스 안 회사도 서버 근거 줄
  const c=up.querySelector('button.vbCo[data-code="005070"]'); const n0=calls('005070');
  c.click(); R.inFirst=txt(b);
  await W(()=>/매입 비중/.test(txt(b)));
  const rs=[...b.querySelectorAll('.vbDet .vbDS')].find(s=>/관계 근거/.test(s.textContent));
  R.inRel=rs?[...rs.querySelectorAll('li')].map(l=>l.textContent):[]; R.inCalls=calls('005070')-n0; R.inHead=(b.querySelector('.vbDetH b')||{}).textContent;
  c.click();
  // ui-4 — × 로 닫으면 초점은 연 칩으로
  const h=b.querySelector('button.vbCo[data-code="010140"]'); h.focus(); h.click();
  await W(()=>/종가/.test(txt(b)));
  const x=b.querySelector('.vbDet .vbX'); x.focus(); x.click();
  R.closeFocus=document.activeElement===h; R.closed=!b.querySelector('.vbDet');
  // ui-4 — 거르기 칩 · 더 보기
  const chip=g=>[...b.querySelectorAll('.vbChips button')].find(e=>(e.dataset.g||'')===g);
  let k=chip('C'); k.focus(); k.click();
  R.chipFocus=document.activeElement===k&&chip('C')===k; R.chipPressed=k.getAttribute('aria-pressed'); R.chipOn=k.classList.contains('on');
  R.chipRows=[...b.querySelectorAll('.vbRow')].map(r=>r.dataset.g);
  k=chip(''); k.focus(); k.click(); R.allFocus=document.activeElement===k; R.cPressed=chip('C').getAttribute('aria-pressed');
  const m=b.querySelector('.vbMore'); R.moreText=m&&m.textContent; m.focus(); m.click();
  const a=document.activeElement, rows=[...b.querySelectorAll('.vbRow')];
  R.moreFocus={cls:a.className,idx:rows.findIndex(r=>r.contains(a)),n:rows.length};
  // ui-1 — 노드 요청이 걸린 사이 폴링이 새 판을 그린다(stale → fresh)
  window.__next=Object.assign(cp(window.__P.board),{built:'2026-10-12 09:05:00'}); window.__hold='010140';
  b=await mount(Object.assign(cp(window.__P.board),{stale:true}));
  const n1=calls('010140');
  b.querySelector('button.vbCo[data-code="010140"]').click(); R.raceLoading=/불러오는 중/.test(txt(b));
  await W(()=>((b.querySelector('.vbNote small')||{}).textContent||'')==='10-12 09:05');
  R.raceRedrawn=(b.querySelector('.vbNote small')||{}).textContent; R.raceStillLoading=/불러오는 중/.test(txt(b));
  if(window.__release) window.__release();
  await W(()=>/종가/.test(txt(b)),40);
  R.raceAfter=txt(b); R.raceStuck=/불러오는 중/.test(R.raceAfter); R.raceCalls=calls('010140')-n1;
  // ---- 2차 리뷰 ui-1 ~ ui-4 — › 탭 이동이 밸류체인 탭을 거치지 않는다 · › 모양 · url 스킴 · 출처 대비 · 좁은 폭 단추 크기
  window.__next=null; window.__hold=null; window.__host=host;
  const tabsOn=()=>[...document.querySelector('#tabs').children].filter(x=>x.classList.contains('on')).map(x=>x.dataset.t);
  const openRow=code=>{ b.querySelector('.vbRow[data-code="'+code+'"]>.vbRowB').click(); return b.querySelector('.vbRow[data-code="'+code+'"] .vbRowD'); };
  const lum=c=>{ const m=(c.match(/\\d+(\\.\\d+)?/g)||[]).slice(0,3).map(Number).map(v=>{ v/=255; return v<=0.03928?v/12.92:Math.pow((v+0.055)/1.055,2.4); }); return 0.2126*m[0]+0.7152*m[1]+0.0722*m[2]; };
  window.__contrast=root=>{ const sm=root.querySelector('.vbEvL>.m small'), ss=getComputedStyle(sm), L1=lum(ss.color), L2=lum(getComputedStyle(sm.closest('.vbEvP')).backgroundColor);
    return {ratio:Math.round((Math.max(L1,L2)+0.05)/(Math.min(L1,L2)+0.05)*100)/100,size:ss.fontSize,color:ss.color}; };
  b=await mount(cp(window.__P.board)); let det=openRow('005070');
  // ui-3 — 근거 줄 링크는 http(s) 만
  R.evLines=[...det.querySelectorAll('.vbEvL')].map(l=>({t:(l.querySelector('.t')||{}).textContent,hrefs:[...l.querySelectorAll('a.vbLnk')].map(a=>a.getAttribute('href')),btn:[...l.querySelectorAll('button.vbLnk')].map(x=>x.className)}));
  R.allHttp=[...det.querySelectorAll('a')].every(a=>/^https?:\\/\\//.test(a.getAttribute('href')||''));
  R.vbA={js:vbA('x','javascript:alert(1)').tagName,rel:vbA('x','dart.fss.or.kr/x').tagName,ok:vbA('x','https://dart.fss.or.kr/x').tagName,none:vbA('x',null).tagName};
  // ui-2 — › 와 ↗ 가 같은 꼴(전역 .go 규칙에 안 밀린다). hover 는 harness 가 CDP 로 마우스를 올려 따로 잰다
  const cs=e=>{ const s=getComputedStyle(e), r=e.getBoundingClientRect(); return {w:Math.round(r.width),h:Math.round(r.height),p:s.padding,bw:s.borderTopWidth,bs:s.borderTopStyle,bg:s.backgroundColor,c:s.color,r:s.borderRadius}; };
  const a0=det.querySelector('a.vbLnk:not(.more)'), g0=det.querySelector('button.vbLnk');
  R.lnkA=cs(a0); R.lnkG=cs(g0); R.gCls=g0.className;
  // ui-4 — 출처 글 대비(라이트 — 다크는 harness 가 미디어를 바꿔 다시 잰다) · 좁은 폭 단추 24px · 사이 8px
  R.srcLight=window.__contrast(det);
  b.classList.add('narrow');
  R.narrowLnk=[...det.querySelectorAll('.vbLnk')].map(e=>{ const r=e.getBoundingClientRect(); return [Math.round(r.width),Math.round(r.height)]; });
  R.narrowGap=getComputedStyle(det.querySelector('.vbEvL>.m')).columnGap;
  b.classList.remove('narrow');
  R.wideLnk=[...det.querySelectorAll('.vbLnk')].map(e=>Math.round(e.getBoundingClientRect().height));
  // ui-1 — › : 목표 탭을 먼저 켜고 pick — 그 회사 밸류체인 한 장(/api/vcmap · /api/valuechain)을 묻지 않는다
  const vcCalls=c=>window.__calls.filter(u=>u.indexOf('/api/vcmap?code='+c)>=0||u.indexOf('/api/valuechain?code='+c)>=0).length;
  const n2=vcCalls('005070'); g0.click(); R.goTabAt=S.tab;
  await W(()=>S.co&&S.co.code==='005070'&&!g0.disabled);
  R.goCo=S.co&&S.co.code; R.goTab=S.tab; R.goOn=tabsOn(); R.goVc=vcCalls('005070')-n2;
  R.goPane=!!document.querySelector('#panes .drkplate'); R.goCalls=window.__calls.filter(u=>/company|druck/.test(u));
  // ui-1 — 수집 안 한 회사(/api/company 404)면 탭을 되돌리고 단추를 흐리게
  b=await mount(cp(window.__P.board)); det=openRow('900001');
  const g1=det.querySelector('button.vbLnk'), n3=vcCalls('900001'); g1.click(); R.failTabAt=S.tab;
  await W(()=>!g1.disabled);
  R.failTab=S.tab; R.failOn=tabsOn(); R.failOff=g1.classList.contains('off'); R.failTitle=g1.title; R.failCo=S.co&&S.co.code; R.failVc=vcCalls('900001')-n3;
  return R; })()`;
// hover · 다크 — 판을 다시 붙이고 › 를 화면 가운데로, harness 가 그 자리에 마우스를 올린 뒤 읽는다
const HOVER_PREP=`(async()=>{ const W=async(f,n=100)=>{ for(let i=0;i<n;i++){ const v=f(); if(v) return v; await new Promise(r=>setTimeout(r,50)); } return null; };
  const d=JSON.parse(JSON.stringify(window.__P.board)); S.tab='tl'; S.co={code:d.code,name:d.name}; S.vb=null; const host=window.__host; host.innerHTML='';
  const box=vcBoard({code:d.code},Promise.resolve(d)); host.appendChild(box); await W(()=>box.querySelector('.vbNote small'));
  box.querySelector('.vbRow[data-code="005070"]>.vbRowB').click(); const g=box.querySelector('.vbRowD button.vbLnk'); g.scrollIntoView({block:'center'}); window.__g=g;
  const r=g.getBoundingClientRect(); return {x:r.left+r.width/2,y:r.top+r.height/2}; })()`;
const HOVER_READ=`(()=>{ const g=window.__g, s=getComputedStyle(g), t=document.createElement('i'); t.style.cssText='background:var(--accent-soft);color:var(--accent)'; document.body.appendChild(t);
  const ts=getComputedStyle(t), o={hover:g.matches(':hover'),c:s.color,bg:s.backgroundColor,soft:ts.backgroundColor,accent:ts.color}; t.remove(); return o; })()`;
const DARK_READ=`window.__contrast(window.__g.closest('.vbRowD'))`;
(async()=>{ let out={};
  try{
    let list=null; for(let i=0;i<200&&!list;i++){ try{ list=await (await fetch('http://127.0.0.1:'+PORT+'/json/list')).json(); }catch(e){ await sleep(100); } }
    const ws=new WebSocket(list.find(t=>t.type==='page').webSocketDebuggerUrl); await new Promise((res,rej)=>{ ws.onopen=res; ws.onerror=rej; });
    let id=0; const pend=new Map(), ev=[];
    ws.onmessage=m=>{ const d=JSON.parse(m.data); if(d.id&&pend.has(d.id)){ pend.get(d.id)(d); pend.delete(d.id); } else ev.push(d); };
    const send=(method,params={})=>new Promise(res=>{ const i=++id; pend.set(i,res); ws.send(JSON.stringify({id:i,method,params})); });
    await send('Page.enable'); await send('Runtime.enable'); await send('Network.enable');
    await send('Network.setBlockedURLs',{urls:['*fonts.googleapis.com*','*fonts.gstatic.com*']});
    await send('Emulation.setDeviceMetricsOverride',{width:1500,height:1200,deviceScaleFactor:1,mobile:false});
    await send('Page.addScriptToEvaluateOnNewDocument',{source:STUB});
    await send('Page.navigate',{url:pathToFileURL(HTML).href});
    for(let i=0;i<200;i++){ await sleep(50); if(ev.some(e=>e.method==='Page.loadEventFired')) break; }
    const r=await send('Runtime.evaluate',{expression:SCENARIO,awaitPromise:true,returnByValue:true});
    out=r.result.exceptionDetails?{error:JSON.stringify(r.result.exceptionDetails).slice(0,800)}:r.result.result.value;
    if(!out.error){
      const h=await send('Runtime.evaluate',{expression:HOVER_PREP,awaitPromise:true,returnByValue:true});
      if(h.result.exceptionDetails) out.error='hover prep: '+JSON.stringify(h.result.exceptionDetails).slice(0,600);
      else { const pt=h.result.result.value; await send('Input.dispatchMouseEvent',{type:'mouseMoved',x:pt.x,y:pt.y}); await sleep(200);
        out.hover=(await send('Runtime.evaluate',{expression:HOVER_READ,returnByValue:true})).result.result.value;
        await send('Emulation.setEmulatedMedia',{features:[{name:'prefers-color-scheme',value:'dark'}]}); await sleep(200);
        out.srcDark=(await send('Runtime.evaluate',{expression:DARK_READ,returnByValue:true})).result.result.value; }
    }
    await send('Browser.close').catch(()=>{});
  }catch(e){ out={error:String(e&&e.message||e)}; }
  clearTimeout(guard); try{ ch.kill(); }catch(e){}
  console.log(JSON.stringify(out)); process.exit(0);
})();
'''


@pytest.fixture(scope="module")
def ui(tmp_path_factory):
    if not (CHROME and NODE):
        pytest.skip("크롬 · node 가 없다")
    d = tmp_path_factory.mktemp("vbui")
    js, fx = d / "harness.js", d / "fix.json"
    js.write_text(HARNESS, encoding="utf-8")
    fx.write_text(json.dumps({"board": board(), "node": NODES, "company": COMPANY}, ensure_ascii=False), encoding="utf-8")
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0)); port = s.getsockname()[1]
    p = subprocess.run([NODE, str(js), str(port), HTML, str(fx), str(d / "prof"), CHROME],
                       capture_output=True, text=True, encoding="utf-8", timeout=120)
    lines = [x for x in (p.stdout or "").splitlines() if x.startswith("{")]
    assert lines, "harness 출력 없음: " + (p.stderr or "")[-800:]
    out = json.loads(lines[-1])
    if out.get("skip"):
        pytest.skip(out["skip"])
    assert not out.get("error"), out.get("error")
    return out


def test_race_node_reply_after_redraw_paints_new_panel(ui):
    assert ui["raceLoading"] is True                     # 누른 바로 뒤엔 받는 중
    assert ui["raceRedrawn"] == "10-12 09:05"            # 폴링이 새 판으로 다시 그렸다
    assert ui["raceStillLoading"] is True                # 새 칸도 같은 요청을 기다린다(두 번 묻지 않는다)
    assert ui["raceStuck"] is False and "종가" in ui["raceAfter"] and "회복" in ui["raceAfter"]
    assert ui["raceCalls"] == 1


def test_in_matrix_node_gets_server_evidence(ui):
    assert "종가" in ui["inFirst"] and "불러오는 중" not in ui["inFirst"]   # 주가 · 국면은 매트릭스 줄 값 그대로, 바로
    assert FILM in ui["inRel"] and SELLER in ui["inRel"] and "삼성전기 매입처 · FILM" in ui["inRel"]
    assert not any(z.startswith("후속주 ") for z in ui["inRel"])            # 위 '후속주 매트릭스' 칸과 겹침
    assert ui["inCalls"] == 1 and ui["inHead"] == "코스모신소재"


def test_supplier_chip_shows_linked_listed_name(ui):
    cs = [c for c in ui["upChips"] if c["code"] == "005070"]
    assert len(cs) == 1                                  # 'COSMO' · 코스모신소재 두 칩이 아니다
    assert cs[0]["t"].startswith("코스모신소재") and "보고서 표기 COSMO" in cs[0]["title"]
    assert not any(c["t"].startswith("COSMO") for c in ui["upChips"])
    assert SELLER in ui["upWhy"]                         # 나를 매출처로 적은 근거 줄은 남는다


def test_focus_kept_after_filter_more_and_close(ui):
    assert ui["chipFocus"] is True and ui["chipPressed"] == "true" and ui["chipOn"] is True
    assert ui["chipRows"] and set(ui["chipRows"]) == {"C"}
    assert ui["allFocus"] is True and ui["cPressed"] == "false"
    assert ui["moreText"] == "나머지 3곳 더 보기"
    assert ui["moreFocus"] == {"cls": "vbRowB", "idx": 12, "n": 15}   # 새로 드러난 첫 줄
    assert ui["closeFocus"] is True and ui["closed"] is True


# ---- 2차 리뷰 ui-1 ~ ui-4

def test_go_tab_turns_tab_first_and_skips_valuechain_build(ui):
    """ui-1 — › 는 목표 탭을 먼저 켜고 pick 한다: 그 회사 밸류체인 한 장(/api/vcmap · /api/valuechain)을 서버에 만들게 하지 않는다."""
    assert ui["goTabAt"] == "druck"                                     # 누른 즉시 목표 탭
    assert ui["goCo"] == "005070" and ui["goTab"] == "druck" and ui["goOn"] == ["druck"]
    assert ui["goVc"] == 0                                              # 그 회사 vcmap · valuechain 요청 0
    assert ui["goPane"] is True                                         # pick 끝의 show 가 바로 가속도 탭을 그렸다
    assert any("/api/company?code=005070" in u for u in ui["goCalls"]) and any("/api/druck?code=005070" in u for u in ui["goCalls"])
    # 수집 안 한 회사(404) — 탭을 되돌리고 단추를 흐리게, 회사는 그대로
    assert ui["failTabAt"] == "rep" and ui["failTab"] == "tl" and ui["failOn"] == ["tl"]
    assert ui["failOff"] is True and "열 수 없다" in ui["failTitle"] and ui["failCo"] == "009150" and ui["failVc"] == 0


def test_tab_button_looks_like_link_button_and_keeps_text_on_hover(ui):
    """ui-2 — › 가 전역 .go(기본 단추) 규칙에 밀리지 않는다: ↗ 와 같은 크기 · 테두리 · 바탕 · 글자색, hover 에도 글자가 남는다."""
    assert ui["gCls"] == "vbLnk tab"
    assert ui["lnkG"] == ui["lnkA"]
    assert ui["lnkG"]["w"] == 18 and ui["lnkG"]["h"] == 18 and ui["lnkG"]["p"] == "0px" and ui["lnkG"]["bw"] == "1px" and ui["lnkG"]["bs"] == "solid"
    h = ui["hover"]
    assert h["hover"] is True and h["bg"] == h["soft"]                  # 바탕은 --accent-soft
    assert h["c"] == h["accent"] and h["c"] != "rgb(255, 255, 255)"     # 글자는 --accent 그대로(전엔 .go 의 흰색이 남아 사라졌다)


def test_evidence_links_only_with_http_scheme(ui):
    """ui-3 — url 스킴이 http(s) 가 아니면 링크를 달지 않는다(상대 경로 · javascript:). 머리 띠 vbA 도 같다."""
    L = {l["t"]: l for l in ui["evLines"]}
    assert L["FC-BGA 리포트 2건(180일)"]["hrefs"] == []                   # 'dart.fss.or.kr/x' · more 'javascript:alert(1)' 둘 다 글자만
    good = L["리포트 목표가 평균 100,000원 → +50%"]
    assert good["hrefs"] == ["https://t.me/companyreport/1", "https://t.me/companyreport/2"] and good["btn"] == ["vbLnk tab"]
    assert ui["allHttp"] is True
    assert ui["vbA"] == {"js": "SPAN", "rel": "SPAN", "ok": "A", "none": "SPAN"}


def test_source_text_contrast_and_narrow_touch_size(ui):
    """ui-4 — 출처 글은 11.5px · AA 4.5:1(라이트 · 다크), 좁은 폭에서 링크 단추는 24px 높이 · 24px 이상 폭 · 사이 8px."""
    assert ui["srcLight"]["size"] == "11.5px" and ui["srcLight"]["ratio"] >= 4.5, ui["srcLight"]
    assert ui["srcDark"]["size"] == "11.5px" and ui["srcDark"]["ratio"] >= 4.5, ui["srcDark"]
    assert ui["srcDark"]["color"] != ui["srcLight"]["color"]            # 다크 토큰이 실제로 붙었다
    assert ui["narrowLnk"] and all(w >= 24 and h == 24 for w, h in ui["narrowLnk"]) and ui["narrowGap"] == "8px"
    assert set(ui["wideLnk"]) == {18}                                   # 넓은 폭은 전처럼 18px
