"""
backfill.py  (v4 · 소유상황보고서 + 3개월 청크 + 미리 한국어 매칭)
─────────────────────────────────────────────────────────────
기존 data.json 초기화 후 365일치 재구축.
Actions에서 Backfill (수동 실행)으로 1회 실행.
"""

import os, io, re, sys, json, time, zipfile, base64
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
    "라이프자산운용",
    "에셋플러스자산운용",
    "트러스톤자산운용",
    "피델리티",
    "Miri",
]

BACKFILL_DAYS = 365

s = requests.Session()
s.headers.update({"User-Agent": "vip-tracker-backfill/4.0"})
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
        except Exception as e:
            print(f"[retry {i}] {endpoint}: {e}", file=sys.stderr)
            time.sleep(1.5 * (i + 1))
    return {"status": "999", "list": []}


FIRM_ALIAS = {"FIL": "피델리티", "미리": "Miri"}

def firm_in(name):
    if not name:
        return None
    low = name.lower().replace(" ", "")
    for alias, canonical in FIRM_ALIAS.items():
        if alias.lower() in low:
            return canonical
    for f in WATCH_FIRMS:
        if f.lower().replace(" ", "") in low:
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
            print(f"    [warn] document {rcept_no}: {r.text[:120]}", file=sys.stderr)
            return {}
        if not r.content[:2] == b"PK":
            print(f"    [warn] document {rcept_no}: not a zip", file=sys.stderr)
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
        return _parse_plain(plain)
    except Exception as e:
        print(f"    [warn] 원문 파싱 실패 {rcept_no}: {e}", file=sys.stderr)
        return {}


def _parse_plain(plain):
    out = {}
    # 소유상황보고서 전용: "이번보고서 날짜 주식수 비율" 직접 매칭
    owm = re.search(r"이번\s*보고서\s*\d{4}년?\s*\d{1,2}월?\s*\d{1,2}일?\s*([\d,]+)\s+([\d.]+)", plain)
    if owm:
        out["stkqy"] = owm.group(1).replace(",", "")
        out["stkrt"] = owm.group(2)

    # 대량보유상황보고서 패턴 (기존, fallback)
    if "stkrt" not in out:
        cur_match = re.search(r"이번\s*보고서(.{3,400}?)(?:의결권|보고사유|변동사유|보유목적|증\s*감|특정증권|종류별|세부변동)", plain, re.DOTALL)
        if cur_match:
            block = cur_match.group(1)
            block = re.sub(r"\d{4}년?\s*\d{1,2}월?\s*\d{1,2}일?", "", block)
            nums = re.findall(r"([\d,]+(?:\.\d+)?)", block)
            float_nums = [(n, to_float(n)) for n in nums if to_float(n) is not None]
            for raw, v in float_nums:
                if "." in raw and v < 100 and "stkrt" not in out:
                    out["stkrt"] = raw
                elif v > 100 and "stkqy" not in out:
                    out["stkqy"] = raw.replace(",", "")
    # 소유상황보고서 전용: 직전보고서 날짜 주식수 비율
    opm = re.search(r"직전\s*보고서\s*\d{4}년?\s*\d{1,2}월?\s*\d{1,2}일?\s*([\d,]+)\s+([\d.]+)", plain)
    if opm:
        out["stkrt_prev"] = opm.group(2)

    if "stkrt_prev" not in out:
        prev_match = re.search(r"직전\s*보고서(.{3,400}?)(?:이번\s*보고서|의결권|보고사유|변동사유|보유목적|증\s*감|특정증권|$)", plain, re.DOTALL)
        if prev_match:
            block = prev_match.group(1)
            block2 = re.sub(r"\d{4}년?\s*\d{1,2}월?\s*\d{1,2}일?", "", block)
            for raw_n in re.findall(r"([\d,]+(?:\.\d+)?)", block2):
                v = to_float(raw_n)
                if v is not None and "." in raw_n and v < 100:
                    out["stkrt_prev"] = raw_n
                    break
    if "stkrt" not in out:
        cur = re.search(r"이번\s*보고서\s*([\d,]+)\s+([\d]+(?:\.\d+)?)", plain)
        if cur:
            out["stkqy"] = cur.group(1).replace(",", "")
            out["stkrt"] = cur.group(2)
    if "stkrt_prev" not in out:
        prev = re.search(r"직전\s*보고서\s*([\d,]+)\s+([\d]+(?:\.\d+)?)", plain)
        if prev:
            out["stkrt_prev"] = prev.group(2)
    # 보고사유: 소유상황보고서는 세부변동내역에서 장내매수 등 추출
    trade_methods = re.findall(r"(장내매수|장외매수|장내매매|시간외매매|시간외매수|장내매도|장외매도)", plain)
    if trade_methods:
        from collections import Counter
        method = Counter(trade_methods).most_common(1)[0][0]
        out["report_resn"] = method

    if "report_resn" not in out:
        for pat in [
            r"보고사유\s*(.+?)\s*(?:보유목적|변동사유|비고)",
            r"보고사유\s*(.{3,60})",
        ]:
            resn = re.search(pat, plain)
            if resn:
                val = resn.group(1).strip()[:60]
                if val and "취득/처분" not in val and "변동전" not in val and "거래계획" not in val:
                    out["report_resn"] = val
                    break
    for pat in [
        r"보유목적\s*([가-힣A-Za-z]+투자)",
        r"보유목적\s*([가-힣A-Za-z]{2,20})",
    ]:
        purpose = re.search(pat, plain)
        if purpose:
            out["purpose"] = purpose.group(1).strip()
            break
    return out


def classify(stkrt, stkrt_prev, report_resn=""):
    cur = to_float(stkrt)
    prev = to_float(stkrt_prev)
    if "신규" in (report_resn or ""):
        return "매수(신규)"
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
    sha = gh_get_sha()
    print("[info] 기존 데이터 무시하고 새로 구축")

    today = dt.date.today()
    start_date = today - dt.timedelta(days=BACKFILL_DAYS)

    # DART API: corp_code 없이 최대 3개월 → 89일 청크
    chunk_days = 89
    date_ranges = []
    d_cursor = start_date
    while d_cursor < today:
        d_end = min(d_cursor + dt.timedelta(days=chunk_days), today)
        date_ranges.append((d_cursor.strftime("%Y%m%d"), d_end.strftime("%Y%m%d")))
        d_cursor = d_end + dt.timedelta(days=1)
    print(f"[info] {len(date_ranges)}개 구간으로 스캔 ({BACKFILL_DAYS}일)")

    items, seen = {}, set()
    max_seen = ""

    for chunk_bgn, chunk_end in date_ranges:
        page = 1
        while True:
            d = dart("list.json", bgn_de=chunk_bgn, end_de=chunk_end, pblntf_ty="D",
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
                report_nm = row.get("report_nm", "")
                if "대량보유상황보고서" not in report_nm and "소유상황보고서" not in report_nm:
                    continue
                firm = firm_in(row.get("flr_nm", ""))
                if not firm or rcept_no in seen:
                    continue
                seen.add(rcept_no)
                doc = parse_document(rcept_no)
                time.sleep(0.3)
                kind = classify(doc.get("stkrt"), doc.get("stkrt_prev"), doc.get("report_resn", ""))
                rdt = row.get("rcept_dt", "")

                ok = "✓" if doc.get("stkrt") else "✗"
                print(f"  [{ok}] {row.get('corp_name','')} / {firm} / stkrt={doc.get('stkrt','?')} / {kind}")

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
            print(f"  ...{chunk_bgn}~{chunk_end} 페이지 {page}/{tp}, 누적 {len(items)}건")
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
