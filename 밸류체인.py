# -*- coding: utf-8 -*-
"""
밸류체인 — 정기보고서 「사업의 내용」에서 이 회사가 누구에게 팔고(매출처), 누구에게서 사며(원재료 · 매입처), 어디로 파는지(수출 · 내수),
종속회사의 최종 고객은 누구인지, 경쟁사로 누구를 적는지를 뽑는다 (2026-10-04).

회사마다 적는 모양이 다르다 — 넷 다 받는다.
  (가) 이름(비중): "주요 매출처는 HICO(6.78%), 한국전력공사 본사 (3.40%) 등"            → 효성중공업
  (나) 문장 + 비중: "주요 매출처는 삼성전자와 그 종속기업이며 … 약 27% 수준"              → 삼성전기
  (다) 가려진 고객: "매출액의 10% 이상을 차지하는 주요 고객은 1개 거래처 … 1,385,727백만원" → 한화오션
  (라) 이름 없음: "세계 유수의 모바일 및 컴퓨팅 관련 전자 업체"                            → SK하이닉스
표: 주요 원재료 현황(품목 · 매입액 · 비중 · 매입처), 매출실적(수출 · 내수), 사업부문별 현황(법인 · 재화 · 주요 고객).
비중 숫자는 보고서가 적은 그대로다(모회사 별도 기준인지 연결 기준인지는 문장을 따른다).
"""
import re

PCT = r"\(?\s*(?:약\s*)?(\d{1,3}(?:\.\d+)?)\s*%\s*\)?"
# 이름(비중) 나열 — "HICO(6.78%), 부산우암1구역 주택재개발정비사업조합(4.31%), AL FANAR(3.39%) 등"
NAME_PCT = re.compile(r"([A-Za-z가-힣0-9&＆·ㆍ.,'’\-\s()㈜]+?)\s*(?:\(\s*(?:약\s*)?(\d{1,3}(?:\.\d+)?)\s*%\s*\)|\s(?:약\s*)?(\d{1,3}(?:\.\d+)?)\s*%(?=[,\s등을를이가]|$))")
CUST_LEAD = re.compile(r"(?:주요\s*(?:매출처|고객(?:사)?|거래처|판매처)(?:\s*및\s*비중)?(?:는|은|로는|으로는|:)|(?:최종\s*고객\s*기준\s*)?주요\s*매출처는|"
                       r"거래처\s*별로?\s*(?:전체\s*)?매출(?:액)?에서\s*차지하는\s*비중은)")
HIDDEN = re.compile(r"매출액의\s*10\s*%\s*이상을?\s*차지하는\s*주요\s*고객(?:수)?[은는]?\s*(\d+)\s*개")
HIDDEN_AMT = re.compile(r"해당\s*거래처(?:에|에서)?\s*발생한\s*매출액은?\s*([\d,]+)\s*백만\s*원")
SINGLE = re.compile(r"주요\s*매출처는\s*([가-힣A-Za-z0-9&\s·]+?)(?:와|과|및)\s*(?:그\s*)?(?:종속|계열|관계)\s*(?:기업|회사)[^.]{0,80}?(?:약\s*)?(\d{1,3}(?:\.\d+)?)\s*%")
TRAIL = re.compile(r"\s*(?:등|등의|등을|등이|로|으로|에|에게|입니다|이며|이고|임|,|·|ㆍ|및|와|과)\s*$")
BAD_NAME = re.compile(r"^(?:수출|내수|직수출|LOCAL\s*수출|로컬\s*수출|민수|기타(?:\s*거래처|\s*고객|\s*매출처)?|합계|소계|국내|해외|현지|중국내수|중국\s*내수|관수|관급|민간|수입|상품|제품|용역|제\s*\d+\s*기|당기|전기|합\s*계|"
                      r"[가-힣]+(?:팀|부서|본부|사업부|실|과)|기타\s*\d+\s*%?|Others?|ETC\.?|Miscellaneous)$", re.I)
CHANNEL = re.compile(r"^(?:수출|내수|직수출|LOCAL\s*수출|로컬\s*수출|민수|중국\s*내수|중국내수|관수|관급|민간|국내|해외)$", re.I)
COMPETE = re.compile(r"(?:경쟁(?:사|업체|회사|기업)(?:로는|는|은|인|로|으로|:)?\s*)([A-Za-z가-힣0-9&·ㆍ,\s()㈜/]+?)(?:등|와|과|및|이|가)\b")
SUBS_HEAD = re.compile(r"주요종속회사\s*\n\s*판매경로\s*\n\s*판매전략\s*\n\s*주요매출처\s*및\s*비중\s*\n\s*비고")
SEG_HEAD = re.compile(r"사업부문\s*\n+\s*법인명\s*\n+\s*주요\s*재화\s*및\s*용역\s*\n+\s*주요\s*고객\s*\n+\s*사업의\s*내용\s*\n+\s*비고")
FOREIGN = re.compile(r"[A-Za-z]{3,}")
COUNTRY_HINT = [("한국", r"한국전력|한전|㈜|\(주\)|주식회사|정비사업조합|조합$|공사$|삼성|현대|LG|SK\s|포스코|두산|한화|롯데|GS|CJ"),
                ("미국", r"America|USA|U\.S\.|Dominion|Eversource|\bAEP\b|American Electric|Southern|Georgia [Pp]ower|Intersect|LS Power|Pattern|Constellation|\bPSE\b|WESCO|Burns|QTS|\bSCE\b|X\.AI|Softbank"),
                ("인도", r"India|Adani|\bKEC\b|PGCIL|Power Grid Corporation|L&T|Larsen|MEGHA|KHAVADA|Arasan|SHYAMA|\bBGR\b"),
                ("중국", r"China|Nantong|국가전망|남방전망|내몽고|GUANGBO|화능|화전|국전|대당|중전투|무한강철|\(중국\)"),
                ("사우디", r"AL FANAR|Saudi|SAUDI ELECTRICITY"), ("남아공", r"ESKOM|남아공"), ("일본", r"Japan|SHOEI|TORAY|MITSUBISHI|RESONAC|Tokyo|Nippon|Sumitomo|Hitachi|COSMO"),
                ("독일", r"Germany|Siemens|ATOTECH"), ("방글라데시", r"DESCO|Bangladesh")]


JUNK_NAME = re.compile(r"같습니다|없습니다|않습니다|않았습니다|바랍니다|입니다|합니다|됩니다|있습니다|참고|해당\s*사항|^아래$|^다음$|^위$|^각각|"
                       r"비율|증가율|금융자산|예탁금|부채|차입금|자본금|매출액|대비|생산하는|하는$|되는$|기준|^\d+(?![A-Za-z\d])|^주\s*\d|^\((?!주\))|^[^\w가-힣]+$|개사$|"
                       r"계열회사|^(?:당기|전기|합\s*계|소\s*계|총\s*계|지배회사|종속회사|USD|JPY|EUR|CNY|KRW|GBP|원화|외화)$|연구\s*개발|경영\s*자문|가나다\s*순|^[^(]*\)$")
TYPE_NAME = re.compile(r"^(?:유럽|중국|일본|미국|아시아|북미|남미|중남미|중동|동남아|아프리카|오세아니아|글로벌|국내|해외|관수|민수|일반|개인(?:\s*고객)?|기업\s*고객|업무용|가정용|산업용|"
                       r"면세점|금융기관|공공기관|관공서|정부|지자체|건설사|EPC|대리점|특약점|도매|소매|병원|약국|의원|유통|딜러|홈쇼핑|온라인|백화점|할인점|편의점|"
                       r"반도체|디스플레이|자동차|조선|가전|통신|기타|완성차|정유사|발전사|전력사)(?:\s*(?:업체|회사|등|사))?(?:\s*등)?$", re.I)
ANON_NAME = re.compile(r"^(?:주요\s*)?(?:고객|거래처|매출처)\s*\(?\s*([A-Za-z]|[가-하])\s*\)?(?:\s*사)?$|^[\"'“”‘’]?([A-Z]|[가-하])[\"'“”‘’]?\s*사(?:\s*\(社\))?$")
CORP_HINT = re.compile(r"㈜|\(주\)|주식회사|유한|[A-Za-z]{2,}")


