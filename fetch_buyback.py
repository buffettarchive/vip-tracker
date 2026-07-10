"""
fetch_buyback.py — 자기주식 취득·소각 공시 자동 수집 (v3.1)
──────────────────────────────────────────────────────
Render Cron Job이 5분마다 실행.
1) GitHub에서 기존 buyback.json 읽기
2) DART list.json (pblntf_ty='B') → 주요사항보고서 중
   "자기주식취득" / "자기주식소각" 필터 (신탁계약·처분 제외)
3) document.xml 본문 파싱 (주력) + 구조화 API 보조
4) 변경 있으면 GitHub push

환경변수: DART_API_KEY, GH_TOKEN
"""

import os, sys, json, time, re, base64, io, zipfile
import datetime as dt
import requests

DART_KEY = os.environ["DART_API_KEY"]
GH_TOKEN = os.environ["GH_TOKEN"]

GH_OWNER   = "buffettarchive"
GH_REPO    = "vip-tracker"
GH_PATH    = "docs/buyback.json"
GH_BRANCH  = "main"

DART = "https://opendart.fss.or.kr/api"
GH_API = "https://api.github.com"

SCAN_DAYS = 3

s = requests.Session()
s.headers.update({"User-Agent": "buyback-tracker/3.1"})

GH_HEADERS = {
    "Authorization": f"Bearer {GH_TOKEN}",
    "Accept": "application/vnd.github+json",
    "X-GitHub-Api-Version": "2022-11-28",
}

# ── helpers ────────────────────────────────────────────

def dart(endpoint, **params):
    params["crtfc_key"] = DART_KEY
    for i in range(3):
        try:
            r = s.get(f"{DART}/{endpoint}", params=params, timeout=20)
            return r.json()
        except Exception as e:
            print(f"[retry {i}] {endpoint}: {e}", file=sys.stderr)
            time.sleep(1.5 * (i + 1))
    return {"status": "999", "list": []}

def to_int(v):
    if v is None:
        return None
    try:
        return int(str(v).replace(",", "").replace(" ", "")
                   .replace("주", "").replace("원", "").strip())
    except (ValueError, TypeError):
        return None

# ── document.xml 본문 추출 ─────────────────────────────

def fetch_document_text(rcept_no):
    try:
        r = s.get(f"{DART}/document.xml",
                  params={"crtfc_key": DART_KEY, "rcept_no": rcept_no},
                  timeout=30)
        if not r.content[:2] == b"PK":
            print(f"    [nodoc] {rcept_no}: 본문 아직 없음")
            return ""
        zf = zipfile.ZipFile(io.BytesIO(r.content))
        for name in zf.namelist():
            raw = zf.read(name)
            for enc in ("utf-8", "euc-kr", "cp949"):
                try:
                    text = raw.decode(enc)
                    text = re.sub(r"<[^>]+>", " ", text)
                    text = re.sub(r"\s+", " ", text).strip()
                    return text
                except (UnicodeDecodeError, LookupError):
                    continue
    except Exception as e:
        print(f"    [err] document.xml {rcept_no}: {e}", file=sys.stderr)
    return ""

# ── 본문 파싱: 취득결정 ───────────────────────────────

