# -*- coding: utf-8 -*-
"""
기본적분석 — 이 회사가 무엇을 팔아 누구한테서 돈을 받고, 무엇이 오르면 좋고 나쁘며, 주가는 실제로 무엇을 따라갔나 (2026-10-22).

재료는 전부 정기보고서 원문(「II. 사업의 내용」 · 「III. 재무에 관한 사항」)과 기업추적 캐시다 — 모델 · 생성 문장 없음. 여기 함수는 순수 함수(파일 · 네트워크 없음).
서버(서버.fundamental_view)가 원문과 캐시를 읽어 이 함수들을 부르고 .cache/기본분석/{code}.json 에 둔다.

  sections(text)        「사업의 내용」을 표준 일곱 절(개요 · 제품 · 원재료 · 매출/수주 · 위험 · 계약/연구 · 기타)로 가른다
  overview(text)        개요의 산문 단락(표 칸 · 머리말 제외)
  segments_pct(text)    개요 · 제품 절의 '부문 · 설명 · N%' 표 → [{name, desc, pct}] (합 85~115% 일 때만)
  price_table(text)     '가격변동추이' 표 → [{item, vals}] (최신 기부터) + 최근 변화율
  risk_sentences(text)  환율 · 금리 · 원자재 · 교역/지정학 · 수요 문장(원문 그대로, 방향 낱말 표시)
  industry_notes(text)  기타 참고사항의 산업 특성 · 성장성 · 경쟁 · 점유율 · 경쟁력 요인 첫 단락
  regions(text)         나라 · 지역 언급 횟수(해외 노출의 거친 자리)
  fx_sensitivity(fin)   주석의 환율 · 금리 민감도 문장 발췌(숫자가 있으면 같이)
  commodity_of(item)    원재료 품목 → 거시 원자재 이름(구리 · 유가 · 철강 …) — 사전 매핑
  followers(px, series) 분기 주가 변화가 어느 숫자 변화를 따라갔나(피어슨 r · 표본 수) — 상관이지 인과가 아니다
  drivers(...)          호재 · 악재 판 — 요인마다 방향 · 세기 · 근거 종류(공시 숫자 · 공시 문장 · 구조에서 추론) · 원문

어기지 않을 것: 사고 팔라는 처방 · 좋다/나쁘다 판정 문장 없음(요인의 방향만), 실명(구루) 없음, 추론은 '구조에서 추론'이라 적는다.
"""
import math
import re

VERSION = 1

# ── 절 가르기 ─────────────────────────────────────────────────────────────────────────────────
SEC_HEADS = [
    ("overview", r"사업의\s*개요"), ("products", r"주요\s*제품\s*(?:및|과|,)?\s*서비스|주요\s*제품"),
    ("materials", r"원재료\s*(?:및|과)\s*생산설비|원재료"), ("sales", r"매출\s*(?:및|과)\s*수주\s*상황|매출\s*및\s*수주"),
    ("risk", r"위험\s*관리\s*(?:및|과)\s*파생\s*거래|위험\s*관리"), ("contracts", r"주요\s*계약\s*(?:및|과)\s*연구\s*개발|연구\s*개발"),
    ("etc", r"기타\s*참고\s*사항"),
]
HEAD_RE = re.compile(r"^\s*(\d)\s*[.)]\s*(.{2,40})$")


def sections(text):
    """표준 일곱 절로 가른다. 머리가 없으면(옛 보고서) 전부 overview 에 둔다."""
    out = {k: "" for k, _ in SEC_HEADS}
    cur, buf = None, []
    found = False
    for ln in text.split("\n"):
        m = HEAD_RE.match(ln)
        key = None
        if m and len(ln) < 60:
            for k, pat in SEC_HEADS:
                if re.search(pat, m.group(2)):
                    key = k
                    break
        if key:
            if cur:
                out[cur] = "\n".join(buf)
            cur, buf, found = key, [ln], True
        elif cur:
            buf.append(ln)
    if cur:
        out[cur] = "\n".join(buf)
    if not found:
        out["overview"] = text
    return out


# ── 산문 · 표 구분 ──────────────────────────────────────────────────────────────────────────────
NUMCELL = re.compile(r"^[\s(\-−]*[\d,]+(?:\.\d+)?\s*%?\)?\s*$")
PCT_LINE = re.compile(r"^\s*(\d{1,3}(?:\.\d+)?)\s*%\s*$")
PROSE_END = re.compile(r"(?:다|요|음|임|함)\s*\.?\s*$|습니다|입니다|됩니다|있다|한다|된다|이다")
SENT_SPLIT = re.compile(r"(?<=[다요음임함])\.\s+|(?<=습니다)\.\s*|(?<=입니다)\.\s*|(?<=됩니다)\.\s*")
TABLE_HEAD = re.compile(r"^(?:구\s*분|사업\s*부문|부\s*문|품\s*목|품\s*명|제\s*품|매출\s*유형|주요\s*상표|비\s*고|합\s*계|소\s*계|단위|\(단위)")


