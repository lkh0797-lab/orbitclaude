# -*- coding: utf-8 -*-
"""
수출 추적 — 관세청 시군구별 품목별 수출로 회사의 매출 흐름을 공시보다 먼저 읽는다.

1) 거점 — 최근 사업보고서에서 본사 주소와 공장 도시를 뽑아 관세청 시군구 이름에 맞춘다.
   관세청 시군구 통계는 '수출자(사업장) 등록 주소' 기준이다. 공장이 별도 사업장이면 공장(삼양식품 원주·밀양·익산),
   아니면 본사(HD현대일렉트릭 → 경기 성남시)로 잡힌다. 그래서 후보를 둘 다 두고, 실제로 수출이 찍히는 곳을 데이터로 고른다.
2) 품목 — 보고서의 제품 낱말을 HS 6단위로(HS_DICT). 확신하는 코드만 넣었다.
3) 통로 — (시군구 × HS) 가운데 수출이 찍히는 조합. 전국 품목 통계로 주 수출국과 단가(달러/kg)를 붙인다.
4) 검증 — 과거 분기 매출 증가율과 통관 수출 증가율의 상관, 통관 수출이 매출의 몇 %를 설명하나(근사 환율).
   믿을 만한 회사만 추정에 쓴다.
5) 신호 — 최근 3개월 수출 증가율(전년 같은 달 대비)과 그 직전 3개월, 가속, 아직 공시 안 된 분기의 부분 추정,
   단가 추세. 고성장 유지 · 가속 · 급감 변곡 · 감소 지속.

금액은 시군구 통계 기준 천 달러(expUsdAmt). 환율은 연평균 근사치(USDKRW)로만 '매출 대비 비중'에 쓴다.
"""
import os
import re
import json
import math
import datetime as dt
import statistics as st

import 관세청 as K

BASE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(BASE, ".cache", "수출추적")
SGG_PATH = os.path.join(BASE, ".cache", "관세청", "_시군구이름.json")
VER = 1

SIDO = {"서울특별시": "11", "서울시": "11", "서울": "11", "부산광역시": "26", "부산": "26", "대구광역시": "27", "대구": "27",
        "인천광역시": "28", "인천": "28", "광주광역시": "29", "대전광역시": "30", "대전": "30", "울산광역시": "31", "울산": "31",
        "세종특별자치시": "36", "세종": "36", "경기도": "41", "경기": "41", "강원특별자치도": "51", "강원도": "51", "강원": "51",
        "충청북도": "43", "충북": "43", "충청남도": "44", "충남": "44", "전북특별자치도": "52", "전라북도": "52", "전북": "52",
        "전라남도": "46", "전남": "46", "경상북도": "47", "경북": "47", "경상남도": "48", "경남": "48",
        "제주특별자치도": "50", "제주도": "50", "제주": "50"}
# 연평균 원/달러(근사) — '통관 수출이 매출의 몇 %인가'를 어림할 때만 쓴다
USDKRW = {2021: 1144, 2022: 1292, 2023: 1306, 2024: 1364, 2025: 1420, 2026: 1440}

