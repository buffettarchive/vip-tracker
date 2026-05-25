"""
fetch_vip.py  (v2)
─────────────────────────────────────────────────────────────
브이아이피자산운용 등 추적 대상 운용사가 '보고자'로 들어간
대량보유(5%) 공시만 골라 docs/data.json 을 갱신한다.

v1과의 차이:
- 시장 전체 지분공시를 다 받지 않고, 운용사명으로 직접 검색해
  해당 운용사가 제출한 공시만 받아온다. → 빠르고 가볍다.
- 검색기간 3개월 제한을 피하려고 80일로 잡는다.
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

LOOKBACK_DAYS = 80
OUT_PATH = "docs/data.json"

s = requests.Session()
s.headers.update({"User-Agent": "vip-tracker/0.2"})


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


def fetch_by_filer(firm, bgn, end):
    """
    공시 제출인명(flr_nm)으로 직접 검색 → 그 운용사가 제출한 공시만.
    list.json은 flr_nm 파라미터로 제출인 검색을 지원한다.
    """
    out, page = [], 1
    while True:
        d = get("list.json", flr_nm=firm, bgn_de=bgn, end_de=end,
                pblntf_ty="D", page_no=page, page_count=100,
                sort="date", sort_mth="desc")
        st = d.get("status")
        if st == "013":          # 해당 조건 데이터 없음
            break
        if st != "000":
            print(f"[warn] {firm} status={st} msg={d.get('message')}", file=sys.stderr)
            break
        out.extend(d.get("list", []) or [])
        tp = int(d.get("total_page", 1) or 1)
        if page >= tp:
            break
        page += 1
        time.sleep(0.3)
    return out


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

    items, seen = [], set()
    total_scanned = 0

    for firm in WATCH_FIRMS:
        rows = fetch_by_filer(firm, bgn, end)
        total_scanned += len(rows)
        print(f"[info] '{firm}' 제출 공시 {len(rows)}건")

        for row in rows:
            if "대량보유상황보고서" not in row.get("report_nm", ""):
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

    print(f"[info] 제출공시 {total_scanned}건 스캔")
    print(f"[info] {len(items)}건 기록 → {OUT_PATH}")


if __name__ == "__main__":
    main()
