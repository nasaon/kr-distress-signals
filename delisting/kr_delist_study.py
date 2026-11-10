# -*- coding: utf-8 -*-
"""[국내 상폐 연구 — 생존편향 직공] KRX 상장폐지 목록(KIND/FDR) × OpenDART 과거 재무.
질문: ①상폐가 얼마나 흔한가(연도별·퇴출성 사유) ②퇴출성 상폐 기업은 '직전 사업보고서'에서
재무 레드플래그(완전자본잠식/자본잠식50%+/2년 연속 영업적자/보고서 미제출)로 사전 포착됐는가
③현 확대 유니버스(시총 상위)에 지금 플래그 걸린 종목은 — 듀얼모멘텀 TOP10의 '파산보험 게이트' 근거.
정직성: 게이트는 알파 개선이 아니라 꼬리 보험(기존 결론 유지) — 여기선 보험의 '적중률'을 상폐 실데이터로 정량화.
키: 환경변수 DART_API_KEY (OpenDART 인증키) · corp 매핑 캐시 _dart_corp.csv · 로그 KR_DELIST_LOG.txt
"""
import os, sys, io, time, zipfile, json
import xml.etree.ElementTree as ET
import numpy as np, pandas as pd, requests
try: sys.stdout.reconfigure(encoding="utf-8")
except Exception: pass

HERE = os.path.dirname(os.path.abspath(__file__))
def dart_key():
    key = os.getenv("DART_API_KEY", "").strip()
    if not key:
        raise SystemExit("환경변수 DART_API_KEY에 OpenDART 인증키를 넣으세요")
    return key


KEY = dart_key()
S = requests.Session()


def corp_map():
    cache = os.path.join(HERE, "_dart_corp.csv")
    if os.path.exists(cache):
        df = pd.read_csv(cache, dtype=str)
    else:
        r = S.get("https://opendart.fss.or.kr/api/corpCode.xml", params={"crtfc_key": KEY}, timeout=60)
        z = zipfile.ZipFile(io.BytesIO(r.content))
        root = ET.fromstring(z.read(z.namelist()[0]))
        rows = [(e.findtext("corp_code"), e.findtext("corp_name"), (e.findtext("stock_code") or "").strip())
                for e in root.iter("list")]
        df = pd.DataFrame(rows, columns=["corp_code", "corp_name", "stock_code"])
        df.to_csv(cache, index=False)
    df = df[df["stock_code"].astype(str).str.len() == 6]
    return dict(zip(df["stock_code"], df["corp_code"]))


def fin_flags(corp_code, year):
    """사업보고서 주요계정 → (플래그 dict) 또는 None(미제출/무데이터)."""
    try:
        r = S.get("https://opendart.fss.or.kr/api/fnlttSinglAcnt.json",
                  params={"crtfc_key": KEY, "corp_code": corp_code, "bsns_year": str(year), "reprt_code": "11011"},
                  timeout=20)
        j = r.json()
        if j.get("status") != "000": return None
        rows = j.get("list", [])
        def pick(nm):
            for fs in ("OFS", "CFS"):
                for x in rows:
                    if x.get("account_nm") == nm and x.get("fs_div") == fs:
                        try: return float(str(x.get("thstrm_amount", "")).replace(",", ""))
                        except Exception: pass
            return None
        cap_tot = pick("자본총계"); cap = pick("자본금"); op = pick("영업이익")
        return dict(cap_tot=cap_tot, cap=cap, op=op)
    except Exception:
        return None


def red(f1, f2):
    """f1=직전연도, f2=그 전년. 레드플래그 판정."""
    if f1 is None: return "보고서없음"
    fl = []
    if f1["cap_tot"] is not None and f1["cap_tot"] <= 0: fl.append("완전자본잠식")
    elif f1["cap_tot"] is not None and f1["cap"] and f1["cap"] > 0 and (f1["cap"] - f1["cap_tot"]) / f1["cap"] > 0.5:
        fl.append("자본잠식50%+")
    if f1["op"] is not None and f1["op"] < 0 and f2 and f2["op"] is not None and f2["op"] < 0:
        fl.append("영업적자 2년+")
    return "·".join(fl) if fl else "-"