def name_kind(nm):
    """'named' · 'type'(고객군 · 지역) · 'hidden'(익명 표기) · None(잡음)."""
    nm = (nm or "").strip()
    if not nm or len(nm) < 2:
        return None
    if ANON_NAME.match(nm):
        return "hidden"
    if TYPE_NAME.match(nm):
        return "type"
    if JUNK_NAME.search(nm):
        return None
    if len(nm.split()) >= 4 and not CORP_HINT.search(nm):
        return None                   # 띄어쓴 낱말 넷 이상 + 법인 표시 없음 = 문장 조각('전기 전자 완제품을 생산하는')
    return "named"


def _anon_label(nm):
    m = ANON_NAME.match(nm.strip())
    return "고객 %s(이름 비공개)" % ((m.group(1) or m.group(2)) if m else nm)


def _clean_name(s):
    s = re.sub(r"\s+", " ", s or "").strip(" ,·ㆍ-")
    s = TRAIL.sub("", s).strip()
    s = re.sub(r"^(?:및|와|과|그리고)\s+", "", s).strip()
    return s


def _country(name):
    for c, rx in COUNTRY_HINT:
        if re.search(rx, name):
            return c
    return "해외" if FOREIGN.search(name) and not re.search(r"[가-힣]", name) else ("한국" if re.search(r"[가-힣]", name) else None)


def _names_in(text):
    """'HICO(6.78%), 한국전력공사 본사 (3.40%)' 꼴을 [(이름, 비중)]로. 비중 없는 나열은 비중 None."""
    out = []
    for m in NAME_PCT.finditer(text):
        nm = _clean_name(m.group(1))
        # 앞 문장의 꼬리가 섞여 들어온다('2025년 주요 매출처는 HICO') — 마지막 구분자 뒤만
        nm = re.split(r"(?:매출처는|고객은|거래처는|매입처는|비중은|는|은)\s+", nm)[-1].strip() if len(nm) > 40 else nm
        # '동국제강(주)이며, 매출비율은 동국제강(주)' — 문장 이음말 뒤의 마지막 이름만
        nm = re.split(r"(?:이며|이고|이다|으로서|로서)[,\s]+|(?:비율|비중|매출처|거래처|고객)(?:은|는)\s+", nm)[-1].strip()
        if not nm or BAD_NAME.match(nm) or len(nm) < 2 or len(nm) > 60:
            continue
        if re.search(r"사업\s*부문|부문$|억\s*원|백만\s*원|\d조|매출액|대비|전체|비중", nm):
            continue          # 부문 매출 비중 문장('컴포넌트 사업부문 5조 1,985억원 45.95%') — 고객이 아니다
        out.append((nm, float(m.group(2) or m.group(3))))
    return out


def _without_subs(text):
    """종속회사 표(판매경로 · 판매전략 · 주요매출처 및 비중 … 수주상황 전)를 비운 본문 — 지배회사 매출처만 남기려고."""
    m = SUBS_HEAD.search(text)
    if not m:
        return text
    end = re.search(r"\n\s*\(\d\)\s*수주상황|\n\s*[가-하]\.\s*수주|\n\s*\d\.\s*수주", text[m.end():])
    stop = m.end() + (end.start() if end else 8000)
    return text[:m.start()] + text[stop:]


UNIT = {"천": 1e3, "백만": 1e6, "억": 1e8}


def _ten_pct(text):
    """'매출액의 10% 이상' 고객 문장.
    LG디스플레이 '고객은 "가"사(社)와 "나"사(社)이며, 각각 14,835,862백만원(2024년: …)과 3,412,768백만원' → 익명 둘 + 금액
    솔루엠 'A사와 그 종속기업 … 827,048,769천원' · 송원산업 '1개 고객사 … 111,028백만원' → 익명 + 금액
    S-Oil '주요매출처는 Aramco Trading Singapore Pte. Ltd.(매출액 비중 21.5%)입니다' · GS 'Chevron U.S.A. Inc.입니다' → 이름
    PI첨단소재 '주요고객에 대한 매출비중은 각각 매출액의 25.72%와 25.98%' → 익명 1 + 비중(당기)
    OCI · 대웅 '10% 이상을 차지하는 … 고객은 없습니다' → none"""
    out = []
    for m in re.finditer(r"10\s*%\s*이상", text):
        # 문장 = 앞쪽 '다.' · 줄바꿈 뒤부터 뒤쪽 '다.' · '다(' · 줄바꿈까지 — 'Pte. Ltd.' 처럼 이름 속 마침표에서 끊기지 않게
        a = max(text.rfind("다.", max(0, m.start() - 200), m.start()), text.rfind("\n", max(0, m.start() - 200), m.start()))
        a = a + 2 if a >= 0 else max(0, m.start() - 200)
        e = re.search(r"다[.(]|\n", text[m.end():m.end() + 450])
        sen = text[a:m.end() + (e.end() if e else 450)]
        if not re.search(r"고객|거래처|매출처", sen) or re.search(r"자회사|자산총액|지분|주주|채권|대손|신용위험이\s*집중", sen) and not re.search(r"매출", sen):
            continue
        if re.search(r"없습니다|없음|해당\s*사항(?:이)?\s*없", sen):
            out.append({"name": "매출 10% 넘는 고객 없음", "pct": None, "scope": "연결", "kind": "none", "country": None})
            continue
        body = re.sub(r"\([^)]*\d{4}\s*년[^)]*\)", "", sen)            # '(2024년: 14,281,844백만원)' 같은 전기 금액은 지운다
        amts = [float(a.replace(",", "")) * UNIT[u] for a, u in re.findall(r"([\d,]{3,})\s*(천|백만|억)\s*원", body)]
        pcts = [float(x) for x in re.findall(r"(\d{1,2}(?:\.\d+)?)\s*%", body) if float(x) != 10]
        labels = re.findall(r"[\"'“”‘’]([가-하A-Z])[\"'“”‘’]\s*사|(?<![A-Za-z])([A-Z])\s*사(?:와|과|,|\s|이|는|의)", body)
        labels = [a or b for a, b in labels]
        nco = re.search(r"(\d+)\s*개\s*(?:의\s*)?(?:고객|거래처|매출처)", body)
        named = re.search(r"(?:매출처|고객|거래처)(?:는|은)\s+((?:[A-Z][A-Za-z0-9.&,'\- ]{2,70}?)|(?:[가-힣][가-힣A-Za-z0-9()㈜ ]{1,30}?))(?:\s*\(\s*매출(?:액)?\s*비중\s*(\d{1,3}(?:\.\d+)?)\s*%\s*\))?\s*(?:입니다|이며|이고|및\s*그|와\s*그|과\s*그)", body)
        if labels:
            for i, lb in enumerate(dict.fromkeys(labels)):
                out.append({"name": "고객 %s(이름 비공개)" % lb, "pct": pcts[i] if i < len(pcts) and len(pcts) >= len(labels) else (pcts[0] if len(labels) == 1 and pcts else None),
                            "amt": amts[i] if i < len(amts) else None, "scope": "연결", "kind": "hidden", "country": None})
        elif not nco and named and name_kind(_clean_name(named.group(1))) == "named" and not re.match(r"\d", named.group(1)):
            nm = _clean_name(named.group(1))
            out.append({"name": nm, "pct": float(named.group(2)) if named.group(2) else (pcts[0] if pcts else None), "scope": "연결", "kind": "named", "country": _country(nm)})
        elif nco or pcts or amts:
            n = int(nco.group(1)) if nco else 1
            out.append({"name": "매출 10%% 이상 고객 %d곳(이름 비공개)" % n, "pct": pcts[0] if pcts else None, "amt": amts[0] if amts else None,
                        "scope": "연결", "kind": "hidden", "country": None})
    return out


