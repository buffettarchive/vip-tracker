"""
fetch_vip.py  (v8 · 본문 파싱 패턴 대폭 강화)
─────────────────────────────────────────────────────────────
v7 대비 변경:
- parse_document를 블록 기반 파싱으로 교체 (다양한 본문 형식 대응)
- "이번 보고서"~"직전 보고서" 블록에서 숫자 추출 → 비율/주식수 자동 판별
- 보고사유·보유목적 패턴 확장
- fallback으로 v7 단순 패턴도 유지
"""

import os, io, re, sys, json, time, zipfile, base64, argparse
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

SCAN_DAYS = 3

s = requests.Session()
s.headers.update({"User-Agent": "vip-tracker/0.8"})
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


# FIL Limited, FIL Investment Management 등은 피델리티 계열
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
    """
    공시 원문(document.xml=zip)을 받아 요약정보 표에서
    이번/직전 보고서의 보유주식수·보유비율, 보고사유, 보유목적을 추출.
    """
    try:
        r = s.get(f"{DART}/document.xml",
                  params={"crtfc_key": DART_KEY, "rcept_no": rcept_no}, timeout=30)
        if r.headers.get("content-type", "").startswith("application/json"):
            print(f"[warn] document {rcept_no}: {r.text[:120]}", file=sys.stderr)
            return {}
        if not r.content[:2] == b"PK":
            print(f"[warn] document {rcept_no}: not a zip", file=sys.stderr)
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
        print(f"[warn] 원문 파싱 실패 {rcept_no}: {e}", file=sys.stderr)
        return {}


def _parse_plain(plain):
    """태그 제거된 본문 텍스트에서 데이터 추출."""
    out = {}

    # ── 이번 보고서: 바로 뒤의 숫자들에서 주식수·비율 추출 ──
    cur_match = re.search(r"이번\s*보고서(.{3,200}?)(?:의결권|보고사유|변동사유|보유목적|$)", plain, re.DOTALL)
    if cur_match:
        block = cur_match.group(1)
        nums = re.findall(r"([\d,]+(?:\.\d+)?)", block)
        float_nums = [(n, to_float(n)) for n in nums if to_float(n) is not None]
        for raw, v in float_nums:
            if "." in raw and v < 100 and "stkrt" not in out:
                out["stkrt"] = raw
            elif v > 100 and "stkqy" not in out:
                out["stkqy"] = raw.replace(",", "")

    # ── 직전 보고서: 바로 뒤의 숫자들에서 비율 추출 ──
    prev_match = re.search(r"직전\s*보고서(.{3,200}?)(?:이번\s*보고서|의결권|보고사유|변동사유|보유목적|$)", plain, re.DOTALL)
    if prev_match:
        block = prev_match.group(1)
        for raw_n in re.findall(r"([\d,]+(?:\.\d+)?)", block):
            v = to_float(raw_n)
            if v is not None and "." in raw_n and v < 100:
                out["stkrt_prev"] = raw_n
                break

    # ── fallback: 단순 패턴 ──
    if "stkrt" not in out:
        cur = re.search(r"이번\s*보고서\s*([\d,]+)\s+([\d]+(?:\.\d+)?)", plain)
        if cur:
            out["stkqy"] = cur.group(1).replace(",", "")
            out["stkrt"] = cur.group(2)
    if "stkrt_prev" not in out:
        prev = re.search(r"직전\s*보고서\s*([\d,]+)\s+([\d]+(?:\.\d+)?)", plain)
        if prev:
            out["stkrt_prev"] = prev.group(2)

    # ── 보고사유 ──
    for pat in [
        r"보고사유\s*(.+?)\s*(?:보유목적|변동사유|비고)",
        r"보고사유\s*(.{3,60})",
    ]:
        resn = re.search(pat, plain)
        if resn:
            val = resn.group(1).strip()[:60]
            if val:
                out["report_resn"] = val
                break

    # ── 보유목적 ──
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
        "message": f"data: auto update {payload['updated_at']}",
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
    parser = argparse.ArgumentParser()
    parser.add_argument("--backfill-days", type=int, default=0,
                        help="과거 N일치 재스캔 (last_seen 무시)")
    args = parser.parse_args()

    data, sha = gh_get()
    existing = {d["rcept_no"]: d for d in data.get("disclosures", [])}
    last_seen = data.get("last_seen", "") or (max(existing) if existing else "")

    scan_days = SCAN_DAYS
    if args.backfill_days > 0:
        scan_days = args.backfill_days
        last_seen = ""  # 백필 모드: last_seen 무시
        print(f"[info] ★ 백필 모드: {scan_days}일, last_seen 무시")

    print(f"[info] 기존 {len(existing)}건, 마지막 본 번호={last_seen or '없음'}")

    today = dt.date.today()
    bgn = (today - dt.timedelta(days=scan_days)).strftime("%Y%m%d")
    end = today.strftime("%Y%m%d")

    added, max_seen, stop, page = 0, last_seen, False, 1
    while not stop:
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
            if last_seen and rcept_no <= last_seen:
                stop = True
                break
            if rcept_no > max_seen:
                max_seen = rcept_no
            report_nm = row.get("report_nm", "")
            if "대량보유상황보고서" not in report_nm and "소유상황보고서" not in report_nm:
                continue
            firm = firm_in(row.get("flr_nm", ""))
            if not firm or rcept_no in existing:
                continue

            doc = parse_document(rcept_no)
            time.sleep(0.3)
            kind = classify(doc.get("stkrt"), doc.get("stkrt_prev"), doc.get("report_resn", ""))
            rdt = row.get("rcept_dt", "")

            ok = "✓" if doc.get("stkrt") else "✗"
            print(f"  [{ok}] {row.get('corp_name','')} / {firm} / stkrt={doc.get('stkrt','?')} / {kind}")

            existing[rcept_no] = {
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
            added += 1

        tp = int(d.get("total_page", 1) or 1)
        if page >= tp:
            break
        page += 1
        time.sleep(0.2)

    # ── 불완전 항목 재시도 (stkrt 비어있는 최근 항목) ──
    retried = 0
    for rcept_no, entry in list(existing.items()):
        if entry.get("stkrt"):
            continue  # 이미 데이터 있음
        # 최근 7일 이내 항목만 재시도
        rdt = entry.get("rcept_dt", "")
        if not rdt:
            continue
        try:
            entry_date = dt.datetime.strptime(rdt, "%Y-%m-%d").date()
        except ValueError:
            continue
        if (today - entry_date).days > 7:
            continue
        doc = parse_document(rcept_no)
        time.sleep(0.3)
        if doc.get("stkrt"):
            entry["stkrt"] = doc["stkrt"]
            entry["stkrt_prev"] = doc.get("stkrt_prev", "")
            entry["stkqy"] = doc.get("stkqy", "")
            entry["report_resn"] = doc.get("report_resn", "")
            entry["purpose"] = doc.get("purpose", "")
            entry["kind"] = classify(doc.get("stkrt"), doc.get("stkrt_prev"), doc.get("report_resn", ""))
            existing[rcept_no] = entry
            retried += 1
            print(f"  [재시도✓] {entry.get('corp_name','')} / stkrt={doc['stkrt']} / {entry['kind']}")
    if retried:
        print(f"[info] {retried}건 재시도 성공")

    if added == 0 and retried == 0 and max_seen == last_seen:
        print("[info] 새 공시 없음 — 변경 없이 종료")
        return

    merged = sorted(existing.values(), key=lambda x: x.get("rcept_no", ""), reverse=True)
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