def is_prose(ln, min_len=40):
    s = ln.strip()
    if len(s) < min_len or NUMCELL.match(s):
        return False
    digits = sum(ch.isdigit() for ch in s)
    if digits > len(s) * 0.35:
        return False
    return bool(PROSE_END.search(s)) or s.endswith(".")


def sentences(text, lo=28, hi=260):
    """산문 줄만 이어 붙여 문장으로. 표 칸 · 짧은 머리말은 버린다."""
    lines = [ln.strip() for ln in text.split("\n") if is_prose(ln, 25)]
    out = []
    for ln in lines:
        for s in SENT_SPLIT.split(ln):
            s = s.strip().strip(".").strip()
            if lo <= len(s) <= hi:
                out.append(s + ".")
            elif len(s) > hi:
                out.append(s[:hi - 1].rstrip() + "….")
    return out


def overview(text, limit=1500):
    """개요의 산문 단락 — 표 · 머리말을 빼고 앞에서부터 limit 자까지. 둘째 값 = 전체 산문 자수."""
    sec = sections(text)["overview"]
    paras = [ln.strip() for ln in sec.split("\n") if is_prose(ln, 50)]
    total = sum(len(p) for p in paras)
    out, n = [], 0
    for p in paras:
        if n + len(p) > limit:
            room = limit - n
            if room > 160:          # 남은 자리에 문장 단위로 채우고 끝낸다
                cut = p[:room]
                k = max(cut.rfind("다. "), cut.rfind("다."), cut.rfind("니다"))
                if k > 60:
                    out.append(cut[:k + 2].rstrip() + " …")
            break
        out.append(p)
        n += len(p)
    return out, total


# ── 부문 · 제품 비중 표 ─────────────────────────────────────────────────────────────────────────
SEG_HDR = re.compile(r"사업\s*부문|부\s*문|품\s*목|제\s*품|구\s*분|사업\s*영역|서비스")
PCT_HDR = re.compile(r"비\s*중|비\s*율|구성비")
STOP_ROW = re.compile(r"^(?:주\s*\d*\)|※|\*|합\s*계|소\s*계|총\s*계|계$)")


HDR_CELL = re.compile(r"^(?:매\s*출\s*액|매\s*출|금\s*액|비\s*중|비\s*율|구성비|수\s*량|단\s*가|용\s*도|주요\s*상표\s*등?|생산\s*제품|품\s*목|제\s*품|사업\s*부문|부\s*문|구\s*분|매출\s*유형)$")


def segments_pct(text):
    """'이름 · (설명) · N%' 꼴의 표를 읽는다 — 영원무역 개요(이름 / 설명 / 68%) · 효성중공업 제품 표(부문 / 용도 / 상표 / 제품 / 금액 / 69.52% / 금액 / 63.31% …).
    숫자 묶음에서는 첫 % 만 그 줄의 비중(최신 기)으로 본다. 합이 85~115% 인 표만, 가장 먼저 맞는 표."""
    sec = sections(text)
    for key in ("overview", "products", "sales"):
        lines = [ln.strip() for ln in sec[key].split("\n")]
        lines = [ln for ln in lines if ln]
        for i, ln in enumerate(lines):
            if not PCT_HDR.search(ln) or len(ln) > 14:
                continue
            if not any(SEG_HDR.search(x) and len(x) < 14 for x in lines[max(0, i - 12):i]):
                continue
            rows, grp, in_num, took = [], [], False, False
            for x in lines[i + 1:i + 120]:
                if STOP_ROW.match(x) or HEAD_RE.match(x):
                    break
                if HDR_CELL.match(x):
                    grp = []
                    continue
                m = PCT_LINE.match(x)
                if m or NUMCELL.match(x):
                    if not in_num:
                        in_num, took = True, False
                    if m and not took and grp:
                        name = grp[0]
                        desc = grp[-1] if len(grp) > 1 else ""
                        if not NUMCELL.match(name) and len(name) <= 40:
                            rows.append({"name": name, "desc": desc[:90], "pct": float(m.group(1))})
                        took = True
                    continue
                if in_num:
                    in_num, grp = False, []
                grp.append(x)
            tot = sum(r["pct"] for r in rows)
            if 2 <= len(rows) <= 10 and 85 <= tot <= 115:
                return rows
    return []


# ── 가격변동추이 표 ─────────────────────────────────────────────────────────────────────────────
PRICE_HEAD = re.compile(r"가격\s*변동\s*추이|가격\s*추이|가격\s*변동")
PERIOD_CELL = re.compile(r"^(?:제\s*\d+\s*기|\d{4}\s*년?(?:\s*\d*\s*분기)?|당\s*기|전\s*기|전전기|\d{4}\.\s*\d{1,2}|\d{2}\s*년)")
NUM = re.compile(r"[\d,]+(?:\.\d+)?")