def parse_acq_doc(text):
    if not text:
        return {}
    result = {}

    # 보통주 주식수
    for pat in [
        r"1\.\s*취득예정주식.*?보통주[식]?\s*([0-9, ]{3,})",
        r"취득\s*예정\s*주식.*?보통주[식]?\s*([0-9, ]{3,})",
        r"보통주[식]?\s*\(?주\)?\s*([0-9, ]{3,})",
        r"보통주[식]?\s*[:\s]*([0-9, ]{3,})",
        r"취득\s*(?:할\s*)?주식[의]?\s*수[^0-9]*?([0-9, ]{3,})",
        r"취득\s*수량[^0-9]*?([0-9, ]{3,})"
    ]:
        m = re.search(pat, text)
        if m:
            val = to_int(m.group(1))
            if val and val >= 100:
                result["shares_common"] = val
                break

    # 보통주 금액
    for pat in [
        r"3\.\s*취득예정금액.*?보통주[식]?\s*([0-9, ]{4,})",
        r"취득\s*예정\s*금액.*?보통주[식]?\s*([0-9, ]{4,})",
        r"취득\s*(?:할\s*)?금액[^0-9]*?([0-9, ]{4,})"
    ]:
        m = re.search(pat, text)
        if m:
            val = to_int(m.group(1))
            if val and val > 1000:
                result["amount_common"] = val
                break

    # 취득목적
    for pat in [
        r"4\.\s*취득목적\s*([^0-9]{2,100}?)\s*5\.",
        r"취득\s*목적\s*[:\s]*([^\n\r]{2,100}?)(?:\s*\d+\.|\s*취득\s*방법|\s*취득\s*예상|\s*비고)",
        r"취득\s*목적\s*[:\s]*(.{2,100}?)(?:취득방법|취득예상|예상기간|이사회)"
    ]:
        m = re.search(pat, text)
        if m:
            val = m.group(1).strip().rstrip(".")
            if val and len(val) >= 2:
                result["acq_purpose"] = val
                break

    # 취득방법
    for pat in [
        r"5\.\s*취득방법\s*([^0-9]{2,100}?)\s*6\.",
        r"취득\s*방법\s*[:\s]*([^\n\r]{2,100}?)(?:\s*\d+\.|\s*취득\s*예상|\s*취득\s*기간|\s*비고)",
        r"취득\s*방법\s*[:\s]*(.{2,100}?)(?:취득예상|예상기간|이사회|비고|기타)"
    ]:
        m = re.search(pat, text)
        if m:
            val = m.group(1).strip().rstrip(".")
            if val and len(val) >= 2:
                result["acq_method"] = val
                break

    return result

# ── 본문 파싱: 소각 ──────────────────────────────────

def parse_cancel_doc(text):
    if not text:
        return {}
    result = {}
    for pat in [
        r"1\.\s*소각할\s*주식.*?보통주[식]?\s*([0-9, ]{3,})",
        r"소각[하할]{0,2}\s*(?:주식|주권)[^0-9]*?([0-9, ]{3,})\s*주",
        r"보통주[식권]?\s*([0-9, ]{3,})\s*주.*?소각",
        r"소각\s*주식\s*수[^0-9]*?([0-9, ]{3,})"
    ]:
        m = re.search(pat, text)
        if m:
            val = to_int(m.group(1))
            if val and val >= 10:
                result["shares_common"] = val
                break
    
    m2 = re.search(r"발행주식\s*총수[^0-9]*?([0-9,]+)", text)
    if m2:
        result["total_shares"] = to_int(m2.group(1))
    return result

# ── 구조화 API (보조) ────────────────────────────────

def fetch_api_detail(corp_code, rcept_dt):
    try:
        base = dt.datetime.strptime(rcept_dt, "%Y%m%d")
    except ValueError:
        base = dt.datetime.strptime(rcept_dt, "%Y-%m-%d")
    bgn = (base - dt.timedelta(days=14)).strftime("%Y%m%d")
    end = (base + dt.timedelta(days=14)).strftime("%Y%m%d")
    d = dart("tsstkAqDecsn.json", corp_code=corp_code, bgn_de=bgn, end_de=end)
    rows = d.get("list") or []
    return rows[0] if rows else {}

# ── GitHub 읽기/쓰기 ──────────────────────────────────

def gh_get_file():
    url = f"{GH_API}/repos/{GH_OWNER}/{GH_REPO}/contents/{GH_PATH}?ref={GH_BRANCH}"
    r = s.get(url, headers=GH_HEADERS, timeout=15)
    if r.status_code == 200:
        j = r.json()
        content = base64.b64decode(j["content"]).decode("utf-8")
        return json.loads(content), j["sha"]
    return {"entries": [], "last_seen": ""}, None