def customers(text):
    """매출처 — [{name, pct, scope('지배회사'|'종속회사명'|'연결'), kind('named'|'hidden'|'type'|'none'), country}]"""
    text = _without_subs(text)
    out = []
    # (다) 가려진 고객 — 10% 이상 n곳, 금액
    for m in HIDDEN.finditer(text):
        n = int(m.group(1))
        seg = text[m.end():m.end() + 300]
        amt = HIDDEN_AMT.search(seg)
        pct = re.search(r"\(\s*(\d{1,3}(?:\.\d+)?)\s*%\s*\)", seg)
        out.append({"name": "매출 10%% 이상 고객 %d곳(이름 비공개)" % n, "pct": float(pct.group(1)) if pct else None,
                    "amt": float(amt.group(1).replace(",", "")) * 1e6 if amt else None, "scope": "연결", "kind": "hidden", "country": None})
    # (다') '10% 이상' 문장의 다른 꼴 — 익명 '가'사 · A사 · n개 고객사, 이름 + 비중, '없습니다'
    if not out:
        out += _ten_pct(text)
    # (나) 한 곳 + 비중
    for m in SINGLE.finditer(text):
        out.append({"name": _clean_name(m.group(1)), "pct": float(m.group(2)), "scope": "연결", "kind": "named", "country": None})
    # (가) 이름(비중) 나열 — 지배회사 문장
    for m in CUST_LEAD.finditer(text):
        seg = text[m.end():m.end() + 600]
        seg = seg.split("\n\n")[0] if "\n\n" in seg[:600] else seg
        stop = re.search(r"(?:입니다|등\s*입니다|임\.|\.\s)", seg)
        if stop:
            seg = seg[:stop.end()]
        got = _names_in(seg)
        if got:
            # 이 문장이 종속회사 표 안인지(앞 300자에 'Co., Ltd' · 'Inc' 법인명 줄이 있나)는 subsidiaries() 가 따로 다룬다
            for nm, pct in got:
                if CHANNEL.match(nm):
                    continue
                out.append({"name": nm, "pct": pct, "scope": "지배회사", "kind": "named", "country": _country(nm)})
    # (카) 법인 · 사업부문별 매출처 표(LS ELECTRIC) — 지배회사 몫. 있으면 일반 표 읽기는 건너뛴다(판매경로 표를 매출처로 잘못 읽는다)
    segt = [t for t in seg_customer_tables(text) if t["parent"]]
    for t in segt:
        for r in t["rows"]:
            out.append({"name": r["name"], "pct": r["pct"], "scope": t["entity"] or "지배회사", "seg": r["seg"], "basis": "부문",
                        "kind": r["kind"], "country": _country(r["name"])})
    # (마)(바)(차) 표 — 머리글에 매출처 · 거래처 · 고객 칸과 금액 · 비중 칸이 있는 표
    if not segt:
        out += _customer_tables(text)
    # (사)(아) 이름만 나열(비중 없음) — 표의 '주요고객' 칸, 문장 "주요 매출처는 A, B, C 등"
    if not any(x.get("pct") is not None for x in out):
        out += _customer_names_only(text)
    # 이름 판정 — 잡음은 버리고, 고객군 · 지역은 type, 익명 표기는 hidden
    keep = []
    for x0 in out:
        # 한 칸에 여럿('삼성전자, SK하이닉스 외' · 'Intel, TSMC, Micron 외') — 가른다. 비중은 누구 몫인지 몰라 비운다
        parts = [_supp_name(t) for t in re.split(r",\s*", x0["name"])] if x0.get("kind") == "named" and re.search(r",\s*\S", x0["name"]) \
            and not re.search(r",\s*(?:Inc|Ltd|LLC|Co|Corp|S\.A|N\.V|GmbH|PLC|Limited)\b", x0["name"], re.I) else [x0["name"]]
        parts = [t for t in parts if t]
        if len(parts) > 1:
            xs = [dict(x0, name=t, pct=None, country=_country(t)) for t in parts]
        else:
            xs = [dict(x0, name=_supp_name(x0["name"]) if x0.get("kind") == "named" else x0["name"])]
        for x in xs:
            if x.get("kind") == "named":
                k_ = name_kind(x["name"])
                if k_ is None:
                    continue
                if k_ == "hidden":
                    x = dict(x, name=_anon_label(x["name"]), kind="hidden", country=None)
                elif k_ == "type":
                    x = dict(x, kind="type")
            keep.append(x)
    out = keep
    # 같은 이름은 큰 비중 하나로
    seen, uniq = {}, []
    for x in out:
        k = re.sub(r"\s+|[().,'’㈜]", "", x["name"]).lower()
        if k in seen:
            if (x.get("pct") or 0) > (seen[k].get("pct") or 0):
                seen[k].update(x)
            continue
        seen[k] = x
        uniq.append(x)
    return uniq


CUST_TBL_HDR = re.compile(r"(?:주요\s*)?(?:매출처|거래처|고객(?:사|명)?|판매처)\s*(?:명)?\s*\n")
CUST_NAME_OK = re.compile(r"[가-힣A-Za-z]{2,}")
CUST_NAME_BAD = re.compile(r"^(?:합\s*계|소\s*계|기타(?:\s*거래처)?|국내|해외|수출|내수|제품|상품|용역|매출|합계|총계|비\s*고|구\s*분|당기|전기|금\s*액|비\s*중|주식|자동차|전자|부품|조선|건설|은행|보험)$|"
                           r"점유율|시장\s*규모|거래처\s*\d+|고객\s*[0-9]$|고객\s*수|이상\s*차지|\*\*|^\d{2}년|유지보수|체결하고|있습니다|합니다$|입니다$")


def _customer_tables(text):
    """표로 적은 매출처 — 머리글 줄에 매출처 · 거래처 · 고객 칸이 있고 금액 · 비중 칸이 따라오는 표.
    SJG세종(주요 매출처 / 금액 / 비중 / 비고) · 오리엔탈정공(거래처 / 금액 비중 금액 비중 증감률) · DB(구분 / 당기 / 전기 — 이름 · 금액 · 비중)."""
    best = []
    # 머리 줄은 번호('다.' '④' '(5)') 뒤 곧장 매출처 · 거래처 · 고객으로 시작해야 한다 — 문장 속 '고객' 뒤의 품목 · 부문 매출표(한화오션 'LNGC 등')를 막는다
    for m in re.finditer(r"(?m)^[\s()\d.가-하①-⑳\-]{0,8}(?:주요\s*)?(?:매출처|거래처|고객)(?:별|사)?[^\n]{0,300}\n", text):
        if re.search(r"위험\s*관리|파생|헤지|조직|부서|거래\s*중|거래를|거래는|거래의", text[max(0, m.start() - 160):m.end()]):
            continue          # '헤지거래 … 거래처' 처럼 문장 속 낱말 — 표 머리글이 아니다
        body = text[m.end():m.end() + 3500]
        rows = _rows(body)
        if len(rows) < 2:
            continue
        hdr = []
        # 머리글은 첫 한두 행에 흩어져 있다(단위 줄 · '금액 비중 금액 비중' 둘째 줄)
        for r_ in rows[:3]:
            hdr += r_
            if any(re.search(r"비\s*중|비\s*율|매출액|금\s*액", h) for h in r_):
                break
        if not any(re.search(r"매출처|거래처|고객|구\s*분|회사|업체", h) for h in hdr) or not any(re.search(r"비\s*중|비\s*율|%", h) for h in hdr):
            continue
        if any(re.search(r"담당\s*부서|관련\s*부서|부서|담당자|담당\s*업무|관리\s*조직|인\s*원|연락처|위험|헤지|파생|결제\s*조건|판매\s*방법|"
                         r"판매\s*경로|직판|특약점|대리점|도매|소매|구성비", h) for h in hdr):
            continue          # 판매 조직 · 위험관리 조직 · 파생상품 표가 '거래처' 낱말 뒤에 오기도 한다(한화오션 '국제금융팀 3')
        start = len([r_ for r_ in rows[:3] if r_ and r_ is not None][:rows.index(r_) + 1]) if False else next(
            (i + 1 for i, r_ in enumerate(rows[:3]) if any(re.search(r"비\s*중|비\s*율|매출액|금\s*액", h) for h in r_)), 1)
        got, out = 0, []
        for cells in rows[start:start + 25]:
            if not cells:
                continue
            nm = cells[0]
            if re.search(r"^\(?단위|^\(?\*|^※|^주\d|^\[주", nm):
                continue
            if not CUST_NAME_OK.search(nm) or CUST_NAME_BAD.search(nm) or BAD_NAME.match(nm) or re.search(r"\d{3,}|^\d", nm) or len(nm) > 40:
                if got:
                    break
                continue
            if len(cells) < 2 or not re.search(r"\d", " ".join(cells[1:])):
                if got:
                    break
                continue
            nums = [x for x in cells[1:] if re.search(r"\d", x)]
            if not nums:
                continue
            pct = None
            for x in nums:
                mp = re.fullmatch(r"\(?\s*(\d{1,3}(?:\.\d+)?)\s*%?\s*\)?", x.replace(",", ""))
                if mp and (("%" in x) or float(mp.group(1)) <= 100 and "," not in x and len(x) <= 6):
                    pct = float(mp.group(1))
                    break
            if pct is None:
                continue
            nm2 = re.sub(r"\s*(?:및\s*(?:그\s*)?종속(?:기업|회사)|\(주\d*\)|\[주\d*\]|\(\*+\))\s*$", "", nm).strip()
            out.append({"name": nm2, "pct": pct, "scope": "표", "kind": "named", "country": _country(nm2)})
            got += 1
        if got > len(best):
            best = out
    return best