def _num(s):
    m = NUM.search(s.replace(" ", ""))
    if not m:
        return None
    try:
        v = float(m.group(0).replace(",", ""))
    except ValueError:
        return None
    if "(" in s and ")" in s or s.strip().startswith(("-", "−")):
        v = -v
    return v


def price_table(text, max_rows=8):
    """'가격변동추이' 표 — 머리 칸의 기수(제N기 · 연도)가 열, 그 다음 '품목 / 숫자×열' 이 행. 숫자는 보고서 단위 그대로(원 · 천원 · USD …).
    change = (첫 열 − 둘째 열) ÷ 둘째 열 — 보고서는 최신 기를 먼저 적는다(제17기 · 제16기 · 제15기)."""
    lines = [ln.strip() for ln in text.split("\n") if ln.strip()]
    out = []
    for i, ln in enumerate(lines):
        if not PRICE_HEAD.search(ln) or len(ln) > 40 or "가격" not in ln:
            continue
        # 머리 칸 — 기수가 2개 이상 나란히. 머리 전에 '해당사항 없음' · 다른 소제목 · 긴 산문이 오면 이 표가 아니다(효성중공업: 가격 표 없음 → 생산실적 표를 집던 것)
        j, cols, bad = i + 1, [], False
        while j < min(i + 14, len(lines)) and len(cols) < 6:
            x = lines[j]
            if PERIOD_CELL.match(x):
                cols.append(x)
            elif cols:
                break
            elif re.search(r"해당\s*사항\s*없|없습니다|생산\s*실적|생산\s*능력|가동률|매출\s*실적", x) or NOTE_HEAD.match(x) or len(x) > 80:
                bad = True
                break
            j += 1
        if bad or len(cols) < 2:
            continue
        rows, k = [], j
        while k < len(lines) and len(rows) < max_rows:
            name = lines[k]
            if HEAD_RE.match(name) or STOP_ROW.match(name) or PRICE_HEAD.search(name):
                break
            vals = []
            m = k + 1
            while m < len(lines) and len(vals) < len(cols) and NUMCELL.match(lines[m]):
                vals.append(_num(lines[m]))
                m += 1
            if len(vals) >= 2 and not NUMCELL.match(name) and len(name) <= 40:
                vals = [v for v in vals if v is not None]
                ch = (vals[0] / vals[1] - 1) * 100 if len(vals) >= 2 and vals[1] else None
                rows.append({"item": name, "vals": vals[:len(cols)], "cols": cols[:len(vals)], "change": ch})
                k = m
            else:
                k += 1
        if rows:
            out.extend(rows)
            if len(out) >= max_rows:
                break
    return out[:max_rows]


# ── 위험 문장 ───────────────────────────────────────────────────────────────────────────────────
RISK_KEYS = [
    ("fx", re.compile(r"환율|환\s*리스크|외환|달러|원화\s*(?:약세|강세)|환차|USD|유로화|엔화")),
    ("rate", re.compile(r"금리|이자율|차입금|이자비용|이자\s*부담")),
    # '여유가' · '자유무역' 같은 다른 낱말 속 글자를 잡지 않게 — 한글 앞글자 없는 유가 · 원가만
    ("input", re.compile(r"원자재|원재료|원부자재|(?<![가-힣])유가|나프타|구리|동\s*가격|철강|강판|니켈|알루미늄|면화|펄프|곡물|밀\s*가격|옥수수|설탕|리튬|원료\s*가격|소재\s*가격|매입\s*단가|(?<![가-힣])원가\s*(?:상승|부담)")),
    ("trade", re.compile(r"관세|(?<!자유)무역|지정학|전쟁|제재|수출\s*규제|보조금|통상|정책\s*(?:변화|리스크)|규제")),
    ("demand", re.compile(r"경기|수요|소비\s*심리|계절|날씨|기후|재고\s*(?:조정|누적)")),
]
TONE_UP = re.compile(r"긍정|유리|수혜|증가|개선|확대|성장|호재|회복")
TONE_DN = re.compile(r"부정|불리|악화|감소|위험|악재|압박|둔화|하락\s*위험|손실|축소|부담")


def risk_sentences(text, per_key=4):
    """위험관리 · 기타 참고사항 · 개요의 문장 중 환율 · 금리 · 원자재 · 교역 · 수요 낱말이 든 것. 원문 그대로, 방향 낱말만 표시."""
    sec = sections(text)
    pool = sentences(sec["risk"]) + sentences(sec["etc"]) + sentences(sec["overview"]) + sentences(sec["materials"])
    out, seen = {k: [] for k, _ in RISK_KEYS}, set()
    for s in pool:
        if s in seen:
            continue
        seen.add(s)
        for k, rx in RISK_KEYS:
            if len(out[k]) < per_key and rx.search(s):
                tone = "up" if TONE_UP.search(s) and not TONE_DN.search(s) else "down" if TONE_DN.search(s) and not TONE_UP.search(s) else "mixed"
                out[k].append({"s": s, "tone": tone})
                break
    return out