def gh_put_file(data, sha):
    url = f"{GH_API}/repos/{GH_OWNER}/{GH_REPO}/contents/{GH_PATH}"
    blob = json.dumps(data, ensure_ascii=False, indent=2)
    body = {
        "message": f"buyback: {dt.datetime.now(dt.UTC).strftime('%Y-%m-%dT%H:%M:%SZ')}",
        "content": base64.b64encode(blob.encode("utf-8")).decode("ascii"),
        "branch": GH_BRANCH,
    }
    if sha:
        body["sha"] = sha
    r = s.put(url, headers=GH_HEADERS, json=body, timeout=15)
    if r.status_code in (200, 201):
        print(f"[ok] GitHub push 완료 ({len(data['entries'])}건)")
    else:
        print(f"[err] GitHub push 실패: {r.status_code} {r.text[:300]}", file=sys.stderr)

# ── 메인 로직 ─────────────────────────────────────────

def main():
    data, sha = gh_get_file()
    existing = {e["rcept_no"] for e in data.get("entries", [])}
    last_seen = data.get("last_seen", "")

    today = dt.date.today()
    bgn = (today - dt.timedelta(days=SCAN_DAYS)).strftime("%Y%m%d")
    end = today.strftime("%Y%m%d")

    added = 0

    for corp_cls, market in [("Y", "KOSPI"), ("K", "KOSDAQ")]:
        print(f"[scan] {market} 주요사항보고서 {bgn}~{end}")
        d = dart("list.json", pblntf_ty="B", corp_cls=corp_cls,
                 bgn_de=bgn, end_de=end, page_count=100)

        if d.get("status") != "000":
            print(f"  → {d.get('message', 'error')}")
            continue

        items = d.get("list") or []
        print(f"  → 총 {len(items)}건 중 자기주식 필터링")

        for item in items:
            rcept_no = item.get("rcept_no", "")
            report_nm = item.get("report_nm", "")
            corp_code = item.get("corp_code", "")
            corp_name = item.get("corp_name", "")
            rcept_dt = item.get("rcept_dt", "")

            if rcept_no in existing:
                continue
            if rcept_no <= last_seen:
                continue

            if "자기주식처분" in report_nm:
                continue
            if "신탁계약" in report_nm:
                continue
            is_acq = "자기주식취득" in report_nm
            is_cancel = "자기주식소각" in report_nm
            if not (is_acq or is_cancel):
                continue

            print(f"  [hit] {corp_name} / {report_nm} / {rcept_no}")

            entry = {
                "rcept_no": rcept_no,
                "rcept_dt": rcept_dt,
                "corp_code": corp_code,
                "corp_name": corp_name,
                "corp_cls": corp_cls,
                "report_nm": report_nm,
                "type": "취득" if is_acq else "소각",
                "shares_common": None,
                "shares_other": None,
                "amount_common": None,
                "amount_other": None,
                "acq_purpose": None,
                "acq_method": None,
                "acq_period_start": None,
                "acq_period_end": None,
                "acq_decision_date": None,
                "total_shares": None,
                "ratio_pct": None,
                "dart_url": f"https://dart.fss.or.kr/dsaf001/main.do?rcpNo={rcept_no}",
            }

            # ① 본문 파싱 (주력)
            text = fetch_document_text(rcept_no)
            time.sleep(0.3)

            if is_acq and text:
                parsed = parse_acq_doc(text)
                if parsed.get("shares_common"):
                    entry["shares_common"] = parsed["shares_common"]
                if parsed.get("amount_common"):
                    entry["amount_common"] = parsed["amount_common"]
                if parsed.get("acq_purpose"):
                    entry["acq_purpose"] = parsed["acq_purpose"]
                if parsed.get("acq_method"):
                    entry["acq_method"] = parsed["acq_method"]

            elif is_cancel and text:
                parsed = parse_cancel_doc(text)
                if parsed.get("shares_common"):
                    entry["shares_common"] = parsed["shares_common"]
                if parsed.get("total_shares"):
                    entry["total_shares"] = parsed["total_shares"]

            # ② 구조화 API (보조)
            if is_acq and (not entry["shares_common"] or not entry["acq_period_start"]):
                detail = fetch_api_detail(corp_code, rcept_dt)
                time.sleep(0.3)
                if detail:
                    if not entry["shares_common"]:
                        entry["shares_common"] = to_int(detail.get("aqpln_stk_ostk"))
                    if not entry["amount_common"]:
                        entry["amount_common"] = to_int(detail.get("aqpln_prc_ostk"))
                    if not entry["acq_purpose"]:
                        entry["acq_purpose"] = (detail.get("aq_pp") or "").strip() or None
                    if not entry["acq_method"]:
                        entry["acq_method"] = (detail.get("aq_mth") or "").strip() or None
                    entry["acq_period_start"] = (detail.get("aqexpd_bgd") or "").strip() or None
                    entry["acq_period_end"] = (detail.get("aqexpd_edd") or "").strip() or None
                    entry["acq_decision_date"] = (detail.get("aq_dd") or "").strip() or None

            if entry["shares_common"] and entry.get("total_shares"):
                entry["ratio_pct"] = round(
                    entry["shares_common"] / entry["total_shares"] * 100, 2
                )

            ok = "✓" if entry["shares_common"] else "✗"
            print(f"    [{ok}] shares={entry['shares_common']}, amt={entry['amount_common']}")

            data["entries"].append(entry)
            added += 1

    all_rcepts = [e["rcept_no"] for e in data.get("entries", []) if e.get("rcept_no")]
    if all_rcepts:
        data["last_seen"] = max(all_rcepts)

    # ── 불완전 항목 재시도 (shares_common 비어있는 항목) ──
    retried = 0
    for entry in data.get("entries", []):
        if entry.get("shares_common"):
            continue
        rdt = entry.get("rcept_dt", "")
        if not rdt:
            continue
        try:
            if "-" in rdt:
                entry_date = dt.datetime.strptime(rdt, "%Y-%m-%d").date()
            elif len(rdt) == 8:
                entry_date = dt.datetime.strptime(rdt, "%Y%m%d").date()
            else:
                continue
        except ValueError:
            continue
        
        # 재시도 기간을 14일에서 60일로 대폭 연장 (과거 누락 데이터 복구용)
        if (today - entry_date).days > 60:
            continue
            
        rcept_no = entry.get("rcept_no", "")
        text = fetch_document_text(rcept_no)
        time.sleep(0.3)
        
        if text:
            is_cancel = entry.get("type") == "소각"
            if is_cancel:
                parsed = parse_cancel_doc(text)
                if parsed.get("shares_common"):
                    entry["shares_common"] = parsed["shares_common"]
                    entry["total_shares"] = parsed.get("total_shares")
                    retried += 1
                    print(f"  [재시도✓] {entry.get('corp_name','')} / shares={parsed['shares_common']}")
            else:
                parsed = parse_acq_doc(text)
                if parsed.get("shares_common"):
                    entry["shares_common"] = parsed["shares_common"]
                    entry["amount_common"] = parsed.get("amount_common")
                    entry["acq_purpose"] = parsed.get("acq_purpose")
                    entry["acq_method"] = parsed.get("acq_method")
                    retried += 1
                    print(f"  [재시도✓] {entry.get('corp_name','')} / shares={parsed['shares_common']}")
                
    if retried:
        print(f"[info] {retried}건 재시도 성공")

    if added == 0 and retried == 0:
        print("[info] 새 자사주 공시 없음")
        return

    data["entries"].sort(key=lambda e: e.get("rcept_no", ""), reverse=True)
    gh_put_file(data, sha)
    print(f"[done] {added}건 추가 완료")

if __name__ == "__main__":
    main()