def _customer_names_only(text):
    """이름만 적은 매출처 — 비중 없음. 문장 "주요 매출처는 삼성전자 등 … 현대자동차, 현대모비스, LG전자 등", 표 '주요고객' 칸('현대자동차기아자동차현대위아 …')."""
    out = []
    for m in re.finditer(r"주요\s*(?:매출처|고객(?:사)?|거래처)(?:는|은|로는|으로는|:)\s*([^.\n]{4,300})", _without_subs(text)):
        seg = m.group(1)
        if "%" in seg:
            continue
        for tok in re.split(r",|·|ㆍ|및|와\s|과\s|\s등\s|\s등$", seg):
            tok = _clean_name(re.sub(r"(?:국내외|해외|국내)?\s*(?:휴대폰|자동차|전자|관련)?\s*(?:업체|기업|회사|고객|거래처)들?(?:을|를|과|와|로)?\s*(?:주요\s*)?(?:거래처로\s*)?(?:확보|보유|공급|납품)?.*$", "", tok))
            tok = re.sub(r"^(?:당사의|당사는|국내외|국내|해외)\s*", "", tok).strip()
            if re.search(r"(?:하고|하여|되어|있으|이며|으로|에서|까지|부터)\s*\S*$", tok) and not re.search(r"㈜|\(주\)", tok):
                continue          # 문장 꼬리('장기해상운송계약을 체결하고 있습니다')
            if CUST_NAME_OK.search(tok) and 2 <= len(tok) <= 20 and not CUST_NAME_BAD.search(tok) and not re.search(r"\s", tok[:2]):
                out.append({"name": tok, "pct": None, "scope": "문장", "kind": "named", "country": _country(tok)})
        if out:
            break
    # 표의 '주요고객' 칸 — 줄바꿈 없이 붙은 이름들
    m = re.search(r"주요\s*고객\s*\n", text)
    if m and not out:
        for cells in _rows(text[m.end():m.end() + 2500])[:12]:
            for cell in cells:
                if len(cell) >= 10 and not re.search(r"\d", cell) and re.search(r"(?:현대|기아|삼성|LG|SK|한화|두산|포스코|롯데|GS|CJ|효성|HD현대)", cell):
                    names = [n for n in re.split(r",|·|ㆍ|\s+", re.sub(r"\s*등\s*$", "", cell)) if n]
                    glued = []
                    for n in names:
                        glued += [g for g in re.split(r"(?=현대|기아|삼성|LG|SK|한화|두산|포스코|롯데|GS|CJ|효성|HD현대)", n) if len(g) >= 2]
                    for g in dict.fromkeys(glued):
                        out.append({"name": g, "pct": None, "scope": "표", "kind": "named", "country": _country(g)})
                    break
            if out:
                break
    return out[:10]


SEGCUST_HEAD = re.compile(r"(?:사업\s*부문|부\s*문|구\s*분)\s*\n+\s*주요\s*(?:매출처|고객(?:사)?|거래처)(?:명)?\s*\n+\s*(?:매출\s*)?(?:비\s*중|비\s*율)(?:\s*\(\s*%\s*\))?\s*\n")
ENTITY_HEAD = re.compile(r"\[(?!주\s*\d|단위|참고|별첨)([A-Za-z가-힣][^\]\n]{1,48})\]")
CUST_TYPE = re.compile(r"(?:회사|산업|업체|업계|대리점|특약점|상사|고객|기관|사업자|건설사|제조사|유통|딜러|EPC)(?:\s*등)?$|/|^(?:관공서|공공기관|민수|관수|개인|일반|기업|지자체)$|^시설|투자\s*\(")
CORP_MARK = re.compile(r"주식회사|\(주\)|㈜|유한\s*공사|유한\s*회사|\b(?:LLC|INC|LTD|CORP|CO\.|GmbH|LIMITED|COMPANY)\b", re.I)


def seg_customer_tables(text):
    """법인 · 사업부문별 주요 매출처 표 — '[LS ELECTRIC] … (4) 주요 매출처 및 매출비중' 다음 '사업부문 / 주요매출처 / 매출 비중'.
    법인 이름은 표 앞의 [대괄호] 머리이고 첫 법인이 지배회사다. 비중은 그 부문 매출 가운데 비중.
    '제조회사 50 · 조선회사/EPC 32' 처럼 이름이 아니라 고객군이면 kind='type'.
    → [{entity, parent, rows:[{seg, name, pct, kind}]}]"""
    out, first = [], None
    for m in SEGCUST_HEAD.finditer(text):
        heads = list(ENTITY_HEAD.finditer(text, max(0, m.start() - 9000), m.start()))
        body = text[m.end():m.end() + 3000]
        stop = re.search(r"\n\s*\[|\n\s*\(\d\)|\n\s*[가-하]\.\s|\n\s*\d\.\s", body)
        body = body[:stop.start()] if stop else body
        rows, seg = [], None
        for cells in _rows(body):
            if len(cells) >= 3:
                seg, cells = cells[0], cells[1:3]      # 세 칸 = 부문 · 이름 · 비중, 두 칸 = 이름 · 비중(부문은 위 행에서 이어짐)
            if len(cells) != 2:
                continue
            nm, v = cells
            mv = re.fullmatch(r"\(?\s*(\d{1,3}(?:\.\d+)?)\s*%?\s*\)?", v.replace(",", ""))
            if not mv or BAD_NAME.match(nm) or CUST_NAME_BAD.search(nm) or re.match(r"합\s*계|기\s*타", nm):
                continue
            nm = re.sub(r"\s+\(주\)$", "(주)", nm).strip()
            k_ = name_kind(nm)
            if k_ is None:
                continue
            typ = k_ == "type" or (CUST_TYPE.search(nm) and not CORP_MARK.search(nm))
            if k_ == "hidden":
                nm = _anon_label(nm)
            rows.append({"seg": seg, "name": nm, "pct": float(mv.group(1)), "kind": "type" if typ else k_})
        if not rows:
            continue
        # 법인 머리 — 표 안 부문 이름과 같은 [대괄호](예: [전력시스템])는 부문 소제목이다. 그 앞의 법인 머리를 쓴다
        segs = {re.sub(r"\s+", "", r["seg"] or "") for r in rows}
        heads = [h for h in heads if re.sub(r"\s+", "", h.group(1)) not in segs]
        ent = heads[-1].group(1).strip() if heads else None
        if first is None:
            first = ent or ""
        out.append({"entity": ent, "parent": (ent or "") == first, "rows": rows})
    return out


def subsidiaries(text):
    """종속회사 표(판매경로 · 판매전략 · 주요매출처 및 비중) — [{sub, customers:[(이름, 비중)], channels:[(경로, 비중)], note}]
    법인별 매출처 표('[LS ELECTRIC America] … 사업부문 / 주요매출처 / 매출 비중')의 종속회사 몫도 여기로 — 고객군은 types."""
    out = []
    for t in seg_customer_tables(text):
        if t["parent"] or not t["entity"]:
            continue
        out.append({"sub": t["entity"], "customers": [(r["name"], r["pct"]) for r in t["rows"] if r["kind"] == "named"],
                    "types": [(r["name"], r["pct"]) for r in t["rows"] if r["kind"] == "type"], "final": [], "channels": [],
                    "segs": sorted({r["seg"] for r in t["rows"] if r["seg"]})})
    m = SUBS_HEAD.search(text)
    if not m:
        return out
    body = text[m.end():]
    end = re.search(r"\n\s*\(\d\)\s*수주상황|\n\s*[가-하]\.\s*수주|\n\s*\d\.\s*수주", body)
    body = body[:end.start()] if end else body[:8000]
    # 법인명 줄 — 영문 법인(Co., Ltd / Inc / Pvt / GmbH) 또는 (주)
    heads = list(re.finditer(r"(?m)^\s*([A-Z][A-Za-z0-9&.,'\- ]{3,}(?:Ltd\.?|Inc\.?|Co\.|Corp\.?|GmbH|LLC|S\.A\.|Pvt\.?\s*Ltd\.?)|[가-힣A-Za-z0-9]+(?:㈜|\(주\))[가-힣A-Za-z0-9]*)\s*$", body))
    for i, h in enumerate(heads):
        blk = body[h.end():heads[i + 1].start() if i + 1 < len(heads) else len(body)]
        custs, chans = [], []
        for m2 in re.finditer(r"주요\s*매출처는([^.\n]{0,400})", blk):
            for nm, pct in _names_in(m2.group(1)):
                (chans if CHANNEL.match(nm) else custs).append((nm, pct))
        for m2 in re.finditer(r"판매\s*경로는([^.\n]{0,300})", blk):
            for nm, pct in _names_in(m2.group(1)):
                chans.append((nm, pct))
        fin = re.search(r"최종\s*고객\s*기준\s*주요\s*매출처는([^.\n]{0,400})", blk)
        final = _names_in(fin.group(1)) if fin else []
        custs = [(nm, p) for nm, p in custs if name_kind(nm) == "named"]
        final = [(nm, p) for nm, p in final if name_kind(nm) == "named"]
        out.append({"sub": _clean_name(h.group(1)), "customers": custs, "final": final, "channels": chans})
    return out