# ── 업의 본질 — 기타 참고사항 ──────────────────────────────────────────────────────────────────────
NOTE_HEAD = re.compile(r"^\s*\(?\s*(\d{1,2})\s*\)\s*(.{2,60})$")
NOTE_KINDS = [("특성", r"특성|특징"), ("성장성", r"성장|전망|경기\s*변동"), ("경쟁", r"경쟁\s*상황|경쟁\s*요소|경쟁\s*환경|경쟁\s*업체"),
              ("점유율", r"점유율"), ("경쟁력", r"경쟁력|성공\s*요인|핵심\s*역량"), ("규제", r"규제|법률|정책"), ("기타", r".")]
SEG_TAG = re.compile(r"^\s*\[\s*([^\]]{2,30})\s*\]\s*$")


def industry_notes(text, limit=420):
    sec = sections(text)["etc"] or ""
    out, cur, seg = [], None, ""
    for ln in sec.split("\n"):
        s = ln.strip()
        if not s:
            continue
        mt = SEG_TAG.match(s)
        if mt:
            seg = mt.group(1)
            continue
        m = NOTE_HEAD.match(s)
        if m and len(s) < 60:
            kind = next(k for k, pat in NOTE_KINDS if re.search(pat, m.group(2)))
            cur = {"seg": seg, "h": m.group(2).strip(), "kind": kind, "p": ""}
            out.append(cur)
            continue
        if cur is not None and is_prose(s, 30) and len(cur["p"]) < limit:
            cur["p"] = (cur["p"] + " " + s).strip()
    # '기타'(요약 재무현황 · 특허 건수 · 주석 같은 것)는 업의 본질이 아니다 — 이름 있는 종류(특성 · 성장성 · 경쟁 · 점유율 · 경쟁력 · 규제)만
    out = [x for x in out if x["p"] and x["kind"] != "기타"]
    for x in out:
        if len(x["p"]) > limit:
            x["p"] = x["p"][:limit - 1].rstrip() + "…"
    return out[:12]


# ── 지역 노출 ───────────────────────────────────────────────────────────────────────────────────
REGION_RX = [
    ("미국", r"미국|북미|U\.?S\.?A?\b|America|USA"), ("중국", r"중국|China|중화"), ("유럽", r"유럽|EU\b|독일|프랑스|이탈리아|영국|스페인|네덜란드|Europe"),
    ("일본", r"일본|Japan"), ("인도", r"인도(?!네시아)|India"), ("베트남", r"베트남|Vietnam"), ("방글라데시", r"방글라데시|Bangladesh"),
    ("동남아", r"동남아|인도네시아|태국|말레이시아|필리핀|싱가포르|ASEAN"), ("중동", r"중동|사우디|UAE|두바이|카타르"), ("중남미", r"남미|중남미|브라질|멕시코|엘살바도르"),
    ("대만", r"대만|Taiwan"), ("아프리카", r"아프리카|에티오피아"), ("국내", r"국내|한국|내수"),
]


def regions(text, top=7):
    cnt = []
    for name, pat in REGION_RX:
        n = len(re.findall(pat, text))
        if n:
            cnt.append({"name": name, "n": n})
    cnt.sort(key=lambda x: -x["n"])
    return cnt[:top]


# ── 주석 민감도 발췌 ─────────────────────────────────────────────────────────────────────────────
FX_SENS = re.compile(r"환율[이가]?\s*(\d{1,2})\s*%\s*(상승|하락|절상|절하|변동)")
RATE_SENS = re.compile(r"(?:금리|이자율)[이가]?\s*(\d+(?:\.\d+)?)\s*(%p?|bp|베이시스)\s*(상승|하락|변동)")
UNIT_RX = re.compile(r"\(\s*단위\s*[:：]\s*([^)]{1,12})\)")