# 제품 낱말 → HS 6단위. 확신하는 코드만. (낱말 정규식, 이름, [HS6])
HS_DICT = [
    (r"변압기", "변압기", ["850421", "850422", "850423", "850432", "850433", "850434"]),
    (r"차단기|개폐기|가스절연|GIS", "차단기·개폐장치", ["853521", "853529", "853530", "853620"]),
    (r"배전반|수배전반|분전반", "배전반", ["853710", "853720"]),
    (r"전력\s*케이블|초고압\s*케이블|해저\s*케이블|전력선|전선(?!\s*(?:에서|을\s*넘))|권선", "전선·케이블", ["854449", "854460"]),
    (r"광케이블|광섬유", "광케이블", ["854470"]),
    (r"발전기", "발전기", ["850164"]),
    (r"가스\s*터빈", "가스터빈", ["841182", "841181"]),
    (r"보일러", "보일러", ["840211", "840212", "840219"]),
    (r"인버터|정류기|전력변환", "전력변환장치", ["850440"]),
    (r"LNG\s*운반선|컨테이너선|유조선|탱커|벌크선|상선|선박\s*건조|조선", "선박", ["890190", "890120", "890110"]),
    (r"해양\s*플랜트|시추선|FPSO|부유식", "해양설비", ["890520", "890590"]),
    (r"선박\s*엔진|선박용\s*엔진|디젤\s*엔진|힘센\s*엔진|이중연료\s*엔진", "선박엔진", ["840810", "840999"]),
    (r"반도체\s*(?:제조\s*)?장비|본딩\s*장비|증착\s*장비|식각\s*장비|세정\s*장비|TC\s*본더|디스플레이\s*장비", "반도체·디스플레이 장비", ["848620", "848630", "848690"]),
    (r"검사\s*장비|계측\s*장비|프로브\s*카드", "반도체 검사장비", ["903082", "903141"]),
    (r"DRAM|디램|낸드|NAND|메모리\s*반도체", "메모리 반도체", ["854232"]),
    (r"MLCC|적층\s*세라믹", "MLCC", ["853224"]),
    (r"인쇄\s*회로\s*기판|PCB|FC-?BGA|패키지\s*기판", "인쇄회로기판", ["853400"]),
    (r"OLED\s*패널|LCD\s*패널|디스플레이\s*패널", "디스플레이 패널", ["852411", "852412", "852491", "852492"]),
    (r"이차\s*전지|2차\s*전지|리튬\s*이온|배터리\s*셀", "2차전지", ["850760"]),
    (r"양극재|양극\s*활물질", "양극재", ["284190"]),
    (r"동박|전지박", "동박", ["741011"]),
    (r"화장품|스킨\s*케어|기초\s*화장|색조|선크림|마스크\s*팩", "화장품", ["330499", "330420", "330410", "330491"]),
    (r"라면|봉지면|용기면", "라면", ["190230"]),
    (r"과자|스낵|비스킷|초코파이", "과자", ["190590", "190532"]),
    (r"소주|증류주", "소주", ["220890"]),
    (r"맥주", "맥주", ["220300"]),
    (r"커피\s*믹스", "커피믹스", ["210112"]),
    (r"담배|궐련", "담배", ["240220"]),
    (r"사료", "사료", ["230910"]),
    (r"완제\s*의약품|전문\s*의약품|일반\s*의약품|개량\s*신약", "완제의약품", ["300490"]),
    (r"바이오\s*시밀러|항체|바이오\s*의약품", "바이오의약품", ["300215"]),
    (r"백신", "백신", ["300241"]),
    (r"톡신|보툴리눔|보톨리눔", "보툴리눔 톡신", ["300249"]),
    (r"임플란트", "치과 임플란트", ["902129"]),
    (r"엑스레이|X-ray|영상\s*진단|디텍터", "X선 기기", ["902214"]),
    (r"콘택트\s*렌즈|컬러\s*렌즈", "콘택트렌즈", ["900130"]),
    (r"자동차\s*부품|차량\s*부품|변속기|제동장치|조향장치|현가장치", "자동차부품", ["870899", "870840", "870830", "870880", "870894"]),
    (r"타이어", "타이어", ["401110", "401120"]),
    (r"굴착기|굴삭기", "굴착기", ["842952"]),
    (r"지게차", "지게차", ["842720"]),
    (r"산업용\s*로봇|협동\s*로봇", "로봇", ["847950"]),
    (r"공작\s*기계|머시닝\s*센터|CNC\s*선반", "공작기계", ["845811", "845710"]),
    (r"강관|라인\s*파이프|유정관|OCTG", "강관", ["730511", "730519", "730630", "730429"]),
    (r"태양광\s*모듈|태양\s*전지", "태양광 모듈", ["854143"]),
    (r"풍력\s*타워|풍력\s*발전\s*타워", "풍력타워", ["730820"]),
    (r"전차|장갑차|K2|K9|자주포", "전차·자주포", ["871000", "930110"]),
    (r"탄약|포탄", "탄약", ["930690"]),
    (r"항공기\s*부품|기체\s*부품|항공\s*기체", "항공기 부품", ["880730"]),
    (r"엘리베이터|승강기", "엘리베이터", ["842810"]),
]


# 제품 ↔ 업종 — 같은 동네 남의 수출이 우연히 매출과 같이 움직여 끌려오는 것을 막는다(인바디→강관, 현대오토에버→자동차부품,
# 흥아해운→선박, 신세계→화장품). 업종을 모르면(빈 값) 거르지 않는다. 업종 이름은 서버 sector_map 의 industry.
_EL = ["전기장비", "전기제품", "전자장비와기기", "기계", "복합기업", "건설", "에너지장비및서비스"]
_SEMI = ["반도체와반도체장비", "디스플레이장비및부품", "전자장비와기기", "기계", "핸드셋"]
_PH = ["제약", "생물공학", "건강관리장비와용품", "건강관리업체및서비스", "생명과학도구및서비스"]
_FOOD = ["식품", "음료"]
_SHIP = ["조선", "기계", "복합기업", "우주항공과국방"]
_BAT = ["전기장비", "전기제품", "전자장비와기기", "화학", "비철금속", "반도체와반도체장비", "핸드셋", "에너지장비및서비스", "복합기업"]
INDUSTRY_OK = {
    "변압기": _EL, "차단기·개폐장치": _EL, "배전반": _EL, "전력변환장치": _EL + ["반도체와반도체장비", "디스플레이장비및부품"],
    "발전기": _EL + ["조선"], "가스터빈": _EL + ["우주항공과국방", "조선"], "보일러": _EL,
    "전선·케이블": ["전기장비", "전기제품", "전자장비와기기", "통신장비", "비철금속", "복합기업"],
    "광케이블": ["통신장비", "전기장비", "전기제품", "전자장비와기기", "복합기업"],
    "선박": _SHIP, "해양설비": _SHIP, "선박엔진": _SHIP,
    "반도체·디스플레이 장비": _SEMI, "반도체 검사장비": _SEMI, "메모리 반도체": ["반도체와반도체장비", "전자장비와기기", "핸드셋"],
    "MLCC": ["전자장비와기기", "핸드셋", "반도체와반도체장비", "전기제품"],
    "인쇄회로기판": ["전자장비와기기", "반도체와반도체장비", "핸드셋", "디스플레이장비및부품", "비철금속", "복합기업"],
    "디스플레이 패널": ["디스플레이장비및부품", "전자장비와기기", "반도체와반도체장비", "핸드셋"],
    "2차전지": _BAT, "양극재": _BAT, "동박": _BAT,
    "화장품": ["화장품", "가정용기기와용품", "섬유,의류,신발,호화품", "화학", "복합기업"] + _PH,
    "라면": _FOOD, "과자": _FOOD, "소주": _FOOD, "맥주": _FOOD, "커피믹스": _FOOD, "담배": ["담배"], "사료": _FOOD + ["복합기업"],
    "완제의약품": _PH, "바이오의약품": _PH, "백신": _PH, "보툴리눔 톡신": _PH,
    "치과 임플란트": ["건강관리장비와용품", "제약", "건강관리업체및서비스"], "X선 기기": ["건강관리장비와용품", "전자장비와기기", "반도체와반도체장비"],
    "콘택트렌즈": ["건강관리장비와용품"],
    "자동차부품": ["자동차부품", "기계", "전기제품", "전자장비와기기", "복합기업", "철강"], "타이어": ["자동차부품"],
    "굴착기": ["기계", "복합기업"], "지게차": ["기계", "복합기업"], "로봇": ["기계", "전자장비와기기", "반도체와반도체장비", "전기제품"],
    "공작기계": ["기계", "복합기업"], "강관": ["철강", "건축자재", "복합기업", "비철금속"],
    "태양광 모듈": ["전기장비", "전기제품", "반도체와반도체장비", "에너지장비및서비스", "화학", "복합기업"],
    "풍력타워": ["에너지장비및서비스", "기계", "전기장비", "철강"],
    "전차·자주포": ["우주항공과국방", "기계", "복합기업"], "탄약": ["우주항공과국방", "화학", "복합기업"],
    "항공기 부품": ["우주항공과국방", "기계"], "엘리베이터": ["기계", "건설"],
}