def _rows(body):
    """표 본문 → 행 목록. 빈 줄이 행 경계, 줄 하나가 칸 하나."""
    return [[ln.strip() for ln in blk.split("\n") if ln.strip()] for blk in re.split(r"\n{2,}", body) if blk.strip()]


def segments(text):
    """사업부문별 현황 표(법인명 · 주요 재화 · 주요 고객 · 사업의 내용) — [{segment, entity, goods, customers, biz}]"""
    m = SEG_HEAD.search(text)
    if not m:
        return []
    body = text[m.end():]
    end = re.search(r"\n\s*\(\d\)\s*사업부문별\s*요약|\n\s*[가-하]\.\s*사업부문별\s*요약|\n\s*\d\.\s", body)
    body = body[:end.start()] if end else body[:4000]
    out, seg = [], None
    for cells in _rows(body):
        if len(cells) >= 5 and len(cells[0]) <= 8 and not re.search(r"[A-Za-z(),]", cells[0]):   # 사업부문 칸이 앞에 붙은 행
            seg, cells = cells[0], cells[1:]
        if len(cells) < 3:
            continue
        ent, goods, cust = cells[0], cells[1], cells[2]
        if not re.search(r"[A-Za-z㈜(]|\(주\)", ent) or re.search(r"재무현황|단위|구분", ent):
            continue
        out.append({"segment": seg, "entity": ent, "goods": goods, "customers": cust, "biz": cells[3] if len(cells) > 3 and cells[3] != "-" else ""})
        if len(out) > 12:
            break
    return out


MAT_HEAD = re.compile(r"주요\s*원\s*재\s*료\s*(?:등\s*의?\s*)?(?:현\s*황|매입\s*(?:현황|실적)?)?\s*(?:\([^)\n]{0,30}\)[^\n]{0,40})?\s*\n")
SUBTOTAL = re.compile(r"^(?:합\s*계|소\s*계|총\s*계|계|Total|Sub\s*total)$", re.I)
NOTE_SUPP = re.compile(r"㈜|\(주\)|주식회사|[A-Za-z]{4,}|(?:제철|제강|화학|전자|중공업|산업|금속|물산|상사|케미칼|소재|에너지|정유|석유|철강|스틸|머티리얼|엔진|빌리티|가스|전력|제지|유리|섬유)$")
HDR_KEY = re.compile(r"^(?:사업부문|사업구분|구분|부문|매입유형|품목|품명|원재료|원재료명|원자재|구체적용도|용도|매입액|매입금액|금액|투입액|비율|비중|매입처|주요매입처|공급처|공급사|공급업체|구입처|업체명|비고|회사명|법인명)")
MAT_COLS = (("seg", r"사업부문|사업구분|^구분$|^부문$"), ("ent", r"회사명|법인명"), ("kind", r"매입유형"), ("item", r"품목|품명|원재료|원자재"),
            ("amt", r"매입액|금액|투입액"), ("pct", r"비중|비율"), ("use", r"용도"), ("supp", r"매입처|업체|구입처|공급사|공급처"), ("note", r"비고"))
NUMLIKE = re.compile(r"^\(?\s*-?[\d,]+(?:\.\d+)?\s*\)?\s*(?:\(\s*\d{1,3}(?:\.\d+)?\s*%\s*\))?\s*%?$")


def _nz(s):
    return re.sub(r"\s+", "", s or "")


PROD_HDR_KEY = re.compile(r"^(?:사업부문|사업구분|구분|부문|매출유형|품목|품명|제품|주요제품|구체적용도|용도|주요상표|상표|매출액|금액|비율|비중)")
PROD_COLS = (("seg", r"사업부문|사업구분|^구분$|^부문$"), ("kind", r"매출유형"), ("item", r"품목|품명|제품"), ("use", r"용도"),
             ("brand", r"상표"), ("amt", r"매출액|금액"), ("pct", r"비중|비율"))


def _hdr_like(cells, mode="mat"):
    """머리 행인가 — 머리 낱말 칸이 둘 이상이고 그중 품목 · 매입액 · 매입처(제품표는 품목 · 매출액 · 비율) 가운데 하나가 있다. '사 업 부 문' 처럼 띄어 써도."""
    if mode == "prod":
        keys = [c for c in cells if PROD_HDR_KEY.match(_nz(c))]
        # 매출액 · 비율 칸이 머리 다음 행으로 내려간 표(효성중공업 '제8기(당기)(2025년 1~12월)' · LG디스플레이 '2025년 연간')도 머리로 본다
        return len(keys) >= 2 and any(re.search(r"품목|품명|제품", _nz(c)) for c in cells) and \
            any(re.search(r"매출액|금액|비율|비중", _nz(c)) or PERIOD_HEAD.match(c.strip()) for c in cells)
    keys = [c for c in cells if HDR_KEY.match(_nz(c))]
    return len(keys) >= 2 and any(re.search(r"품목|품명|원재료|원자재|매입액|금액|매입처|공급", _nz(c)) for c in keys)


def materials(text):
    """주요 원재료 현황 표 — [{segment, kind, item, amt(백만원), pct, suppliers:[...]}].
    머리 행은 '사업부문'으로 시작하지 않아도 찾는다 — 머리 낱말이 둘 넘는 첫 행(CJ제일제당 '품 목 / 구체적용도 / 매입액',
    DB하이텍 · KG스틸 '매입유형 / …', HD현대중공업 '사 업 부 문 / 회 사 명 / 품 목 / 매 입 액(비 중)').
    칸 수가 머리보다 적은 행은 병합 칸이다 — 앞 · 뒤 어디가 빠졌는지 숫자 칸이 숫자로 떨어지는 자리를 골라 맞추고, 앞에서 빠진 칸은 위 행 값을 잇는다.
    표 가운데 다시 나온 머리 행(종속회사 표)은 그 머리로 다시 맞춘다. 표가 없으면 문장('주요 원재료는 Glass, 편광판 … 등이며')을 품목 하나로."""
    out = []
    for m in list(MAT_HEAD.finditer(text))[:4]:
        body = text[m.end():m.end() + 7000]
        end = re.search(r"\n\s*[나-하]\.\s|\n[^\n]{0,8}(?:주요\s*)?원\s*재\s*료\s*(?:등\s*의?\s*)?가\s*격|\n[^\n]{0,6}가격\s*변동\s*추이|\n\s*\(\d\)\s*생산|\n\s*[가-하]\.\s*생산|\n\s*\d\.\s*생산", body)
        body = body[:end.start()] if end else body
        rows = _rows(body)
        hi = next((i for i, r_ in enumerate(rows[:8]) if _hdr_like(r_)), None)
        if hi is None:
            continue
        got = _mat_rows(rows[hi:])
        if got:
            out = got
            break
    if not out:
        # 문장형(삼성전기): "주요 원재료는 PASTE/POWDER로 SHOEI, GUANGBO 등에서 매입"
        for m2 in re.finditer(r"주요\s*원재료는\s*([A-Za-z가-힣0-9/&\s]{2,40}?)[로으]로?\s*([A-Za-z가-힣0-9&,\s·]{2,80}?)\s*등?\s*(?:에서|으로부터|로부터)\s*(?:매입|구매|공급)", text):
            item, supp = m2.group(1).strip(), m2.group(2)
            if not any(x.get("item") == item for x in out):
                sl = [_clean_name(s) for s in re.split(r",|·|ㆍ", supp) if _clean_name(s)]
                out.append({"segment": None, "item": item, "amt": None, "pct": None, "suppliers": [{"name": s, "country": _country(s)} for s in sl]})
    if not out:
        # 문장형(LG디스플레이): "Display 패널 생산을 위한 주요 원재료는 Glass, 반도체류, 편광판, 유기물, Backlight, PCB 등이며"
        m3 = re.search(r"주요\s*원재료는\s*([^.\n]{3,140}?)\s*(?:등(?:이며|이고|입니다|이다|으로|을|이)|(?:이며|입니다))", text)
        if m3 and not re.search(r"다음과|아래|표", m3.group(1)):
            out.append({"segment": None, "kind": "문장", "item": m3.group(1).strip(" ,"), "amt": None, "pct": None, "suppliers": []})
    return out


