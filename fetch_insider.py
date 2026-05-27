"""
fetch_insider.py  (v1 · 코스닥 내부자 매수 추적)
─────────────────────────────────────────────────────────────
코스닥(corp_cls=K) 임원·주요주주 특정증권등 소유상황보고서 중
'소유 증가(매수)'만 골라 docs/insider.json 에 누적한다.

핵심 최적화:
- 본문(document.xml) 다운로드를 전혀 안 한다.
- list로 코스닥 내부자 보고의 회사를 모으고, elestock 정형 API로
  회사별 변동을 한 번에 받아 해당 접수번호의 매수 건만 추린다.
"""

import os
import sys
import json
import time
import base64
import datetime as dt

import requests

DART_KEY = os.environ["DART_API_KEY"]
GH_TOKEN = os.environ["GH_TOKEN"]

GH_OWNER = "buffettarchive"
GH_REPO = "vip-tracker"
GH_PATH = "docs/insider.json"     # 운용사(data.json)와 분리된 별도 파일
GH_BRANCH = "main"

DART = "https://opendart.fss.or.kr/api"
GH_API = "https://api.github.com"

SCAN_DAYS = 3
INSIDER_REPORT = "임원ㆍ주요주주특정증권등소유상황보고서"

s = requests.Session()
s.headers.update({"User-Agent": "vip-tracker-insider/1.0"})
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


def to_int(v):
    try:
        return int(str(v).replace(",", "").replace("+", "").strip())
    except (ValueError, TypeError):
        return 0


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
        "message": f"insider: auto update {payload['updated_at']}",
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
    last_seen = data.get("last_seen", "") or (max(existing) if existing else "")
    print(f"[info] 기존 {len(existing)}건, 마지막 본 번호={last_seen or '없음'}")

    today = dt.date.today()
    bgn = (today - dt.timedelta(days=SCAN_DAYS)).strftime("%Y%m%d")
    end = today.strftime("%Y%m%d")

    # 1) 코스닥 내부자 보고만 list로 훑어 (회사,접수번호) 후보 수집
    targets = {}        # corp_code -> set(rcept_no)
    meta = {}           # rcept_no -> (corp_name, stock_code)
    max_seen, stop, page = last_seen, False, 1
    while not stop:
        d = dart("list.json", bgn_de=bgn, end_de=end,
                 pblntf_ty="D", pblntf_detail_ty="D002",  # 내부자 소유보고만
                 corp_cls="K",                            # 코스닥만
                 page_no=page, page_count=100, sort="date", sort_mth="desc")
        st = d.get("status")
        if st == "013":
            break
        if st != "000":
            print(f"[warn] list status={st} msg={d.get('message')}", file=sys.stderr)
            break
        for row in d.get("list", []) or []:
            rcept_no = row["rcept_no"]
            if last_seen and rcept_no <= last_seen:
                stop = True
                break
            if rcept_no > max_seen:
                max_seen = rcept_no
            if INSIDER_REPORT not in row.get("report_nm", ""):
                continue
            cc = row.get("corp_code", "")
            if not cc:
                continue
            targets.setdefault(cc, set()).add(rcept_no)
            meta[rcept_no] = (row.get("corp_name", ""), row.get("stock_code", ""))
        tp = int(d.get("total_page", 1) or 1)
        if page >= tp:
            break
        page += 1
        time.sleep(0.2)

    print(f"[info] 코스닥 내부자 보고 후보 회사 {len(targets)}곳")

    # 2) 회사별 elestock 한 번씩 → 해당 접수번호의 '매수(증가)'만 기록
    added = 0
    for cc, rcept_set in targets.items():
        d = dart("elestock.json", corp_code=cc)
        if d.get("status") != "000":
            continue
        for item in d.get("list", []) or []:
            rcept_no = item.get("rcept_no", "")
            if rcept_no not in rcept_set or rcept_no in existing:
                continue
            irds = to_int(item.get("sp_stock_lmp_irds_cnt"))
            if irds <= 0:        # 매수(증가)만. 0이나 매도(-)는 제외
                continue
            corp_name, stock_code = meta.get(rcept_no, (item.get("corp_name", ""), ""))
            existing[rcept_no] = {
                "rcept_no": rcept_no,
                "rcept_dt": item.get("rcept_dt", ""),
                "corp_name": corp_name or item.get("corp_name", ""),
                "stock_code": stock_code,
                "corp_code": cc,
                "repror": item.get("repror", ""),
                "ofcps": item.get("isu_exctv_ofcps", ""),
                "rgist": item.get("isu_exctv_rgist_at", ""),
                "main_shrholdr": item.get("isu_main_shrholdr", ""),
                "irds_cnt": item.get("sp_stock_lmp_irds_cnt", ""),
                "total_cnt": item.get("sp_stock_lmp_cnt", ""),
                "irds_rate": item.get("sp_stock_lmp_irds_rate", ""),
                "hold_rate": item.get("sp_stock_lmp_rate", ""),
            }
            added += 1
        time.sleep(0.15)

    if added == 0 and max_seen == last_seen:
        print("[info] 새 내부자 매수 없음 — 변경 없이 종료")
        return

    merged = sorted(existing.values(), key=lambda x: x.get("rcept_no", ""), reverse=True)
    payload = {
        "updated_at": dt.datetime.now(dt.timezone(dt.timedelta(hours=9))).isoformat(timespec="minutes"),
        "market": "KOSDAQ",
        "last_seen": max_seen,
        "disclosures": merged,
    }
    if gh_put(payload, sha):
        print(f"[info] 신규 매수 {added}건 추가 → 총 {len(merged)}건, GitHub 반영 완료")


if __name__ == "__main__":
    main()