def industry_ok(product, industry):
    ok = INDUSTRY_OK.get(product)
    return (not industry) or (not ok) or industry in ok


def _sgg():
    with open(SGG_PATH, "r", encoding="utf-8") as fh:
        return json.load(fh)


def _norm_addr(addr):
    """'경기도 성남시 분당구 …' → ('41', '경기도 성남시'). 관세청 이름표에 없으면 None."""
    S = _sgg()
    a = re.sub(r"\s+", " ", addr or "").strip()
    m = re.match(r"([가-힣]+(?:특별시|광역시|특별자치시|특별자치도|도|시)?)\s*([가-힣]+(?:시|군|구))?\s*([가-힣]+구)?", a)
    if not m:
        return None
    sd = SIDO.get(m.group(1)) or SIDO.get(m.group(1)[:2])
    if not sd or sd not in S:
        return None
    names = S[sd]
    for part in (m.group(2), m.group(3)):
        if not part:
            continue
        hit = next((n for n in names if n.endswith(" " + part)), None)
        if hit:
            return sd, hit
    return None


def _base_names():
    """'원주' → ('51', '강원특별자치도 원주시'). 여러 시도에 같은 이름(중구·동구…)이 있으면 넣지 않는다."""
    S = _sgg()
    cnt, out = {}, {}
    for sd, names in S.items():
        for n in names:
            last = n.split(" ")[-1]
            base = re.sub(r"(시|군|구)$", "", last)
            for k in {last, base} if len(base) >= 2 else {last}:
                cnt[k] = cnt.get(k, 0) + 1
                out[k] = (sd, n)
    return {k: v for k, v in out.items() if cnt[k] == 1 and k not in ("중", "동", "서", "남", "북")}


ADDR_RX = re.compile(r"((?:서울|부산|대구|인천|광주|대전|울산|세종|경기|강원|충청북|충청남|충북|충남|전라북|전라남|전북|전남|경상북|경상남|경북|경남|제주)"
                     r"[가-힣]*(?:특별시|광역시|특별자치시|특별자치도|도|시)?\s+[가-힣]+(?:시|군|구)(?:\s+[가-힣]+구)?)")
PLANT_RX = re.compile(r"공장|사업장|생산\s*(?:기지|라인|거점|시설)|제조\s*(?:시설|공장)|캠퍼스|조선소|야드")
EXPORT_SHARE_RX = [
    re.compile(r"수출\s*비중(?:은|이|은\s*약|이\s*약)?\s*([\d.]+)\s*%"),
    re.compile(r"(?:해외|수출)\s*(?:매출|판매)\s*(?:비중|비율)(?:은|이)?\s*(?:약\s*)?([\d.]+)\s*%"),
    re.compile(r"매출(?:액)?\s*(?:중|의)\s*(?:약\s*)?([\d.]+)\s*%\s*(?:가|를|이)?\s*(?:해외|수출)"),
]
COUNTRY = ["미국", "중국", "일본", "베트남", "인도", "유럽", "독일", "영국", "프랑스", "중동", "사우디", "아랍에미리트", "UAE",
           "멕시코", "캐나다", "호주", "대만", "동남아", "인도네시아", "태국", "브라질", "튀르키예", "폴란드", "러시아"]