PERIOD = re.compile(r"^(?:제\s*\d+\s*기|\d{4}\s*년?|당\s*기|전\s*기|전전기|\d{2}\s*년)$")
PERIOD_HEAD = re.compile(r"^(?:\[?\s*제\s*\d+\s*기|\d{4}\s*년|당\s*기|전\s*기|전전기)")      # 머리 칸 속 기수('제8기(당기)(2025년 1~12월)', '2025년 연간')


def _unspace(s):
    """한 글자씩 띄어 쓴 칸('대 두' · '원 당' · '조 선' · '사 업 부 문')을 붙인다."""
    if s and re.fullmatch(r"(?:[가-힣]{1,2}\s)+[가-힣]{1,2}", s.strip()):
        return re.sub(r"\s+", "", s)
    return s


def _item_ok(item):
    """원재료 품목 칸으로 쓸 만한가 — 문장('…습니다') · 기수('제51기', '(제26기)') · 숫자 · '※' 주석 · 지나치게 긴 칸은 아니다."""
    it = (item or "").strip()
    if not it or len(it) > 80 or it.startswith(("※", "-", "·", "*")):
        return False
    if re.search(r"습니다|있으며|입니다|하였|되었|않았", it) or re.search(r"제\s*\d+\s*기|^\(?\d{4}\s*년", it) or \
            re.search(r"단\s*가|사\s*용\s*량|비\s*용$|\(원/", it):         # 연료 · 단가 표가 이어 붙은 행(CJ제일제당 '경 유 비 용', '단가(원/ℓ)')
        return False
    return not re.match(r"^[\s\d,.%()~\-$/]+$", it)


def _mat_rows(rows, mode="mat"):
    """원재료 표(mode='mat') · 주요 제품 표(mode='prod') 행 읽기 — 머리로 칸을 정하고 병합 · 넘친 칸을 맞춘다."""
    COLS = PROD_COLS if mode == "prod" else MAT_COLS
    hdr = rows[0]
    ci = {}
    # 머리 다음 행이 기수뿐이면('제 18기 / 제 17기 / 제 16기') 머리 마지막 칸이 해마다 갈라진 것 — 머리를 넓힌다(E1 '매입물량')
    if len(rows) > 1 and len(rows[1]) >= 2 and all(PERIOD.match(x.strip()) for x in rows[1]):
        hdr = hdr[:-1] + ["%s %s" % (hdr[-1], x) for x in rows[1]]
        rows = [hdr] + rows[2:]
    # 머리에 기수가 섞이고 다음 행이 '매출액 / 비율(%)' 되풀이면(KG스틸 제품표) — 기수를 빼고 그 행을 머리 뒤에 붙인다(첫 짝 = 당기)
    elif len(rows) > 1 and any(PERIOD_HEAD.match(x.strip()) for x in hdr) and rows[1] and all(re.search(r"매출액|매입액|금액|비율|비중|%", x) for x in rows[1]):
        hdr = [x for x in hdr if not PERIOD_HEAD.match(x.strip())] + rows[1]
        rows = [hdr] + rows[2:]
    # 칸 하나가 빈 줄로 떨어져 따로 행이 된 것(SK하이닉스 '…SK하이닉스⏎⏎97,146,675(100%)') — 숫자 한 칸뿐인 행은 앞 행에 붙인다
    merged = [rows[0]]
    for r_ in rows[1:]:
        if len(r_) == 1 and NUMLIKE.match(r_[0].replace(" ", "")) and len(merged) > 1 and len(merged[-1]) < len(hdr):
            merged[-1] = merged[-1] + r_
        else:
            merged.append(r_)
    rows = merged

    def set_hdr(h):
        nonlocal hdr, ci
        hdr = h
        hz = [_nz(x) for x in h]
        ci = {k: next((i for i, x in enumerate(hz) if re.search(rx, x)), None) for k, rx in COLS}
        if mode == "mat" and ci["supp"] is None:   # 매입처 칸이 없으면 비고 칸에 적는 회사(한화오션: 'POSCO현대제철…')
            ci["supp"] = ci["note"]
            ci["supp_note"] = True
        if ci["amt"] is not None and ci["pct"] is not None and ci["amt"] == ci["pct"]:
            ci["pct"] = None              # '투입액(비율)' · '매입액(비중)' 한 칸
    set_hdr(hdr)
    if mode == "prod" and (ci["item"] is None or (ci["amt"] is None and ci["pct"] is None)):
        return []
    if mode == "mat" and ci["supp"] is None and ci["item"] is None:
        return []

    def fold(cells):
        """칸 수가 머리글보다 많으면 셀 안 줄바꿈이다('변압기 생산' + '변압기, 전동기 생산' / '포스코, 보무강철,' + '삼동, 티씨티 등').
        뒤에서부터 쉼표로 끝나는 줄 · 매입처처럼 보이는 연속 줄을 합친다."""
        is_use = lambda s: bool(re.search(r"(?:생산|제조|용|재료|부품|가공|조립)\s*$", s)) and not re.search(r",|\s등$", s)
        while len(cells) > len(hdr):
            j = next((i for i in range(len(cells) - 1) if cells[i].endswith(",")), None)
            if j is None:
                j = next((i for i in range(len(cells) - 1) if is_use(cells[i]) and is_use(cells[i + 1])), None)
            if j is None:
                cand = [i for i in range(len(cells) - 1) if not re.search(r"\d", cells[i]) and not re.search(r"\d", cells[i + 1])
                        and cells[i + 1] != "-" and len(cells[i]) < 30]
                if not cand:
                    break
                j = cand[-1]
            cells = cells[:j] + [cells[j] + " " + cells[j + 1]] + cells[j + 2:]
        return cells

    def score(row):
        """맞춘 행이 그럴듯한가 — 금액 · 비중 칸은 숫자, 품목 · 매입처 칸은 글자."""
        g = lambda k: row[ci[k]] if ci.get(k) is not None and ci[k] < len(row) else None
        sc = 0
        for k in ("amt", "pct"):
            v = g(k)
            if v is not None and v not in ("-", ""):
                sc += 2 if NUMLIKE.match(v.replace(" ", "")) else -3
        for k in ("item", "supp", "use", "seg", "kind"):
            v = g(k)
            if v is not None and v not in ("-", ""):
                sc += -3 if NUMLIKE.match(v.replace(" ", "")) else 1
        return sc

    out, prev = [], None
    seg = kind = None
    for cells in rows[1:]:
        if _hdr_like(cells, mode):
            set_hdr(cells)                # 표 가운데 다시 나온 머리(종속회사 표) — 그 머리로 다시 맞춘다
            prev = None
            continue
        if len(cells) < 2:
            continue                      # '(2) 종속회사 DB글로벌칩' 같은 소제목 · '(단위 : 백만원)'
        if all(PERIOD.match(x.strip()) for x in cells):
            continue
        if any(SUBTOTAL.match(_nz(x)) or SUBTOTAL.match(x.strip()) for x in cells):
            continue                      # 소계 · 합계 행 — 병합 칸을 위 행에서 이으면 품목처럼 보인다
        n = len(hdr)
        while len(cells) > n and NUMLIKE.match(cells[-1].replace(" ", "")) and NUMLIKE.match(cells[-2].replace(" ", "")):
            cells = cells[:-1]            # 머리 한 칸이 해마다 여러 칸으로 갈라진 표(E1 '매입물량' 제18 · 17 · 16기) — 뒤쪽 숫자를 덜어낸다
        cells = fold(cells)
        if len(cells) >= n:
            row = cells[:n]
        else:
            miss = n - len(cells)
            best = None
            for off in range(miss, -1, -1):          # 같은 점수면 뒤에 붙인(앞 칸이 병합된) 쪽 — 흔한 모양
                cand = [None] * off + cells + [None] * (miss - off)
                sc = score(cand)
                if best is None or sc > best[0]:
                    best = (sc, cand, off)
            row, off = best[1], best[2]
            if best[0] < 0:
                continue                  # 어떻게 맞춰도 숫자 · 글자 칸이 엇갈리는 행
            if prev:
                for i in range(off):
                    row[i] = prev[i]                # 앞에서 빠진(병합된) 칸은 위 행 값을 잇는다
        g = lambda k: (row[ci[k]] if ci.get(k) is not None and ci[k] < len(row) else None)
        if g("seg"):
            seg = g("seg")
        if g("kind"):
            kind = g("kind")
        item, amt, pct, supp = g("item"), g("amt"), g("pct"), g("supp")
        prev = row
        if not item or re.search(r"합\s*계|소\s*계", (item or "") + " " + (seg or "")) or re.fullmatch(r"품\s*목|원\s*재\s*료\s*명?|구\s*분|매입\s*유형|원자재|-", item):
            continue
        if NUMLIKE.match(item.replace(" ", "")) or not _item_ok(item):
            continue                      # 맞춤이 어긋나 숫자 · 기수 · 문장이 품목 칸에 온 행(가격 변동 표가 이어 붙은 것 포함)
        if seg and (PERIOD.match(seg.strip()) or re.match(r"^[\s\d,.%()~\-$]+$", seg) or re.search(r"\d{4}\s*년", seg)):
            continue
        amt_v = pct_v = None
        if amt and re.fullmatch(r"\s*\d{1,3}(?:\.\d+)?\s*%\s*", amt):
            pct, amt = amt, None          # '매입액(비율)' 칸에 비율만 적은 행(E1 'LNG 98.1%')
        if amt and re.search(r"\d", amt):
            mm = re.match(r"\(?\s*([\d,]+)\s*\)?\s*(?:\(\s*(\d{1,3}(?:\.\d+)?)\s*%\s*\))?", amt.strip())
            if mm and mm.group(1).replace(",", ""):
                amt_v = float(mm.group(1).replace(",", ""))
                if mm.group(2):
                    pct_v = float(mm.group(2))
        if pct and re.search(r"\d", pct):
            pv = float(re.search(r"(\d{1,3}(?:\.\d+)?)", pct).group(1))
            pct_v = pv if pv <= 100 else pct_v
        if mode == "prod":
            if amt_v is None and pct_v is None:
                continue
            out.append({"segment": _unspace(seg), "kind": kind, "item": _unspace(item), "use": g("use"), "amt": amt_v, "pct": pct_v})
            continue
        if supp and not re.search(r"[,·ㆍ/]", supp) and len(re.sub(r"\s*등\s*$", "", supp)) > 14:
            supp = _split_glued(supp)      # 줄바꿈 없이 붙은 이름들(POSCO현대제철동국제강HD현대중공업한화엔진두산에너빌리티 등)
        # 칸 안에서 '외'로 이어 적은 이름('TOM GREYHOUND 외 예진에프앤지㈜', '대광직물㈜ 외㈜해성인터내셔날')도 가른다
        sl = [x for x in (_supp_name(x) for x in re.split(r",|·|ㆍ|/|\s등|\s+(?:외|外)\s*(?=㈜|\(주\)|[가-힣A-Z])", supp or "")) if _supplier_ok(x)] if supp else []
        item, seg = _unspace(item), _unspace(seg)
        out.append({"segment": seg, "kind": kind, "item": item, "amt": amt_v, "pct": pct_v, "_note": bool(ci.get("supp_note")),
                    "suppliers": [{"name": x, "country": _country(x)} for x in sl if len(x) <= 40]})
    # 비고 칸을 매입처로 읽은 행 — 표 전체에서 회사 이름처럼 보이는 것이 하나도 없으면 품목 메모다
    # (KG스틸 비고 'BP, GI, SGL, AL' · '페인트' 는 버리고, DB하이텍 비고 'Siltron, Shin-Etsu' · '동우화인켐' 은 살린다)
    nr = [r for r in out if r.get("_note")]
    if nr and not any(NOTE_SUPP.search(s["name"]) or s["name"] in KNOWN_CO for r in nr for s in r["suppliers"]):
        for r in nr:
            r["suppliers"] = []
    for r in out:
        r.pop("_note", None)
    return out