def fx_sensitivity(fin_text, max_items=4):
    """「재무에 관한 사항」 주석에서 '환율이 N% 상승/하락' · '금리 1% 상승' 문장과 그 뒤 숫자(최대 4개)를 발췌한다. 해석은 하지 않는다 — 원문을 보인다."""
    lines = [ln.strip() for ln in fin_text.split("\n")]
    out, unit = [], ""
    for i, ln in enumerate(lines):
        mu = UNIT_RX.search(ln)
        if mu:
            unit = mu.group(1).strip()
        for kind, rx in (("fx", FX_SENS), ("rate", RATE_SENS)):
            m = rx.search(ln)
            if not m or len(ln) > 400:
                continue
            # 문장 뒤 표 — 숫자 칸을 그 앞의 짧은 이름 칸(USD · 상승 시 · 세전이익 …)과 짝지어 최대 8개. 긴 산문이 나오면 표가 끝난 것
            nums, rows, label = [], [], ""
            for x in lines[i + 1:i + 40]:
                if not x:
                    continue
                if NUMCELL.match(x):
                    v = _num(x)
                    if v is not None:
                        nums.append(v)
                        rows.append([label[:30], v])
                elif len(x) > 70 or HEAD_RE.match(x):
                    break
                elif len(x) <= 14:          # 통화 · '상승 시' 같은 짧은 칸만 이름표로(긴 설명 줄은 아니다)
                    label = x
                if len(nums) >= 8:
                    break
            q = ln if len(ln) <= 220 else ln[:219] + "…"
            key = (kind, q)
            if key in {(o["kind"], o["q"]) for o in out}:
                continue
            out.append({"kind": kind, "q": q, "pct": m.group(1), "dir": m.group(len(m.groups())), "nums": nums[:8], "rows": rows[:8], "unit": unit})
            if len(out) >= max_items:
                return out
    return out


# ── 원재료 → 거시 원자재 ──────────────────────────────────────────────────────────────────────────
COMMODITY = [
    ("구리", r"구리|전기동|동선|동\s*(?:가격|괴|판)|copper"), ("알루미늄", r"알루미늄|알미늄|aluminum|aluminium"), ("니켈", r"니켈|nickel"), ("아연", r"아연|zinc"), ("리튬", r"리튬|lithium"),
    ("철강·철광석", r"철강|강판|후판|선재|철근|열연|냉연|철광석|슬라브|빌릿|스틸|steel|코일"), ("유가·나프타", r"(?<![가-힣])유가|원유(?!\s*\(우유)|나프타|석유|벙커|경유|휘발유|LNG|LPG|천연가스|naphtha"),
    ("석유화학 원료", r"에틸렌|프로필렌|PVC|ABS|폴리에스터|폴리에스테르|합성수지|레진|수지|PTA|MEG|BTX|벤젠|톨루엔|polyester"), ("면화·섬유", r"면화|원면|원사|원단|섬유|사류|yarn|fabric|다운|down"),
    ("펄프·종이", r"펄프|고지|원지|종이|pulp"), ("곡물·설탕", r"소맥|밀가루|옥수수|대두|원당|설탕|곡물|쌀|팜유|대두유|커피|카카오|corn|wheat|sugar"), ("우유·축산", r"우유|원유\s*\(우유|돈육|돼지|계육|육류"),
    ("반도체·웨이퍼", r"웨이퍼|wafer|실리콘|포토레지스트|감광"), ("귀금속", r"백금|팔라듐|gold|silver"), ("시멘트·골재", r"시멘트|골재|레미콘|유연탄|석탄|coal"), ("전력", r"전력|전기료|전기요금"),
]
# 원소 기호 · 두 글자 약어는 대소문자 그대로, 영문 낱말 경계 안에서만(Chemical 의 'al' 이 알루미늄으로 잡히던 것)
COMMODITY_SYM = [("구리", r"(?<![A-Za-z])Cu(?![A-Za-z])"), ("알루미늄", r"(?<![A-Za-z])Al(?![A-Za-z])"), ("니켈", r"(?<![A-Za-z])Ni(?![A-Za-z])"), ("아연", r"(?<![A-Za-z])Zn(?![A-Za-z])"),
                 ("리튬", r"(?<![A-Za-z])Li(?![A-Za-z])"), ("석유화학 원료", r"(?<![A-Za-z])(?:PE|PP|PET)(?![A-Za-z])")]
OTHER_ITEM = re.compile(r"^\s*(?:기\s*타|그\s*밖|합\s*계|소\s*계|Others?|etc\.?)\s*$", re.I)


def commodity_of(item):
    s = item or ""
    for name, pat in COMMODITY:
        if re.search(pat, s, re.I):
            return name
    for name, pat in COMMODITY_SYM:
        if re.search(pat, s):
            return name
    return None


# ── 수출 · 내수 (밸류체인 export_split 이 못 읽은 꼴 — 영원무역 '수 출 / 해외(연결) / 기 타') ──────────────────────────────
CH_EX = re.compile(r"^(?:수\s*출|해\s*외(?:\s*\(연결\))?|직\s*수\s*출|로\s*컬\s*수\s*출|LOCAL\s*수출|해외\s*매출)$", re.I)
CH_DOM = re.compile(r"^(?:내\s*수|국\s*내(?:\s*\(연결\))?|국내\s*매출)$")


