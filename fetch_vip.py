"""
fetch_vip.py  (v5 · 마지막 본 지점까지만 확인)
─────────────────────────────────────────────────────────────
DART 공시는 접수번호(rcept_no)가 시간순으로 커진다.
지난번에 본 가장 큰 번호(high-water mark)를 기억해두고,
최신부터 훑다가 그 번호 이하를 만나면 즉시 멈춘다.
→ 새 공시가 없으면 목록 한두 페이지만 보고 끝. 매우 빠름.

기존 누적/정리 기능은 그대로:
- 이전 데이터는 모아두고 새 것만 추가
- 5% 미만(지분 축소) 제외, 신규/변동 구분
"""

import os
import sys
import json
import time
import datetime as dt

import requests

DART_KEY = os.environ["DART_API_KEY"]
DART = "https://opendart.fss.or.kr/api"

WATCH_FIRMS = [
    "브이아이피자산운용",
    # "라이프자산운용",
    # "머스트자산운용",
]

# 새 공시가 없을 때도 안전하게 살펴볼 최소 기간(짧게).
SCAN_DAYS = 3
OUT_PATH = "docs/data.json"

s = requests.Session()
s.headers.update({"User-Agent": "vip-tracker/0.5"})


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


def load_existing():
    """기존 데이터와, 지금까지 본 가장 큰 접수번호를 함께 반환."""
    if not os.path.exists(OUT_PATH):
        return {}, ""
    try:
        with open(OUT_PATH, encoding="utf-8") as f:
            data = json.load(f)
        items = {d["rcept_no"]: d for d in data.get("disclosures", [])}
        last_seen = data.get("last_seen", "")
        if not last_seen and items:
            last_seen = max(items.keys())   # 옛 파일 대비
        return items, last_seen
    except Exception as e:  # noqa
        print(f"[warn] 기존 데이터 읽기 실패: {e}", file=sys.stderr)
        return {}, ""


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


def to_float(v):
    try:
        return float(str(v).replace(",", "").replace("%", "").strip())
    except (ValueError, TypeError):
        return None


def classify(report_resn, stkrt):
    resn = report_resn or ""
    rt = to_float(stkrt)
    if "5%미만" in resn or "5% 미만" in resn or (rt is not None and rt < 5):
        return None
    if "신규" in resn:
        return "신규"
    if "변동" in resn:
        return "변동"
    if "변경" in resn:
        return "변경"
    return "기타"


def main():
    existing, last_seen = load_existing()
    print(f"[info] 기존 {len(existing)}건, 마지막 본 번호={last_seen or '없음'}")

    today = dt.date.today()
    bgn = (today - dt.timedelta(days=SCAN_DAYS)).strftime("%Y%m%d")
    end = today.strftime("%Y%m%d")

    added = 0
    max_seen = last_seen
    stop = False
    page = 1

    while not stop:
        d = get("list.json", bgn_de=bgn, end_de=end, pblntf_ty="D",
                page_no=page, page_count=100, sort="date", sort_mth="desc")
        st = d.get("status")
        if st == "013":
            break
        if st != "000":
            print(f"[warn] list status={st} msg={d.get('message')}", file=sys.stderr)
            break

        rows = d.get("list", []) or []
        for row in rows:
            rcept_no = row["rcept_no"]
            # 최신순으로 훑다가 '이미 본 지점'에 닿으면 멈춤
            if last_seen and rcept_no <= last_seen:
                stop = True
                break
            if rcept_no > max_seen:
                max_seen = rcept_no

            if "대량보유상황보고서" not in row.get("report_nm", ""):
                continue
            firm = firm_in(row.get("flr_nm", ""))
            if not firm:
                continue
            if rcept_no in existing:
                continue

            detail = major_detail(row.get("corp_code", ""), rcept_no) if row.get("corp_code") else {}
            kind = classify(detail.get("report_resn", ""), detail.get("stkrt", ""))
            if kind is None:
                continue

            rdt = row.get("rcept_dt", "")
            existing[rcept_no] = {
                "rcept_no": rcept_no,
                "rcept_dt": f"{rdt[:4]}-{rdt[4:6]}-{rdt[6:]}" if len(rdt) == 8 else rdt,
                "firm": firm,
                "corp_name": row.get("corp_name", ""),
                "stock_code": row.get("stock_code", ""),
                "stkrt": detail.get("stkrt", ""),
                "stkrt_irds": detail.get("stkrt_irds", ""),
                "report_resn": detail.get("report_resn", ""),
                "report_nm": row.get("report_nm", ""),
                "kind": kind,
            }
            added += 1

        tp = int(d.get("total_page", 1) or 1)
        if page >= tp:
            break
        page += 1
        time.sleep(0.2)

    merged = sorted(existing.values(), key=lambda x: x.get("rcept_dt", ""), reverse=True)
    payload = {
        "updated_at": dt.datetime.now(dt.timezone(dt.timedelta(hours=9))).isoformat(timespec="minutes"),
        "is_seed": False,
        "firms": WATCH_FIRMS,
        "last_seen": max_seen,
        "disclosures": merged,
    }
    os.makedirs(os.path.dirname(OUT_PATH), exist_ok=True)
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    print(f"[info] 신규 {added}건 추가 → 총 {len(merged)}건 (살핀 페이지 {page})")


if __name__ == "__main__":
    main()