KNOWN_CO = ["POSCO", "포스코", "현대제철", "동국제강", "HD현대중공업", "현대중공업", "HD현대", "한화엔진", "HSD엔진", "두산엔진", "두산에너빌리티", "두산중공업",
            "삼성전자", "LG전자", "SK하이닉스", "현대자동차", "세아제강", "고려아연", "LS전선", "대한전선", "효성", "두산", "한화", "삼성", "현대",
            "SONY", "TORAY", "MITSUBISHI"]


SUPP_JUNK = re.compile(r"^(?:비\s*고|주요\s*매입처|매입처|업체명|구입처|공급사|합\s*계|소\s*계|LTD\.?|INC\.?|CO\.?|CORP\.?|외|기타|국내|해외|수입|직수입|당사|자체\s*생산|자가\s*생산)$", re.I)
SUPP_JUNK_IN = re.compile(r"장부가액|환율변동|당기증감|상각|기말|기초|단위\s*:|백만원\s*$|\d[\d,]*\s*(?:백만\s*원|억\s*원|천\s*원)\s*$")


def _supplier_ok(x):
    """매입처 이름으로 쓸 만한가 — 숫자 · 비율 조각('2', '129', '305(29.8%)', '11.6%'), 용도 문구('플랜트 용', '특수선박 건조용'),
    표 머리글 조각('비고', '주요 매입처', '당기증감 당기상각 …'), 법인 꼬리만 남은 것('LTD'), 금액이 붙은 이름은 뺀다."""
    if not x or x == "-" or BAD_NAME.match(x) or SUPP_JUNK.match(x) or SUPP_JUNK.match(re.sub(r"\s+", "", x)) or SUPP_JUNK_IN.search(x):
        return False
    if name_kind(x) is None or re.search(r"계열회사|입니다|^주\s*\d|비율|계약\s*\(", x):
        return False
    if re.fullmatch(r"[\d,.\s()%]+", x):
        return False
    if re.search(r"(?:용|생산|제조|건조용|가공|소재|자재|필름|부품)\s*$", x) and not re.search(r"[A-Za-z]|㈜|\(주\)", x):
        return False
    if len(x) < 2 or len(x) > 40:
        return False
    return True


def _supp_name(x):
    """매입처 이름 — '롯데케미칼 외' · '(주)덕진 外' · '금강석유(주) 外 3개사' 의 꼬리를 뗀다(상장사와 이어지게)."""
    x = _clean_name(x)
    x = re.sub(r"\s*(?:외|外)\s*(?:\d+\s*(?:개사|곳|社))?\s*$", "", x).strip()
    x = re.sub(r"(?<=[가-힣A-Za-z)㈜])(?:외|外)$", "", x).strip()
    return x


def _strip_amount(x):
    """'포스코인터내셔널 231,928백만원' → '포스코인터내셔널'. 이름 뒤에 금액이 붙은 표."""
    return re.sub(r"\s*\(?\d[\d,]*\s*(?:백만\s*원|억\s*원|천\s*원|원)\)?\s*$", "", x or "").strip()


def _split_glued(s):
    """'POSCO현대제철동국제강HD현대중공업한화엔진두산에너빌리티 등' → 'POSCO, 현대제철, 동국제강, …'. 아는 이름부터 긴 것 순으로 뗀다."""
    s = re.sub(r"\s*등\s*$", "", s.strip())
    out, i = [], 0
    names = sorted(KNOWN_CO, key=len, reverse=True)
    while i < len(s):
        hit = next((n for n in names if s.startswith(n, i)), None)
        if hit:
            out.append(hit)
            i += len(hit)
        else:
            # 모르는 이름 — 다음 아는 이름이 나올 때까지
            j = i + 1
            while j < len(s) and not any(s.startswith(n, j) for n in names):
                j += 1
            out.append(s[i:j])
            i = j
    return ", ".join(x for x in out if x.strip())


