"""
fetch_vip.py  (v3)
─────────────────────────────────────────────────────────────
핵심 교훈: DART list.json은 '제출인 이름'으로 필터링을 지원하지 않는다.
그래서 기간 내 대량보유(5%) 공시를 받아온 뒤, 응답의 flr_nm(제출인) 칸을
코드에서 직접 검사해 추적 대상 운용사 것만 골라낸다.
골라낸 소수 건에 대해서만 majorstock(보유비율 상세)을 호출하므로 빠르다.
"""

import os
import sys
import json
import time
import datetime as dt

import requests

DART_KEY = os.environ["DART_API_KEY"]
DART = "https://opendart.fss.or.kr/api"

# ── 추적 대상. 처음엔 VIP 하나. 나중에 한 줄씩 추가. ──
WATCH_FIRMS = [
    "브이아이피자산운용",
    # "라이프자산운용",
    # "머스트자산운용",
]

LOOKBACK_DAYS = 80          # corp 미지정 시 최대 3개월(약 90일)까지만 허용됨
OUT_PATH = "docs/data.json"

s = requests.Session()
s.headers.update({"User-Agent": "vip-tracker/0.3"})


def get(endpoint, **params):
    params["crtfc_key"] = DART_KEY
    for i in range(3):
        try:
            r = s.get(f"{DART}/{endpoint}", params=params, timeout=20)
            return r.json()
        except Exception as e:  # noqa
            print(f"[retry {i}] {endpoint}: {e}", file=sys.stderr)
            time.sleep(1.5 * (i + 1))
    return {"status": "999", "list": []}


def fetch_list(bgn, end):
    """기간 내 지분공시(pblntf_ty='D') 전체. 제출인 필터는 코드에서 따로."""
    out, page = [], 1
    while True:
        d = get("list.json", bgn_de=bgn, end_de=end, pblntf_ty="D",
                page_no=page, page_count=100, sort="date", sort_mth="desc")
        st = d.get("status")
        if st == "013":
            break
        if st != "000":
            print(f"[warn] list status={st} msg={d.get('message')}", file=sys.stderr)
            break
        out.extend(d.get("list", []) or [])
        tp = int(d.get("total_page", 1) or 1)
        if page >= tp:
            break
        page += 1
        time.sleep(0.2)
    return out


def firm_in(name):
    if not name:
        return None
    for f in WATCH_FIRMS:
        if f in name:
            return f
    return None


def major_detail(corp_code, rcept_no):
    d = get("majorstock.json", corp_code=corp_code)
    rows = d.get("list", []) or []
    for row in rows:
        if row.get("rcept_no") == rcept_no:
            return row
    return rows[0] if rows else {}


def main():
    today = dt.date.today()
    bgn = (today - dt.timedelta(days=LOOKBACK_DAYS)).strftime("%Y%m%d")
    end = today.strftime("%Y%m%d")

    rows = fetch_list(bgn, end)
    print(f"[info] 지분공시 {len(rows)}건 스캔")

    items, seen = [], set()
    for row in rows:
        if "대량보유상황보고서" not in row.get("report_nm", ""):
            continue
        firm = firm_in(row.get("flr_nm", ""))   # ← 제출인 칸을 코드에서 직접 검사
        if not firm:
            continue
        rcept_no = row["rcept_no"]
        if rcept_no in seen:
            continue
        seen.add(rcept_no)

        detail = major_detail(row.get("corp_code", ""), rcept_no) if row.get("corp_code") else {}
        rdt = row.get("rcept_dt", "")
        items.append({
            "rcept_no": rcept_no,
            "rcept_dt": f"{rdt[:4]}-{rdt[4:6]}-{rdt[6:]}" if len(rdt) == 8 else rdt,
            "firm": firm,
            "corp_name": row.get("corp_name", ""),
            "stock_code": row.get("stock_code", ""),
            "stkrt": detail.get("stkrt", ""),
            "stkrt_prev": "",
            "stkrt_irds": detail.get("stkrt_irds", ""),
            "report_resn": detail.get("report_resn", ""),
            "report_nm": row.get("report_nm", ""),
        })

    payload = {
        "updated_at": dt.datetime.now(dt.timezone(dt.timedelta(hours=9))).isoformat(timespec="minutes"),
        "is_seed": False,
        "firms": WATCH_FIRMS,
        "disclosures": items,
    }
    os.makedirs(os.path.dirname(OUT_PATH), exist_ok=True)
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    print(f"[info] {len(items)}건 기록 → {OUT_PATH}")


if __name__ == "__main__":
    main()