def export_split(text):
    """매출 절에서 수출 · 내수 머리 칸 바로 뒤 숫자(최신 기)를 더한다. 부문별 줄과 합계 줄이 둘 다 더해져도 비율은 같다.
    → {export, domestic, export_pct} (보고서 단위 그대로의 합) · 둘 다 0 이면 None."""
    sec = sections(text)["sales"]
    lines = [ln.strip() for ln in sec.split("\n") if ln.strip()]
    ex = dom = 0.0
    hit = False
    for i, ln in enumerate(lines[:-1]):
        kind = "ex" if CH_EX.match(ln) else "dom" if CH_DOM.match(ln) else None
        if not kind or not NUMCELL.match(lines[i + 1]):
            continue
        v = _num(lines[i + 1])
        if v is None or v < 0:
            continue
        hit = True
        if kind == "ex":
            ex += v
        else:
            dom += v
    # 수출 칸을 하나도 못 읽었으면 '수출 0%'라 하지 않는다(삼성전자 — 해외 매출 표의 꼴이 달라 내수만 잡혔다). 내수 칸이 없고 수출만 있으면 100%(영원무역)
    if not hit or ex <= 0:
        return None
    return {"export": ex, "domestic": dom, "export_pct": ex / (ex + dom) * 100, "src": "매출 절 수출 · 내수 칸"}


PLANT_HEAD = re.compile(r"생산\s*(?:설비|능력|법인|거점|공장)|공장\s*(?:현황|소재지)|소\s*재\s*지")


def plants_from(text):
    """원재료 · 생산설비 절에서 생산설비 소제목 뒤의 나라 · 지역만(원부자재 조달국 표는 그 앞이라 빠진다). 국내는 뺀다."""
    sec = sections(text)["materials"]
    lines = sec.split("\n")
    # 첫 줄은 절 제목('3. 원재료 및 생산설비')이라 건너뛴다 — 안 그러면 원부자재 조달국 표(대만 · 홍콩 · 미국)가 공장으로 잡힌다
    k = next((i for i, ln in enumerate(lines) if i > 0 and PLANT_HEAD.search(ln) and len(ln.strip()) < 60 and not HEAD_RE.match(ln)), None)
    if k is None:
        return []
    # 소제목 바로 뒤 표만 — 다음 소제목('다.' · '(2)')이나 마케팅 사무소 · 유통 법인 표가 나오면 끝(영원무역: 시애틀 · 도쿄 사무소는 공장이 아니다)
    STOP = re.compile(r"^\s*(?:[가-하]\s*\.|\(\s*\d+\s*\)|\d+\s*\.)\s|마케팅|사무소|오피스|연락|유통\s*법인|판매\s*법인")
    body = []
    for ln in lines[k + 1:]:
        if STOP.search(ln) and len(ln.strip()) < 60:
            break
        body.append(ln)
    return [r["name"] for r in regions("\n".join(body)) if r["name"] != "국내"][:4]


# ── 주가가 따라간 것 ─────────────────────────────────────────────────────────────────────────────
def _pearson(xs, ys):
    n = len(xs)
    if n < 6:
        return None
    mx, my = sum(xs) / n, sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    syy = sum((y - my) ** 2 for y in ys)
    if sxx <= 1e-10 or syy <= 1e-10:        # 변화가 늘 같은 열(복리 증가 · 상수)은 r 없음 — 부동소수 찌꺼기로 1.0 이 나오지 않게
        return None
    return sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / math.sqrt(sxx * syy)