def export_split(text):
    """별도(또는 연결) 매출실적 표의 수출 · 내수 합계 — {export, domestic, year_cols} 가장 최근 기만."""
    m = re.search(r"매출실적", text)
    if not m:
        return None
    body = text[m.start():m.start() + 6000]
    def num(s):
        s = s.replace(",", "")
        return float(s) if re.fullmatch(r"\d+", s) else None
    # 연결 · 별도 표가 둘이면(효성: 연결엔 수출 · 내수 줄이 없고 별도에만 있다 / 삼성전기: 연결에 있다) 수출 · 내수 줄이 있는 첫 표를 쓴다
    parts = re.split(r"(?=\d\)\s*(?:연결|별도)\s*기준\s*매출실적|(?=별도\s*기준\s*매출실적))", body)
    body = next((p for p in parts if re.search(r"\n수\s*출\s*\n", p)), body)
    # 합계 행 — 당기 칸은 첫 숫자. 연도 칸이 셋이라 '합 계\n수 출\n(당기)\n(전기)\n(전전기)\n\n내 수\n(당기)…' 모양
    tot = re.search(r"합\s*계\s*\n+\s*수\s*출\s*\n+([\d,\-]+)[\s\S]{0,200}?내\s*수\s*\n+([\d,\-]+)", body)
    if tot:
        more = re.search(r"합\s*계\s*\n+\s*수\s*출\s*\n+([\d,\-]+)[\s\S]{0,200}?내\s*수\s*\n+([\d,\-]+)", body[tot.end():])
        tot = tot if not more else tot     # 부문별 합계가 여럿이면 첫 '합 계' 가 그 부문 — 전체 합계는 마지막. 아래서 다시 고른다
        last = None
        for mm in re.finditer(r"합\s*계\s*\n+\s*수\s*출\s*\n+([\d,\-]+)[\s\S]{0,200}?내\s*수\s*\n+([\d,\-]+)", body):
            last = mm
        tot = last
    if tot:
        ex, do = num(tot.group(1)), num(tot.group(2))
    else:
        # 합계 행이 없으면 부문별 행의 당기 수출 · 내수를 더한다(한화오션)
        exs = [num(x) for x in re.findall(r"\n수\s*출\s*\n([\d,]+)", body)]
        dos = [num(x) for x in re.findall(r"\n내\s*수\s*\n([\d,]+)", body)]
        exs, dos = [v for v in exs if v], [v for v in dos if v]
        if not exs:
            return None
        ex, do = sum(exs), sum(dos)
    if ex is None or do is None or ex + do <= 0:
        return None
    return {"export": ex * 1e6, "domestic": do * 1e6, "export_pct": ex / (ex + do) * 100}


def competitors(text):
    """경쟁 서술 — 이름을 뽑지 않고(대개 '중국 경쟁사' 같은 서술) 경쟁사 · 경쟁업체 · 경쟁 심화가 든 문장을 그대로 모은다."""
    out, seen = [], set()
    for m in re.finditer(r"[^.\n]{0,160}(?:경쟁\s*(?:사|업체|기업|회사)|가격\s*경쟁|후발\s*업체|선진\s*업체|점유율)[^.\n]{0,160}[.다]", text):
        s = re.sub(r"\s+", " ", m.group(0)).strip()
        k = s[:40]
        if 30 <= len(s) <= 360 and k not in seen and not re.search(r"경쟁력을\s*(?:확보|강화|좌우|갖추)|경쟁력\s*(?:강화|확보|제고)", s):
            seen.add(k)
            out.append(s)
    return out[:8]


PROD_HEAD = re.compile(r"주요\s*제\s*품\s*(?:등\s*의?\s*)?(?:현\s*황|매\s*출|및\s*서비스)[^\n]{0,40}\n")


def products(text):
    """주요 제품 등의 현황 — 무엇을 팔아 매출을 내나 [{segment, kind, item, use, amt(백만원), pct}].
    머리 '사업부문 / 매출유형 / 품목 / 구체적용도 / 주요상표 / 매출액(비율)'(CJ제일제당 · SK하이닉스 · HD현대중공업 '매 출 액(비 율)'),
    기수마다 갈라진 머리(KG스틸 '제44기 · 제43기 …' 다음 '매출액 / 비율(%)')는 첫 짝(당기)을 쓴다."""
    for m in list(PROD_HEAD.finditer(text))[:4]:
        body = text[m.end():m.end() + 6000]
        end = re.search(r"\n\s*[나-하]\.\s|\n\s*\d\.\s", body)
        body = body[:end.start()] if end else body
        rows = _rows(body)
        hi = next((i for i, r_ in enumerate(rows[:8]) if _hdr_like(r_, "prod")), None)
        if hi is None:
            continue
        got = _mat_rows(rows[hi:], "prod")
        if got:
            return got[:20]
    return []


CHAN_HEAD = re.compile(r"판매\s*경로[^\n]{0,40}\n")


def channels(text):
    """판매경로 비중 — 고객 이름을 안 적는 회사의 '누구에게 파나'를 대신한다 [{name, desc, pct}].
    CJ제일제당 '경로구분 / 주요 거래처 유형 / 매출비중'('대리점 · 전문점,복합점,식당전문점 등 · 18.9'), 문장 '판매경로는 직판 70%, 대리점 30%'."""
    for m in list(CHAN_HEAD.finditer(text))[:3]:
        body = text[m.end():m.end() + 2500]
        rows = _rows(body)
        hi = next((i for i, r_ in enumerate(rows[:6]) if any(re.search(r"경로|구분", _nz(x)) for x in r_)
                   and any(re.search(r"비중|비율", _nz(x)) for x in r_) and len(r_) >= 2), None)
        if hi is not None:
            hz = [_nz(x) for x in rows[hi]]
            wide = sum(1 for x in hz if re.search(r"직판|대리점|특약점|도매|소매|관계회사|온라인", x)) >= 2
            out = []
            if not wide:                  # 긴 꼴만 — 경로가 칸 머리로 늘어선 넓은 꼴(LS ELECTRIC '직판 / 관계회사 / 특약점')은 건너뛴다
                for cells in rows[hi + 1:hi + 16]:
                    if len(cells) < 2 or SUBTOTAL.match(_nz(cells[0])) or re.match(r"^\(?단위|^※|^주\d", cells[0]):
                        continue
                    nums = [x for x in cells[1:] if re.fullmatch(r"\s*\d{1,3}(?:\.\d+)?\s*%?\s*", x)]
                    if not nums:
                        if out:
                            break
                        continue
                    pv = float(re.search(r"\d{1,3}(?:\.\d+)?", nums[0]).group(0))
                    if pv > 100:
                        continue
                    desc = next((x for x in cells[1:] if not re.search(r"\d", x) and x != "-"), None)
                    if re.search(r"비중|비율|÷|합\s*계", cells[0]):
                        continue          # '해외매출 비중(해외매출÷전체매출)' 같은 집계 행
                    out.append({"name": cells[0][:30], "desc": (desc or "")[:60], "pct": pv})
                    if sum(x["pct"] for x in out) >= 99:
                        break             # 한 표가 100%를 채우면 끝(LG디스플레이처럼 해외 · 국내 표가 이어 붙은 꼴에서 둘째 표를 섞지 않게)
            if out:
                return out[:8]
        seg = text[m.end():m.end() + 400]
        got = [(nm, p) for nm, p in _names_in(seg.split("\n\n")[0]) if len(nm) <= 20]
        # 문장형은 경로 낱말일 때만(직판 · 대리점 · 온라인 …) — 판매경로 제목 밑의 매출처 이름(TANTRANSCO 3.2%)을 경로로 읽지 않게
        chan = [g for g in got if re.search(r"직판|직접|대리점|특약점|도매|소매|온라인|오프라인|수출|내수|위탁|유통|홈쇼핑|할인점|편의점|백화점|"
                                            r"마트|면세|관수|조달|B2B|B2C|OEM|로컬|해외|국내|자사|가맹|딜러|총판|상사", g[0], re.I)]
        if len(chan) >= 2 and len(chan) * 2 >= len(got):
            return [{"name": nm, "desc": "", "pct": p} for nm, p in chan[:8]]
    return []


def extract(text):
    return {"customers": customers(text), "subs": subsidiaries(text), "segments": segments(text),
            "materials": materials(text), "products": products(text), "channels": channels(text),
            "export": export_split(text), "competitors": competitors(text)}
