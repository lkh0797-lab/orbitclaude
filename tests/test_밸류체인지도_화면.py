# -*- coding: utf-8 -*-
"""밸류체인 한 장 화면(웹/index.html vcBoard) — 헤드리스 크롬에 index.html 을 file:// 로 띄우고 fetch 를 가짜로 바꿔
판 하나를 붙여 누른다. 서버 · 실제 캐시는 쓰지 않는다. 크롬 · node(22+, WebSocket 내장)가 없으면 건너뛴다.

보는 것(리뷰 ui-1 ~ ui-4):
- 심층 칸 노드 요청이 걸린 사이 폴링이 새 판(stale → fresh)을 그려도 응답이 오면 새 칸이 값을 그린다('불러오는 중…'에 멈추지 않는다).
- 매트릭스 안 회사도 /api/vcmap/node 근거 줄(어느 보고서 · 어느 표 · 몇 %)을 받는다. '후속주 B군 n점' 줄은 위 칸과 겹쳐 뺀다.
- 매입처 칩은 이은 상장사 이름(co) — 적힌 이름은 풍선에. 같은 칸의 '나를 매출처로 적은' 줄은 칩 없이 근거만.
- 거르기 칩 · 더 보기 · 심층 칸 × 뒤에 초점이 body 로 떨어지지 않는다."""
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


def _row(code, name, group, score, link):
    return {"code": code, "name": name, "group": group, "score": score, "stars": 3, "why": name + " 근거",
            "parts": {"link": 3, "fund": 4, "attn": 3, "lag": 3, "safe": 5},
            "ev": {"link": link, "fund": ["확장 유지"], "attn": [], "lag": [], "safe": ["위험 꼬리표 없음"]},
            "px": {"px": 1000, "dd52": -5.0, "r1m": 1.0, "r3m": 2.0, "r6m": 3.0}, "phase": "확장 유지", "old": False, "flags": []}


def board():
    rows = [_row("005070", "코스모신소재", "B", 18, ["삼성전기 매입처 · FILM"])]
    rows += [_row("9%05d" % i, "후보%d" % i, "C" if i % 2 else "D", 17 - i, ["테마"]) for i in range(14)]
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
  return R; })()`;
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
    fx.write_text(json.dumps({"board": board(), "node": NODES}, ensure_ascii=False), encoding="utf-8")
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