def quarter_changes(series, lag=4):
    """{분기키 n: 값} → {n: 1년 변화}. 값이 양수면 로그 변화, 아니면(이익 · 적자 섞임) 차이를 절대값 중앙으로 나눈 것."""
    ks = sorted(k for k, v in series.items() if v is not None)
    pos = all(series[k] > 0 for k in ks)
    out = {}
    if not pos:
        base = sorted(abs(series[k]) for k in ks)
        scale = base[len(base) // 2] if base else 1
        scale = scale or 1
    for k in ks:
        p = series.get(k - lag)
        if p is None:
            continue
        v = series[k]
        if pos:
            out[k] = math.log(v / p)
        else:
            out[k] = (v - p) / scale
    return out


def followers(px_q, named, min_n=8, window=24):
    """px_q = {분기키: 분기 말 주가}, named = {이름: {분기키: 값}}. 둘 다 1년 변화로 바꾼 뒤 최근 window 분기에서 피어슨 r.
    r 는 '같이 움직였나'일 뿐 인과가 아니다 — 화면도 그렇게 적는다."""
    pxc = quarter_changes(px_q)
    out = []
    for name, ser in named.items():
        sc = quarter_changes(ser)
        ks = sorted(set(pxc) & set(sc))[-window:]
        if len(ks) < min_n:
            out.append({"name": name, "r": None, "n": len(ks)})
            continue
        r = _pearson([sc[k] for k in ks], [pxc[k] for k in ks])
        out.append({"name": name, "r": None if r is None else round(r, 2), "n": len(ks)})
    out.sort(key=lambda x: -(abs(x["r"]) if x["r"] is not None else -1))
    return out


# ── 호재 · 악재 판 ─────────────────────────────────────────────────────────────────────────────
def _row(factor, up, strength, basis, why, quote=None, note=None):
    """up: +1 오르면 호재 · −1 오르면 악재 · 0 양면. strength 1~3. basis: 공시 숫자 · 공시 문장 · 구조에서 추론."""
    return {"factor": factor, "up": up, "strength": max(1, min(3, strength)), "basis": basis, "why": why, "quote": quote, "note": note}


def drivers(export_pct=None, materials=None, fx_sens=None, risk=None, net_debt_ratio=None, backlog=None, regions_=None,
            product_index=None, competitors=None, customers=None, plants=None):
    """요인별 방향 — 규칙은 여기 적힌 대로이고 회사마다 숫자만 다르다.
    export_pct: 수출 비중 % · materials: [{item, pct}] · fx_sens: fx_sensitivity() · risk: risk_sentences() · net_debt_ratio: 순차입금 ÷ 매출(TTM, 비율)
    backlog: {value, ratio} · regions_: regions() · product_index: {name, chg12} 업종 수출물가 · competitors: 문장 목록 · customers: [{name, country, pct}] · plants: [나라]"""
    rows = []
    risk = risk or {}
    fxq = next((x["s"] for x in risk.get("fx", [])), None)
    sens = [x for x in (fx_sens or []) if x["kind"] == "fx"]
    # 원/달러
    if export_pct is not None:
        if export_pct >= 50:
            rows.append(_row("원/달러 환율 ↑ (원화 약세)", +1, 3 if export_pct >= 70 else 2, "공시 숫자",
                             "매출의 %d%%가 수출 — 달러로 받은 돈을 원화로 바꾸면 더 많아진다. 단, 수입 원재료 · 해외 공장 비용은 반대로 는다." % round(export_pct),
                             fxq, "주석 민감도 발췌 참고" if sens else None))
        elif export_pct <= 20:
            rows.append(_row("원/달러 환율 ↑ (원화 약세)", -1, 2, "공시 숫자",
                             "매출의 %d%%만 수출 — 수입 원재료 · 외화 부채가 있으면 비용 쪽이 더 커진다." % round(export_pct), fxq))
        else:
            rows.append(_row("원/달러 환율 ↑ (원화 약세)", 0, 1, "공시 숫자",
                             "수출 %d%% · 내수 %d%% — 수출 쪽 이익과 수입 원가가 맞선다. 주석의 민감도 숫자로 어느 쪽이 큰지 본다." % (round(export_pct), round(100 - export_pct)), fxq))
    elif fxq:
        rows.append(_row("원/달러 환율 ↑ (원화 약세)", 0, 1, "공시 문장", "수출 비중 숫자를 못 읽었다 — 회사가 위험관리 절에 적은 문장으로 본다.", fxq))
    # 금리
    if net_debt_ratio is not None:
        if net_debt_ratio > 0.15:
            rows.append(_row("금리 ↑", -1, 3 if net_debt_ratio > 0.5 else 2, "공시 숫자",
                             "순차입금이 연 매출의 %d%% — 금리가 오르면 이자비용이 늘어 이익을 깎는다." % round(net_debt_ratio * 100)))
        elif net_debt_ratio < -0.15:
            rows.append(_row("금리 ↑", +1, 1, "공시 숫자", "빚보다 현금이 연 매출의 %d%%만큼 많다 — 이자수익이 늘지만 본업보다 작다." % round(-net_debt_ratio * 100)))
        else:
            rows.append(_row("금리 ↑", 0, 1, "공시 숫자", "순차입금이 매출 대비 ±15% 안 — 금리는 이 회사 손익을 크게 흔들지 않는다 (고객의 경기 쪽 영향은 따로)."))
    rq = next((x["s"] for x in risk.get("rate", [])), None)
    if rq and not any(r["factor"] == "금리 ↑" for r in rows):
        rows.append(_row("금리 ↑", 0, 1, "공시 문장", "차입 구조 숫자를 못 읽었다 — 회사 문장으로 본다.", rq))
    # 원재료 — '기타' 줄은 뺀다
    for m in [x for x in (materials or []) if not OTHER_ITEM.match(x.get("item") or "")][:4]:
        nm = m.get("item") or ""
        cm = commodity_of(nm)
        lab = ("%s 가격 ↑" % cm) if cm else ("원재료 '%s' 가격 ↑" % nm[:18])
        pct = m.get("pct")
        strength = 3 if (pct or 0) >= 30 else 2 if (pct or 0) >= 10 else 1
        why = "주요 원재료" + (" (매입의 %d%%)" % round(pct) if pct else "") + " — 값이 오르면 원가가 올라 이익률이 깎인다. 제품값에 얼마나 빨리 옮기느냐가 관건."
        iq = next((x["s"] for x in risk.get("input", []) if (cm and re.search(COMMODITY[[c[0] for c in COMMODITY].index(cm)][1], x["s"], re.I)) or (nm[:4] and nm[:4] in x["s"])), None)
        rows.append(_row(lab, -1, strength, "공시 숫자" if pct else "공시 문장", why, iq))
    # 제품 가격(업종 수출물가)
    if product_index and product_index.get("chg12") is not None:
        rows.append(_row("제품 값 ↑ (업종 수출물가 지수)", +1, 2, "공시 밖 통계",
                         "%s 수출물가(한국은행) 최근 1년 %+.1f%% — 같은 업종 제품값이 오르면 매출 · 이익률이 먼저 움직인다. 이 회사 제품값과는 다를 수 있다." % (product_index.get("name", ""), product_index["chg12"])))
    # 수주
    if backlog and backlog.get("value"):
        rows.append(_row("수주 잔고 ↑", +1, 2, "공시 숫자",
                         "수주잔고 %s — 앞으로 매출이 될 주문. 잔고가 늘면 다음 분기 매출의 바닥이 올라간다." % backlog.get("text", "")))
    # 지역 · 교역
    tq = next((x["s"] for x in risk.get("trade", [])), None)
    regs = [r for r in (regions_ or []) if r["name"] != "국내"][:3]
    cust_c = {}
    for c in customers or []:
        if c.get("country") and c.get("pct"):
            cust_c[c["country"]] = cust_c.get(c["country"], 0) + c["pct"]
    if regs or cust_c:
        top = regs[0]["name"] if regs else max(cust_c, key=cust_c.get)
        rows.append(_row("%s 쪽 관세 · 규제 · 경기 악화" % top, -1, 2, "공시 문장",
                         "보고서에 가장 자주 적힌 해외 지역 — " + " · ".join("%s %d회" % (r["name"], r["n"]) for r in regs) +
                         ((" · 고객 비중 " + " · ".join("%s %d%%" % (k, round(v)) for k, v in sorted(cust_c.items(), key=lambda kv: -kv[1])[:3])) if cust_c else "") +
                         ". 그 지역의 관세 · 규제 · 경기가 이 회사 매출에 바로 닿는다.", tq))
    if plants:
        rows.append(_row("생산국(%s) 정치 · 임금 · 전력 불안" % " · ".join(plants[:3]), -1, 1, "공시 문장",
                         "공장이 있는 나라의 사정이 원가와 납기를 흔든다 — 해당 나라 뉴스가 이 회사 뉴스다."))
    # 경쟁
    cq = next((s for s in (competitors or []) if re.search(r"중국|가격\s*경쟁|저가", s)), None)
    if cq:
        rows.append(_row("경쟁사(특히 중국) 가격 인하", -1, 2, "공시 문장", "회사 스스로 가격 경쟁 위험을 적었다 — 경쟁사 증설 · 덤핑 뉴스가 악재 쪽.", cq))
    # 수요
    dq = next((x["s"] for x in risk.get("demand", [])), None)
    if dq:
        rows.append(_row("최종 수요(경기 · 소비) ↑", +1, 2, "공시 문장", "회사가 적은 수요 변수 — 경기 · 소비 지표가 이 회사 매출을 앞서 움직인다.", dq))
    return rows


def josa(word, a="은", b="는"):
    """받침 있으면 a(은 · 이 · 을), 없으면 b(는 · 가 · 를). 한글이 아니면 b."""
    ch = (word or "").rstrip()[-1:]
    if not ch or not ("가" <= ch <= "힣"):
        return b
    return a if (ord(ch) - 0xAC00) % 28 else b


def summary_line(name, segs, customers=None, export_pct=None, regions_=None, plants=None):
    """한 줄 — '{회사}는 {부문1}(비중)로 돈을 번다 · 주 고객 … · 수출 …%'. 숫자가 없으면 그 조각을 뺀다."""
    parts = []
    if segs:
        top = sorted(segs, key=lambda s: -s["pct"])[:3]
        parts.append(name + josa(name) + " " + " · ".join("%s %d%%" % (s["name"], round(s["pct"])) for s in top) + "로 매출을 올린다")
    else:
        parts.append(name + "의 매출 구성은 보고서 표를 못 읽었다 — 아래 개요 원문으로")
    if customers:
        cs = [c["name"] for c in customers if c.get("kind") == "named"][:3]
        if cs:
            parts.append("주요 고객 " + " · ".join(cs))
    if export_pct is not None:
        parts.append("수출 %d%%" % round(export_pct))
    if plants:
        parts.append("공장 " + " · ".join(plants[:3]))
    return ". ".join(parts) + "."
