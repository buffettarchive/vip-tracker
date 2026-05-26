"""
backfill.py  (v2 · 본문 파싱 + 기존 데이터 초기화 후 재구축)
─────────────────────────────────────────────────────────────
80일치 대량보유 공시를 본문에서 직접 읽어 정확한 본인 몫으로 다시 채운다.
기존 data.json은 무시하고 처음부터 새로 만든다(틀린 옛 데이터 청소).
Render에서 Command를 'python backfill.py'로 잠깐 바꿔 1회 실행.
"""

import os
import io
import re
import sys
import json
import time
import zipfile
import base64
import datetime as dt

import requests

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

BACKFILL_DAYS = 80

s = requests.Session()
s.headers.update({"User-Agent": "vip-tracker-backfill/2.0"})
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


def to_float(v):
    try:
        return float(str(v).replace(",", "").replace("%", "").strip())
    except (ValueError, TypeError):
        return None


def parse_document(rcept_no):
    try:
        r = s.get(f"{DART}/document.xml",
                  params={"crtfc_key": DART_KEY, "rcept_no": rcept_no}, timeout=30)
        if r.headers.get("content-type", "").startswith("application/json"):
            print(f"[warn] document {rcept_no}: {r.text[:120]}", file=sys.stderr)
            return {}
        z = zipfile.ZipFile(io.BytesIO(r.content))
        name = max(z.namelist(), key=lambda n: z.getinfo(n).file_size)
        raw = z.read(name)
        text = None
        for enc in ("utf-8", "euc-kr", "cp949"):
            try:
                text = raw.decode(enc)
                break
            except UnicodeDecodeError:
                continue
        if text is None:
            text = raw.decode("utf-8", errors="ignore")
        plain = re.sub(r"<[^>]+>", " ", text)
        plain = re.sub(r"&[a-zA-Z#0-9]+;", " ", plain)
        plain = re.sub(r"\s+", " ", plain)
        out = {}
        cur = re.search(r"이번\s*보고서\s*([\d,]+)\s+([\d]+(?:\.\d+)?)", plain)
        prev = re.search(r"직전\s*보고서\s*([\d,]+)\s+([\d]+(?:\.\d+)?)", plain)
        if cur:
            out["stkqy"] = cur.group(1).replace(",", "")
            out["stkrt"] = cur.group(2)
        if prev:
            out["stkrt_prev"] = prev.group(2)
        resn = re.search(r"보고사유\s*(.+?)\s*보유목적", plain)
        if resn:
            out["report_resn"] = resn.group(1).strip()[:60]
        purpose = re.search(r"보유목적\s*([가-힣A-Za-z]+투자)", plain)
        if purpose:
            out["purpose"] = purpose.group(1).strip()
        return out
    except Exception as e:  # noqa
        print(f"[warn] 원문 파싱 실패 {rcept_no}: {e}", file=sys.stderr)
        return {}


def classify(stkrt, stkrt_prev):
    cur = to_float(stkrt)
    prev = to_float(stkrt_prev)
    if cur is None:
        return "기타"
    if prev is None:
        return "매수(신규)"
    if cur > prev:
        return "매수"
    if cur < prev:
        return "매도"
    return "기타"


def gh_get_sha():
    url = f"{GH_API}/repos/{GH_OWNER}/{GH_REPO}/contents/{GH_PATH}?ref={GH_BRANCH}"
    r = s.get(url, headers=GH_HEADERS, timeout=20)
    if r.status_code == 200:
        return r.json()["sha"]
    return None


def gh_put(payload, sha):
    url = f"{GH_API}/repos/{GH_OWNER}/{GH_REPO}/contents/{GH_PATH}"
    body = {
        "message": f"data: backfill rebuild {payload['updated_at']}",
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
    sha = gh_get_sha()   # 기존 파일은 덮어쓴다(초기화)
    print("[info] 기존 데이터 무시하고 새로 구축")

    today = dt.date.today()
    bgn = (today - dt.timedelta(days=BACKFILL_DAYS)).strftime("%Y%m%d")
    end = today.strftime("%Y%m%d")

    items, seen = {}, set()
    max_seen, page = "", 1
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
            if not firm or rcept_no in seen:
                continue
            seen.add(rcept_no)
            doc = parse_document(rcept_no)
            time.sleep(0.3)
            kind = classify(doc.get("stkrt"), doc.get("stkrt_prev"))
            rdt = row.get("rcept_dt", "")
            items[rcept_no] = {
                "rcept_no": rcept_no,
                "rcept_dt": f"{rdt[:4]}-{rdt[4:6]}-{rdt[6:]}" if len(rdt) == 8 else rdt,
                "firm": firm,
                "corp_name": row.get("corp_name", ""),
                "stock_code": row.get("stock_code", ""),
                "corp_code": row.get("corp_code", ""),
                "stkrt": doc.get("stkrt", ""),
                "stkrt_prev": doc.get("stkrt_prev", ""),
                "stkqy": doc.get("stkqy", ""),
                "report_resn": doc.get("report_resn", ""),
                "purpose": doc.get("purpose", ""),
                "report_nm": row.get("report_nm", ""),
                "kind": kind,
            }
        tp = int(d.get("total_page", 1) or 1)
        print(f"  ...페이지 {page}/{tp}, 누적 {len(items)}건")
        if page >= tp:
            break
        page += 1
        time.sleep(0.2)

    merged = sorted(items.values(), key=lambda x: x.get("rcept_no", ""), reverse=True)
    payload = {
        "updated_at": dt.datetime.now(dt.timezone(dt.timedelta(hours=9))).isoformat(timespec="minutes"),
        "is_seed": False,
        "firms": WATCH_FIRMS,
        "last_seen": max_seen,
        "disclosures": merged,
    }
    if gh_put(payload, sha):
        print(f"[info] 재구축 완료 → 총 {len(merged)}건, GitHub 반영")


if __name__ == "__main__":
    main()
