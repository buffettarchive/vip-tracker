"""
backfill.py  (과거 채우기 · 일회용)
─────────────────────────────────────────────────────────────
추적 대상 운용사의 최근 80일치 대량보유(5%) 공시를 한 번에 긁어
기존 data.json에 합쳐 넣고 GitHub에 push 한다.
평소 자동 로봇(fetch_vip.py)은 그대로 두고, 이건 필요할 때만 손으로 1회 실행.

Render에서 Command를 'python backfill.py'로 잠깐 바꿔 1회 실행하면 된다.
"""

import os
import sys
import json
import time
import base64
import datetime as dt

import requests

# Render에 이미 등록된 환경변수를 그대로 사용 (별도 입력 불필요)
DART_KEY = os.environ["DART_API_KEY"]
GH_TOKEN = os.environ["GH_TOKEN"]

GH_OWNER = "buffettarchive"
GH_REPO = "vip-tracker"
GH_PATH = "docs/data.json"
GH_BRANCH = "main"

DART = "https://opendart.fss.or.kr/api"
GH_API = "https://api.github.com"

WATCH_FIRMS = [
    "브이아이피자산운용",
    "얼라인파트너스자산운용",
]

BACKFILL_DAYS = 80   # 최대 약 90일(3개월)까지. 80이 안전.

s = requests.Session()
s.headers.update({"User-Agent": "vip-tracker-backfill/1.0"})
GH_HEADERS = {
    "Authorization": f"Bearer {GH_TOKEN}",
    "Accept": "application/vnd.github+json",
    "X-GitHub-Api-Version": "2022-11-28",
}


def dart(endpoint, **params):
    params["crtfc_key"] = DART_KEY
    for i in range(3):
        try:
            return s.get(f"{DART}/{endpoint}", params=params, timeout=20).json()
        except Exception as e:  # noqa
            print(f"[retry {i}] {endpoint}: {e}", file=sys.stderr)
            time.sleep(1.5 * (i + 1))
    return {"status": "999", "list": []}


def firm_in(name):
    if not name:
        return None
    for f in WATCH_FIRMS:
        if f in name:
            return f
    return None


def major_detail(corp_code, rcept_no):
    d = dart("majorstock.json", corp_code=corp_code)
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


def gh_get():
    url = f"{GH_API}/repos/{GH_OWNER}/{GH_REPO}/contents/{GH_PATH}?ref={GH_BRANCH}"
    r = s.get(url, headers=GH_HEADERS, timeout=20)
    if r.status_code == 200:
        j = r.json()
        return json.loads(base64.b64decode(j["content"]).decode("utf-8")), j["sha"]
    return {"disclosures": [], "last_seen": ""}, None


def gh_put(payload, sha):
    url = f"{GH_API}/repos/{GH_OWNER}/{GH_REPO}/contents/{GH_PATH}"
    body = {
        "message": f"data: backfill {payload['updated_at']}",
        "content": base64.b64encode(
            json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
        ).decode("ascii"),
        "branch": GH_BRANCH,
    }
    if sha:
        body["sha"] = sha
    r = s.put(url, headers=GH_HEADERS, data=json.dumps(body), timeout=20)
    if r.status_code not in (200, 201):
        print(f"[ERR] github push {r.status_code}: {r.text}", file=sys.stderr)
        return False
    return True


def main():
    data, sha = gh_get()
    existing = {d["rcept_no"]: d for d in data.get("disclosures", [])}
    prev_last = data.get("last_seen", "") or (max(existing) if existing else "")
    print(f"[info] 기존 {len(existing)}건에서 시작")

    today = dt.date.today()
    bgn = (today - dt.timedelta(days=BACKFILL_DAYS)).strftime("%Y%m%d")
    end = today.strftime("%Y%m%d")

    added, max_seen, page = 0, prev_last, 1
    while True:
        d = dart("list.json", bgn_de=bgn, end_de=end, pblntf_ty="D",
                 page_no=page, page_count=100, sort="date", sort_mth="desc")
        st = d.get("status")
        if st == "013":
            break
        if st != "000":
            print(f"[warn] list status={st} msg={d.get('message')}", file=sys.stderr)
            break
        for row in d.get("list", []) or []:
            rcept_no = row["rcept_no"]
            if rcept_no > max_seen:
                max_seen = rcept_no
            if "대량보유상황보고서" not in row.get("report_nm", ""):
                continue
            firm = firm_in(row.get("flr_nm", ""))
            if not firm or rcept_no in existing:
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
        print(f"  ...페이지 {page}/{tp} 처리")
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
    if gh_put(payload, sha):
        print(f"[info] 신규 {added}건 추가 → 총 {len(merged)}건, GitHub 반영 완료")


if __name__ == "__main__":
    main()
