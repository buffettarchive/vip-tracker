"""
fetch_vip.py
─────────────────────────────────────────────────────────────
브이아이피자산운용의 대량보유(5%) 공시만 DART에서 긁어
docs/data.json 을 갱신한다. GitHub Actions가 주기적으로 실행하고,
변경분을 레포에 커밋 → GitHub Pages가 그 JSON을 읽어 화면에 표시한다.

DB도 서버도 없는 최소 구성. 추적 운용사를 늘리고 싶으면
WATCH_FIRMS에 한 줄 추가하면 된다.
"""

import os
import sys
import json
import time
import datetime as dt

import requests

DART_KEY = os.environ["DART_API_KEY"]
DART = "https://opendart.fss.or.kr/api"

# ── 추적 대상. 처음엔 VIP 하나로 시작. 나중에 여기에 한 줄씩 추가. ──
# 주의: "브이아이피자산운용"으로 정확히. "브이아이자산운용"(다른 회사)과 혼동 금지.
WATCH_FIRMS = [
    "브이아이피자산운용",
    # "라이프자산운용",
    # "머스트자산운용",
]

LOOKBACK_DAYS = 80          # 최근 90일 공시를 매번 다시 스캔(중복은 rcept_no로 제거)
OUT_PATH = "docs/data.json"

s = requests.Session()
s.headers.update({"User-Agent": "vip-tracker/0.1"})


def get(endpoint, **params):
    params["crtfc_key"] = DART_KEY
    for i in range(3):
        try:
            r = s.get(f"{DART}/{endpoint}", params=params, timeout=15)
            return r.json()
        except Exception as e:  # noqa
            print(f"[retry {i}] {endpoint}: {e}", file=sys.stderr)
            time.sleep(1.5 * (i + 1))
    return {"status": "999", "list": []}


def firm_in(name: str):
    if not name:
        return None
    for f in WATCH_FIRMS:
        if f in name:
            return f
    return None


def fetch_list(bgn, end):
    """기간 내 지분공시(pblntf_ty='D') 전체."""
    out, page = [], 1
    while True:
        d = get("list.json", bgn_de=bgn, end_de=end, pblntf_ty="D",
                page_no=page, page_count=100, sort="date", sort_mth="desc")
        out.extend(d.get("list", []) or [])
        tp = int(d.get("total_page", 1) or 1)
        if page >= tp:
            break
        page += 1
        time.sleep(0.3)
    return out


def major_detail(corp_code, rcept_no):
    """corp_code로 대량보유 상세 → 해당 rcept_no 행."""
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

    seen, items = set(), []
    for row in rows:
        if "대량보유상황보고서" not in row.get("report_nm", ""):
            continue
        firm = firm_in(row.get("flr_nm", ""))
        detail = {}
        if not firm and row.get("corp_code"):
            # 제출인에서 못 잡으면 대표보고자로 재확인
            detail = major_detail(row["corp_code"], row["rcept_no"])
            firm = firm_in(detail.get("repror", ""))
        if not firm:
            continue
        if not detail and row.get("corp_code"):
            detail = major_detail(row["corp_code"], row["rcept_no"])

        rcept_no = row["rcept_no"]
        if rcept_no in seen:
            continue
        seen.add(rcept_no)

        rdt = row.get("rcept_dt", "")
        items.append({
            "rcept_no": rcept_no,
            "rcept_dt": f"{rdt[:4]}-{rdt[4:6]}-{rdt[6:]}" if len(rdt) == 8 else rdt,
            "firm": firm,
            "corp_name": row.get("corp_name", ""),
            "stock_code": row.get("stock_code", ""),
            "stkrt": detail.get("stkrt", ""),            # 보유비율
            "stkrt_prev": "",                            # 직전 비율(상세에 없으면 빈값)
            "stkrt_irds": detail.get("stkrt_irds", ""),  # 비율 증감
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