def profile(S, c):
    """보고서 한 곳의 수출 프로필 — 본사 · 공장 후보 · 품목(HS) · 수출 비중 · 언급 국가."""
    reps = [r for r in c["reports"] if r["label"] == "사업보고서" and not r["tag"]] or [r for r in c["reports"] if not r["tag"]]
    if not reps:
        return None
    r = reps[-1]
    txt = {}
    for norm in ("회사의 개요", "사업의 내용"):
        sec = next((s for s in r["sections"] if s["norm"] == norm), None)
        txt[norm] = S.read_section(c, r, sec["file"]) if sec else ""
    over, biz = txt["회사의 개요"], txt["사업의 내용"]
    out = {"code": c["code"], "name": c["name"], "report": r["stamp"] + " " + r["label"], "rcept": r["rcept"],
           "hq": None, "plants": [], "products": [], "export_share": None, "countries": []}
    m = re.search(r"(?:본사의\s*주소|본점의\s*소재지|본점\s*소재지)[^가-힣]{0,40}(?:주\s*소\s*[|:]?\s*)?", over)
    if m:
        am = ADDR_RX.search(over[m.end():m.end() + 160])
        if am:
            hq = _norm_addr(am.group(1))
            if hq:
                out["hq"] = {"sido": hq[0], "sgg": hq[1], "text": am.group(1)}
    seen = set()
    # 공장 — 주소 꼴 그대로, 또는 공장·사업장 문장 속 도시 이름
    for am in ADDR_RX.finditer(biz):
        ctx = biz[max(0, am.start() - 80):am.end() + 40]
        if not PLANT_RX.search(ctx):
            continue
        p = _norm_addr(am.group(1))
        if p and p[1] not in seen:
            seen.add(p[1])
            out["plants"].append({"sido": p[0], "sgg": p[1], "how": "주소"})
    base = _base_names()
    for sm in re.finditer(r"[^.|\n]{0,120}(?:공장|사업장|조선소|야드|캠퍼스|생산\s*(?:기지|거점|라인|시설))[^.|\n]{0,80}", biz + "\n" + over):
        sent = sm.group(0)
        for k, (sd, n) in base.items():
            if n in seen or len(k) < 2:
                continue
            if re.search(r"(?<![가-힣])" + re.escape(k) + r"(?:시|군|공장|사업장|\s*공장|\s*사업장|,|\)|\s|·|ㆍ)", sent):
                seen.add(n)
                out["plants"].append({"sido": sd, "sgg": n, "how": "공장 문장"})
    body = biz[:30000]
    for rx, nm, hs in HS_DICT:
        hits = len(re.findall(rx, body))
        if hits:
            out["products"].append({"name": nm, "hs": hs, "hits": hits})
    out["products"].sort(key=lambda p: -p["hits"])
    for rx in EXPORT_SHARE_RX:
        mm = rx.search(biz)
        if mm:
            try:
                v = float(mm.group(1))
                if 0 < v <= 100:
                    out["export_share"] = v
                    break
            except ValueError:
                pass
    cc = [(k, len(re.findall(k, biz))) for k in COUNTRY]
    out["countries"] = [k for k, n in sorted(cc, key=lambda x: -x[1]) if n >= 2][:6]
    return out


# ---------------------------------------------------------------- 통관 시계열
def _ym(d):
    return d.strftime("%Y%m")


def _months_back(n):
    t = dt.date.today().replace(day=1)
    y, m = t.year, t.month - n
    while m <= 0:
        y, m = y - 1, m + 12
    return "%04d%02d" % (y, m)


def channels(prof, start=None, end=None, min_kusd=500):
    """(시군구 × HS6) 가운데 이 회사 후보 주소에서 수출이 찍히는 조합과 월별 값(천 달러)."""
    start = start or "202201"
    end = end or _months_back(1)
    cand = {}
    for p in ([prof["hq"]] if prof.get("hq") else []) + prof.get("plants", []):
        cand.setdefault(p["sido"], set()).add(p["sgg"])
    hs_all, seen_h = [], set()
    for p in prof.get("products", [])[:4]:
        for h in p["hs"]:
            if h not in seen_h:
                seen_h.add(h)
                hs_all.append((h, p["name"]))
    out = []
    for sd, sggs in cand.items():
        for h, nm in hs_all:
            try:
                rows = K.시군구품목별(start, end, h, sd)
            except K.관세청오류:
                continue
            for sg in sggs:
                mon = {}
                for x in rows:
                    if x.get("sggNm") == sg:
                        ym = (x.get("priodTitle") or "").replace(".", "")
                        mon[ym] = mon.get(ym, 0) + (x.get("expUsdAmt") or 0)
                tot = sum(mon.values())
                if tot >= min_kusd:
                    out.append({"sido": sd, "sgg": sg, "hs": h, "item": nm, "hsName": next((x.get("korePrlstNm") for x in rows if x.get("hsSgn") == h), ""),
                                "months": dict(sorted(mon.items())), "total": tot})
    out.sort(key=lambda c: -c["total"])
    return out