def main():
    import FinanceDataReader as fdr
    cmap = corp_map()
    L = ["[국내 상폐 연구 — KRX 상폐목록 × OpenDART 직전 재무]"]

    dl = fdr.StockListing("KRX-DELISTING")
    dl = dl[dl["SecuGroup"] == "주권"].copy()
    dl["DelistingDate"] = pd.to_datetime(dl["DelistingDate"])
    dl = dl[(dl["DelistingDate"] >= "2016-01-01") & (dl["Market"].isin(["KOSPI", "KOSDAQ"]))]
    merger = dl["Reason"].astype(str).str.contains("합병|이전상장|자진|스팩|주식교환|완전자회사|지주|포괄적|유가증권시장으로|해산사유\\(존속기한", na=False) | dl["ToSymbol"].notna()
    forced = dl[~merger]
    L.append(f"  2016~2026 주권 상폐 총 {len(dl)}건 — 비퇴출(합병·이전·자진 등) {int(merger.sum())} · ★퇴출성 {len(forced)}건")
    yr_cnt = forced.groupby(forced["DelistingDate"].dt.year).size()
    L.append("  퇴출성 연도별: " + " ".join(f"{y}:{c}" for y, c in yr_cnt.items()))
    top_r = forced["Reason"].value_counts().head(6)
    L.append("  주요 사유: " + " · ".join(f"{k}({v})" for k, v in top_r.items()))
    n_bench = 308  # 확대 유니버스 크기
    L.append(f"  연평균 퇴출 {yr_cnt.mean():.0f}건 — 상장 ~2600종 대비 {yr_cnt.mean()/2600*100:.1f}%/년 (시총상위 {n_bench}종엔 훨씬 드묾)")
    L.append("")

    # ── ② 퇴출성 상폐 표본 → 직전 사업보고서 레드플래그 적중률 ──
    sample = forced.sort_values("DelistingDate", ascending=False)
    sample = sample[sample["Symbol"].isin(cmap.keys())].head(120)
    hits = {"완전자본잠식": 0, "자본잠식50%+": 0, "영업적자 2년+": 0, "보고서없음": 0}
    flagged = 0; total = 0; examples = []
    for _, r in sample.iterrows():
        dy = r["DelistingDate"].year
        cc = cmap[r["Symbol"]]
        f1 = fin_flags(cc, dy - 1); time.sleep(0.08)
        f2 = fin_flags(cc, dy - 2); time.sleep(0.08)
        tag = red(f1, f2)
        total += 1
        if tag != "-":
            flagged += 1
            for k in hits:
                if k in tag: hits[k] += 1
            if len(examples) < 8: examples.append(f"{r['Name']}({dy}: {tag})")
    L.append(f"② 퇴출성 상폐 {total}곳(최근순)의 '상폐 전년 사업보고서' 레드플래그")
    L.append(f"  ★사전 포착률: {flagged}/{total} = {flagged/max(total,1)*100:.0f}%  (완전잠식 {hits['완전자본잠식']} · 잠식50%+ {hits['자본잠식50%+']} · 영업적자2년+ {hits['영업적자 2년+']} · 보고서미제출 {hits['보고서없음']})")
    L.append("  예: " + " / ".join(examples))
    L.append("")

    # ── ③ 현 확대 유니버스 스캔 (2025 사업보고서) ──
    uni = pd.read_csv(os.path.join(HERE, "kr_universe2.csv"), dtype={"code": str})
    bad = []
    scanned = 0
    for _, r in uni.iterrows():
        cc = cmap.get(r["code"])
        if not cc: continue
        f1 = fin_flags(cc, 2025); time.sleep(0.06)
        f2 = fin_flags(cc, 2024); time.sleep(0.06)
        tag = red(f1, f2)
        scanned += 1
        if tag not in ("-",):
            bad.append(f"{r['name']}({tag})")
    L.append(f"③ 현 확대 유니버스 {scanned}종 스캔(2025 사업보고서 기준)")
    L.append(f"  플래그 종목 {len(bad)}개: " + (" · ".join(bad) if bad else "없음"))
    L.append("")
    L.append("결론(게이트 설계): 듀얼모멘텀 유니버스에서 [완전자본잠식·자본잠식50%+·영업적자 2년+·보고서 미제출] 제외.")
    L.append("  성격 = 알파 아님·꼬리(상폐) 보험 — ②의 사전 포착률이 보험 적중률, ③이 보험료(제외 종목 수).")
    txt = "\n".join(L)
    print(txt)
    open(os.path.join(HERE, "KR_DELIST_LOG.txt"), "w", encoding="utf-8").write(txt + "\n")


if __name__ == "__main__":
    main()
