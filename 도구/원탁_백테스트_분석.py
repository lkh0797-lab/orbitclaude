import json, sys, math, statistics as st
rows = json.load(open(sys.argv[1] if len(sys.argv) > 1 else 'bt.json', encoding='utf-8'))
print('rows', len(rows), 'companies', len({r['code'] for r in rows}))


def rank(v):
    s = sorted(range(len(v)), key=lambda i: v[i])
    r = [0] * len(v)
    for k, i in enumerate(s):
        r[i] = k
    return r


def spear(a, b):
    p = [(x, y) for x, y in zip(a, b) if x is not None and y is not None and math.isfinite(x) and math.isfinite(y)]
    if len(p) < 10:
        return None, len(p)
    x, y = zip(*p)
    rx, ry = rank(x), rank(y)
    mx, my = st.mean(rx), st.mean(ry)
    num = sum((i - mx) * (j - my) for i, j in zip(rx, ry))
    den = math.sqrt(sum((i - mx) ** 2 for i in rx) * sum((j - my) ** 2 for j in ry))
    return (num / den if den else None), len(p)


def within(key_x, key_y):
    """회사 안에서의 순위 상관 평균 — 종목별 수준 차이(대세 상승주)를 걷어낸다."""
    by = {}
    for r in rows:
        by.setdefault(r['code'], []).append(r)
    cs = []
    for code, rs in by.items():
        c, n = spear([gx(r, key_x) for r in rs], [gx(r, key_y) for r in rs])
        if c is not None:
            cs.append(c)
    return (st.mean(cs) if cs else None), len(cs)


def gx(r, k):
    if k.startswith('ty.'):
        return r['ty'].get(k[3:], 0.0)
    if k.startswith('c.'):
        return r['c'].get(k[2:])
    return r.get(k)


for y in ('f1', 'f3', 'f6', 'fnext'):
    print('\n== 앞으로', y)
    for x in ('M', 'c.드러켄밀러', 'c.버핏', 'c.린치', 'c.멍거', 'ty.momentum', 'ty.story', 'ty.quality', 'ty.valuation', 'ty.risk',
              'prevc', 'pre', 'per', 'g', 'a', 'lag'):
        a, n = spear([gx(r, x) for r in rows], [r[y] for r in rows])
        w, m = within(x, y)
        print('  %-14s pooled %s (n=%d)   within-company %s (%d cos)' % (x, 'None' if a is None else '%+.3f' % a, n, 'None' if w is None else '%+.3f' % w, m))

print('\n== 선반영: 펀더멘털 논거와 이미 움직인 주가')
for x in ('ty.momentum', 'ty.quality', 'M'):
    for y in ('prevc', 'pre'):
        a, n = spear([gx(r, x) for r in rows], [r[y] for r in rows])
        print('  %s ~ %s  %+.3f (n=%d)' % (x, y, a, n))

print('\n== 결론별 공시 뒤 3개월 중앙값')
by = {}
for r in rows:
    by.setdefault(r['verdict'], []).append(r['f3'])
for k, v in sorted(by.items(), key=lambda kv: -len(kv[1])):
    v = [x for x in v if x is not None]
    if v:
        print('  %-18s n=%3d  med %+.1f%%  up %.0f%%' % (k, len(v), st.median(v), 100 * sum(1 for x in v if x > 0) / len(v)))
lags = [r['lag'] for r in rows if r['lag'] is not None]
print('\n공시 지연(분기말→공시) 중앙값 %.0f일' % st.median(lags))