def national(hs, months=24):
    """전국 품목 통계 — 최근 months 개월 주 수출국(금액 순)과 월별 단가(달러/kg)."""
    end = _months_back(1)
    start = _months_back(months)
    try:
        rows = K.품목국가별(start, end, hs=hs)
    except K.관세청오류:
        return None
    mon, cty = {}, {}
    for x in rows:
        if x.get("statCd") in ("-", None) or x.get("hsCd") == "-":
            continue
        ym = (x.get("year") or "").replace(".", "")
        m = mon.setdefault(ym, [0.0, 0.0])
        m[0] += x.get("expDlr") or 0
        m[1] += x.get("expWgt") or 0
        cty[x.get("statCdCntnKor1")] = cty.get(x.get("statCdCntnKor1"), 0) + (x.get("expDlr") or 0)
    tot = sum(cty.values()) or 1
    return {"hs": hs, "unit": {k: (v[0] / v[1] if v[1] else None) for k, v in sorted(mon.items())},
            "value": {k: v[0] for k, v in sorted(mon.items())},
            "top": [(k, v / tot * 100) for k, v in sorted(cty.items(), key=lambda kv: -kv[1])[:6]]}


# ---------------------------------------------------------------- 검증 · 신호
def _q_of(ym):
    return ym[:4] + "Q%d" % ((int(ym[4:]) - 1) // 3 + 1)


def _corr(a, b):
    p = [(x, y) for x, y in zip(a, b) if x is not None and y is not None]
    if len(p) < 6:
        return None
    xs, ys = zip(*p)
    mx, my = sum(xs) / len(xs), sum(ys) / len(ys)
    num = sum((x - mx) * (y - my) for x, y in p)
    den = math.sqrt(sum((x - mx) ** 2 for x in xs) * sum((y - my) ** 2 for y in ys))
    return num / den if den else None


def validate(S, c, mon):
    """분기 매출 YoY vs 통관 수출 YoY 상관, 통관 수출이 매출의 몇 %(근사 환율)."""
    corp = S.corp_code_of(c["code"])
    try:
        pts = S.DRK.series(corp, c["code"], list(range(2021, dt.date.today().year + 1)))
    except Exception:
        pts = []
    rev = {"%dQ%d" % (p["year"], p["q"]): p.get("매출액") for p in pts if p.get("매출액")}
    qx = {}
    for ym, v in mon.items():
        qx[_q_of(ym)] = qx.get(_q_of(ym), 0) + v
    full = {q: v for q, v in qx.items() if sum(1 for ym in mon if _q_of(ym) == q) == 3}

    def yoy(d, q):
        p = "%dQ%s" % (int(q[:4]) - 1, q[5])
        return (d[q] / d[p] - 1) * 100 if (q in d and p in d and d[p] > 0) else None
    qs = sorted(set(rev) & set(full))
    a = [yoy(full, q) for q in qs]
    b = [yoy(rev, q) for q in qs]
    r = _corr(a, b)
    cov = []
    for q in qs[-4:]:
        fx = USDKRW.get(int(q[:4]), 1400)
        if rev.get(q):
            cov.append(full[q] * 1000 * fx / rev[q] * 100)
    return {"corr": r, "n": sum(1 for x, y in zip(a, b) if x is not None and y is not None),
            "coverage": st.median(cov) if cov else None,
            "pairs": [{"q": q, "x": x, "r": y} for q, x, y in zip(qs, a, b)][-12:],
            "last_rev_q": max(rev) if rev else None}


def signals(mon):
    """월별 수출(천 달러) → 최근 3개월·직전 3개월 증가율(전년 같은 달 대비), 가속, 12개월, 상태."""
    ks = sorted(mon)
    if len(ks) < 15:
        return None
    last = ks[-1]

    def shift(ym, n):
        y, m = int(ym[:4]), int(ym[4:]) - n
        while m <= 0:
            y, m = y - 1, m + 12
        return "%04d%02d" % (y, m)

    def win(end, n):
        return [shift(end, i) for i in range(n)]

    def yoy(end, n):
        cur = sum(mon.get(k, 0) for k in win(end, n))
        ly = sum(mon.get(shift(k, 12), 0) for k in win(end, n))
        return (cur / ly - 1) * 100 if ly > 0 else None
    y3, y3p, y12 = yoy(last, 3), yoy(shift(last, 3), 3), yoy(last, 12)
    y1 = yoy(last, 1)
    acc = (y3 - y3p) if (y3 is not None and y3p is not None) else None
    state = "보합"
    if y3 is not None:
        if acc is not None and acc <= -25 and y3 < 5:
            state = "급감 변곡"
        elif acc is not None and acc <= -25:
            state = "꺾임"
        elif y3 >= 20 and (y3p or 0) >= 20:
            state = "고성장 유지"
        elif acc is not None and acc >= 15 and y3 >= 10:
            state = "가속"
        elif y3 <= -10 and (y3p or 0) <= -10:
            state = "감소 지속"
        elif y3 <= -10:
            state = "감소 전환"
    return {"last": last, "y1": y1, "y3": y3, "y3p": y3p, "acc": acc, "y12": y12, "state": state,
            "m3": sum(mon.get(k, 0) for k in win(last, 3))}


def unit_trend(nat):
    """전국 단가(달러/kg) 최근 6개월 vs 전년 같은 6개월."""
    if not nat or not nat.get("unit"):
        return None
    ks = sorted(k for k, v in nat["unit"].items() if v)
    if len(ks) < 18:
        return None
    cur = ks[-6:]
    v = nat["value"]
    w = {k: (v[k] / nat["unit"][k]) for k in ks}           # 중량
    c = sum(v[k] for k in cur) / max(1e-9, sum(w[k] for k in cur))
    prev = ["%04d%02d" % (int(k[:4]) - 1, int(k[4:])) for k in cur]
    if not all(p in w for p in prev):
        return None
    p = sum(v[k] for k in prev) / max(1e-9, sum(w[k] for k in prev))
    return (c / p - 1) * 100 if p else None


# ---------------------------------------------------------------- 전체 실행
def _spans():
    """1단계(거르기) 한 해와 2단계(앞뒤) 기간 — 해가 바뀌면 같이 넘어간다.
    지난달이 2026년 8월이면 1단계 2025년, 2단계 2023 · 2024 · 2026.1~8월."""
    end = _months_back(1)
    y = int(end[:4])
    probe = ("%d01" % (y - 1), "%d12" % (y - 1))
    hist = [("%d01" % (y - 3), "%d12" % (y - 3)), ("%d01" % (y - 2), "%d12" % (y - 2)), ("%d01" % y, end)]
    return probe, hist


def _long_spans():
    """차트 팝업용 앞 기간 — 최근 5년 증가율(전년 대비)을 그리려면 6년 전 7월부터 필요. 2026년이면 2020 · 2021 · 2022.
    검증 · 신호 · 통로 순위에는 안 쓴다(그쪽은 _spans 기간 그대로)."""
    y = int(_months_back(1)[:4])
    return [("%d01" % yy, "%d12" % yy) for yy in (y - 6, y - 5, y - 4)]


class 한도초과(RuntimeError):
    pass


def _rows(sd, h, a, b):
    try:
        return K.시군구품목별(a, b, h, sd)
    except K.관세청오류 as e:
        # 하루 한도(개발계정 1만 건)를 넘으면 '수출 없음'으로 넘기지 말고 멈춘다 — 다음 날 이어 달린다(응답은 캐시)
        if "LIMITED" in str(e) or "게이트웨이 22" in str(e) or "HTTP 429" in str(e):
            raise 한도초과(str(e))
        return []


def _channels_fast(prof, min_kusd=300):
    """두 단계로 통로를 찾는다 — 2025년 한 해로 거르고, 남은 조합만 2023·2024·2026을 더 부른다."""
    cand = {}
    for p in ([prof["hq"]] if prof.get("hq") else []) + prof.get("plants", []):
        cand.setdefault(p["sido"], set()).add(p["sgg"])
    # 부수 품목은 뺀다 — 가장 많이 언급된 제품의 4분의 1(최소 5번) 넘게 나온 것만(한미반도체의 '기판' 4번 같은 것)
    top = max([x["hits"] for x in prof.get("products", [])] or [0])
    prods = [x for x in prof.get("products", []) if x["hits"] >= max(5, top * 0.25)][:3]
    hs_all, seen = [], set()
    for p in prods:
        for h in p["hs"]:
            if h not in seen:
                seen.add(h)
                hs_all.append((h, p["name"]))
    probe, hist = _spans()
    keep = []
    for sd, sggs in cand.items():
        for h, nm in hs_all:
            rows = _rows(sd, h, *probe)
            for sg in sggs:
                tot = sum(x.get("expUsdAmt") or 0 for x in rows if x.get("sggNm") == sg)
                if tot >= min_kusd:
                    keep.append((sd, sg, h, nm, rows))
    start = hist[0][0]
    out = []
    for sd, sg, h, nm, rows in keep:
        allrows = list(rows)
        for a, b in hist + _long_spans():
            allrows += _rows(sd, h, a, b)
        mon = {}
        for x in allrows:
            if x.get("sggNm") == sg:
                ym = (x.get("priodTitle") or "").replace(".", "")
                if ym.isdigit():
                    mon[ym] = mon.get(ym, 0) + (x.get("expUsdAmt") or 0)
        cur = {k: v for k, v in mon.items() if k >= start}
        out.append({"sido": sd, "sgg": sg, "hs": h, "item": nm,
                    "hsName": next((x.get("korePrlstNm") for x in rows if x.get("hsSgn") == h and x.get("korePrlstNm")), ""),
                    "months": dict(sorted(cur.items())), "months_long": dict(sorted(mon.items())), "total": sum(cur.values())})
    out.sort(key=lambda c: -c["total"])
    return out


MIN_COVER = 5.0     # 통관 수출이 연결 매출의 5%도 안 되면 매출 추론에 쓸 수 없다(같은 동네 남의 수출일 가능성도 크다)
MAX_COVER = 150.0   # 통관 수출이 매출보다 한참 크면 같은 주소·품목의 다른 회사 수출이 섞였다(ISC 안산 인쇄회로기판 923%)


def _grade(v):
    r, n = v.get("corr"), v.get("n") or 0
    if r is None or n < 6 or v.get("coverage") is None or not (MIN_COVER <= v["coverage"] <= MAX_COVER):
        return "C"
    return "A" if (r >= 0.6 and n >= 8) else "B" if r >= 0.3 else "C"


def _partial(mon, last_rev_q):
    """마지막으로 공시된 분기 뒤의 달들 — 아직 보고서에 안 나온 매출의 단서."""
    if not last_rev_q:
        return None
    y, q = int(last_rev_q[:4]), int(last_rev_q[5])
    after = sorted(k for k in mon if (int(k[:4]), (int(k[4:]) - 1) // 3 + 1) > (y, q))
    if not after:
        return None
    cur = sum(mon[k] for k in after)
    ly = sum(mon.get("%04d%s" % (int(k[:4]) - 1, k[4:]), 0) for k in after)
    return {"months": after, "yoy": (cur / ly - 1) * 100 if ly > 0 else None}


def build_one(S, c, prof=None):
    prof = prof or profile(S, c)
    if not prof:
        return None
    ch = _channels_fast(prof)
    if not ch:
        return {"code": c["code"], "name": c["name"], "profile": prof, "channels": [], "status": "통로 없음"}
    mon, mon_long = {}, {}
    for x in ch:
        for k, v in x["months"].items():
            mon[k] = mon.get(k, 0) + v
        for k, v in x.get("months_long", x["months"]).items():
            mon_long[k] = mon_long.get(k, 0) + v
    v = validate(S, c, mon)
    sg = signals(mon)
    # 전국 품목 — 이 회사 통로 가운데 금액이 큰 HS 둘의 주 수출국과 단가
    by_hs = {}
    for x in ch:
        by_hs[x["hs"]] = by_hs.get(x["hs"], 0) + x["total"]
    nat = []
    for h, _ in sorted(by_hs.items(), key=lambda kv: -kv[1])[:2]:
        n = national(h)
        if n:
            nat.append({"hs": h, "top": n["top"][:4], "unit_yoy": unit_trend(n),
                        "name": next((x["hsName"] for x in ch if x["hs"] == h), "")})
    last12 = sorted(mon)[-12:]
    tot12 = sum(mon[k] for k in last12) or 1
    chs = []
    for x in ch[:8]:
        t12 = sum(x["months"].get(k, 0) for k in last12)
        chs.append({k: x[k] for k in ("sido", "sgg", "hs", "item", "hsName")} | {"t12": t12, "share": t12 / tot12 * 100})
    cov = v.get("coverage")
    implied = (sg["y3"] * min(cov, 100) / 100) if (sg and sg.get("y3") is not None and cov) else None
    return {"code": c["code"], "name": c["name"], "status": "ok",
            "profile": {k: prof.get(k) for k in ("report", "hq", "plants", "export_share", "countries")}
                       | {"products": [p["name"] for p in prof.get("products", []) if p["hits"] >= 2][:4]},
            "channels": chs, "series": dict(sorted(mon.items())), "series_long": dict(sorted(mon_long.items())), "validation": v, "grade": _grade(v),
            "signals": sg, "partial": _partial(mon, v.get("last_rev_q")), "national": nat, "implied": implied}


def build_all(S, codes=None, progress=print, out_name="result.json", on_step=None):
    """전 종목(또는 codes) — 결과는 .cache/수출추적/result.json. 관세청 응답은 관세청.py 캐시를 함께 쓴다."""
    os.makedirs(CACHE, exist_ok=True)
    out_path = os.path.join(CACHE, out_name)
    prev = {}
    if os.path.exists(out_path):
        try:
            prev = {x["code"]: x for x in json.load(open(out_path, encoding="utf-8")).get("items", [])}
        except Exception:
            prev = {}
    comps = [c for c in S.INDEX.get("companies", []) if c.get("code") and (not codes or c["code"] in codes)]
    smap = (S.sector_map() or {}).get("stocks", {})
    items = []
    stopped = None
    for i, c in enumerate(comps, 1):
        if on_step:
            on_step(i, len(comps), sum(1 for x in items if x.get("channels")))
        try:
            p = profile(S, c)
            if p:
                ind = (smap.get(c["code"].upper(), {}) or {}).get("industry") or ""
                p["industry"] = ind
                p["products"] = [x for x in p["products"] if industry_ok(x["name"], ind)]
            if not p or not [x for x in p["products"] if x["hits"] >= 2] or not (p["hq"] or p["plants"]):
                continue
            r = build_one(S, c, p)
            if r:
                items.append(r)
        except 한도초과 as e:
            stopped = "관세청 하루 한도 — %d/%d에서 멈춤, 내일 다시 돌리면 이어서(이미 부른 응답은 캐시)" % (i, len(comps))
            progress("  " + stopped)
            break
        except Exception as e:
            progress("  %s 실패: %s" % (c.get("code"), e))
        if i % 20 == 0:
            progress("  %d/%d · 통로 있는 회사 %d" % (i, len(comps), sum(1 for x in items if x.get("channels"))))
            json.dump({"at": dt.datetime.now().isoformat(timespec="minutes"), "v": VER, "items": items, "partial": True},
                      open(out_path, "w", encoding="utf-8"), ensure_ascii=False)
    done = {"at": dt.datetime.now().isoformat(timespec="minutes"), "v": VER, "items": items}
    done["month"] = data_month(done)
    if stopped:
        done.update(partial=True, stopped=stopped)
    json.dump(done, open(out_path, "w", encoding="utf-8"), ensure_ascii=False)
    return items


# ---------------------------------------------------------------- 매달 자동 갱신
# 관세청은 매달 15일께 지난달 치를 낸다. 서버(서버.py _exp_tick)가 몇 시간마다 '지난달 치가 나왔나'를
# 큰 통로 몇 개로 떠보고, 나왔으면 이 파일을 '갱신'으로 따로 띄운다. 새 결과는 result.new.json 에 쓰고
# 끝까지 가야 result.json 과 바꾼다 — 도는 동안 화면은 지난 결과 그대로.
PROG_PATH = os.path.join(CACHE, "progress.json")


def data_month(d):
    """결과가 담은 마지막 통관 달('YYYYMM')."""
    if d.get("month"):
        return d["month"]
    ks = [(x.get("signals") or {}).get("last") for x in d.get("items", [])]
    ks = [k for k in ks if k]
    return max(ks) if ks else None


def probe_targets(d, n=3):
    """믿을 만한 회사의 가장 큰 통로(시도 × HS) 몇 개 — 어느 달이든 수출이 0일 일이 없는 곳."""
    best = {}
    for x in d.get("items", []):
        if x.get("grade") not in ("A", "B"):
            continue
        for ch in (x.get("channels") or [])[:1]:
            k = (ch["sido"], ch["hs"])
            best[k] = max(best.get(k, 0), ch.get("t12") or 0)
    out = [k for k, _ in sorted(best.items(), key=lambda kv: -kv[1])[:n]]
    return out or [("44", "854232"), ("41", "854232")]       # 결과가 없으면 충남·경기 메모리 반도체


def available(ym, probes):
    """ym 달 시군구 통계가 나왔나 — 떠보는 통로 가운데 하나라도 그 달 금액이 찍히면 나온 것(응답 30분 캐시)."""
    for sd, h in probes:
        try:
            rows = K._get("시군구품목별", {"strtYymm": ym, "endYymm": ym, "HsSgn": h, "sidoCd": sd}, 1800)
        except K.관세청오류:
            continue
        if any((x.get("priodTitle") or "").replace(".", "") == ym and (x.get("expUsdAmt") or 0) > 0 for x in rows):
            return True
    return False


def _prog(**kw):
    kw["at"] = dt.datetime.now().isoformat(timespec="seconds")
    tmp = PROG_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(kw, fh, ensure_ascii=False)
    os.replace(tmp, PROG_PATH)


def update(S, month=None):
    """서버가 띄우는 매달 갱신 — 전 종목을 다시 돌려 result.new.json 에 쓰고, 끝까지 가면 result.json 과 바꾼다.
    진행은 progress.json(10초마다) — 서버가 이걸 읽어 화면에 'n/792'를 띄우고, 15분 넘게 안 바뀌면 죽은 것으로 본다."""
    import time
    month = month or _months_back(1)
    t0 = dt.datetime.now().isoformat(timespec="seconds")
    K.FRESH_AFTER = time.time()
    last = [0.0]

    def step(i, n, k):
        if time.time() - last[0] >= 10 or i == n:
            last[0] = time.time()
            _prog(state="running", month=month, i=i, n=n, ch=k, started=t0, pid=os.getpid())

    step(0, 0, 0)
    try:
        build_all(S, out_name="result.new.json", on_step=step)
        new = os.path.join(CACHE, "result.new.json")
        with open(new, "r", encoding="utf-8") as fh:
            d = json.load(fh)
        if d.get("stopped"):
            _prog(state="quota", want=month, msg=d["stopped"], started=t0)
            return
        cur = os.path.join(CACHE, "result.json")
        if os.path.exists(cur):
            os.replace(cur, os.path.join(CACHE, "result_prev.json"))
        os.replace(new, cur)
        _prog(state="done", month=data_month(d), want=month, n=len(d["items"]),
              ch=sum(1 for x in d["items"] if x.get("channels")), started=t0)
    except Exception as e:
        _prog(state="error", want=month, msg="%s: %s" % (type(e).__name__, e), started=t0)
        raise


if __name__ == "__main__":
    import sys
    import importlib.util
    if sys.stdout:
        sys.stdout.reconfigure(encoding="utf-8")
    spec = importlib.util.spec_from_file_location("srv", os.path.join(BASE, "서버.py"))
    S = importlib.util.module_from_spec(spec)
    argv, sys.argv = sys.argv, ["x"]
    spec.loader.exec_module(S)
    sys.argv = argv
    S.INDEX.update(json.load(open(S.INDEX_PATH, encoding="utf-8")))
    if len(sys.argv) > 1 and sys.argv[1] == "갱신":
        update(S, sys.argv[2] if len(sys.argv) > 2 else None)
        print("갱신 끝 — %s" % json.load(open(PROG_PATH, encoding="utf-8")).get("state"))
        sys.exit(0)
    codes = set(sys.argv[2].split(",")) if len(sys.argv) > 2 else None
    if len(sys.argv) > 1 and sys.argv[1] == "전체":
        items = build_all(S, codes)
        print("끝 — 통로 있는 회사 %d" % sum(1 for x in items if x.get("channels")))
    else:
        print("python 수출추적.py 전체 [코드,코드]   |   python 수출추적.py 갱신 [YYYYMM]")
