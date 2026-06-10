"""
backfill_buyback.py — 자기주식 취득·소각 과거 데이터 재구축 (v3)
──────────────────────────────────────────────────────────
Render에서 1회 실행. GitHub의 buyback.json을 읽고 결과를 push.
사용법: python backfill_buyback.py [시작일 YYYYMMDD] [종료일 YYYYMMDD]
기본: 최근 365일

환경변수: DART_API_KEY, GH_TOKEN
"""

import os, sys, json, time, re, io, zipfile, base64
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

s = requests.Session()
s.headers.update({"User-Agent": "buyback-backfill/3.0"})

GH_HEADERS = {
    "Authorization": f"Bearer {GH_TOKEN}",
    "Accept": "application/vnd.github+json",
    "X-GitHub-Api-Version": "2022-11-28",
}


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


def fetch_document_text(rcept_no):
    try:
        r = s.get(f"{DART}/document.xml",
                  params={"crtfc_key": DART_KEY, "rcept_no": rcept_no},
                  timeout=30)
        if not r.content[:2] == b"PK":
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
        print(f"    [err] doc {rcept_no}: {e}", file=sys.stderr)
    return ""


def parse_acq_doc(text):
    if not text:
        return {}
    result = {}
    for pat in [
        r"보통주[식권]?\s*[:\s]*([0-9][0-9,]*)",
        r"취득\s*예정\s*주식[^0-9]*?([0-9][0-9,]+)",
        r"취득\s*(?:할\s*)?주식[의]?\s*수[^0-9]*?([0-9][0-9,]+)",
    ]:
        m = re.search(pat, text)
        if m:
            val = to_int(m.group(1))
            if val and val > 0:
                result["shares_common"] = val
                break
    for pat in [
        r"취득\s*예정\s*금액[^보]*보통주[식]?\s*([0-9][0-9,]+)",
        r"취득\s*예정\s*금액[^0-9]*?([0-9][0-9,]+)",
        r"취득\s*(?:할\s*)?금액[^0-9]*?([0-9][0-9,]+)",
    ]:
        m = re.search(pat, text)
        if m:
            val = to_int(m.group(1))
            if val and val > 1000:
                result["amount_common"] = val
                break
    for pat in [
        r"취득\s*목적\s*[:\s]*([^\n\r]{5,100}?)(?:\s*\d+\.|\s*취득\s*방법|\s*취득\s*예상|\s*비고)",
        r"취득\s*목적\s*[:\s]*(.{5,100}?)(?:취득방법|취득예상|예상기간|이사회)",
    ]:
        m = re.search(pat, text)
        if m:
            val = m.group(1).strip().rstrip(".")
            if val and len(val) >= 3:
                result["acq_purpose"] = val
                break
    for pat in [
        r"취득\s*방법\s*[:\s]*([^\n\r]{3,100}?)(?:\s*\d+\.|\s*취득\s*예상|\s*취득\s*기간|\s*비고)",
        r"취득\s*방법\s*[:\s]*(.{3,100}?)(?:취득예상|예상기간|이사회|비고|기타)",
    ]:
        m = re.search(pat, text)
        if m:
            val = m.group(1).strip().rstrip(".")
            if val and len(val) >= 2:
                result["acq_method"] = val
                break
    return result


def parse_cancel_doc(text):
    if not text:
        return {}
    result = {}
    for pat in [
        r"소각[하할]{0,2}\s*(?:주식|주권)[^0-9]*?([0-9,]+)\s*주",
        r"보통주[식권]?\s*([0-9,]+)\s*주.*?소각",
        r"소각\s*주식\s*수[^0-9]*?([0-9,]+)",
    ]:
        m = re.search(pat, text)
        if m:
            result["shares_common"] = to_int(m.group(1))
            break
    m2 = re.search(r"발행주식\s*총수[^0-9]*?([0-9,]+)", text)
    if m2:
        result["total_shares"] = to_int(m2.group(1))
    return result


def fetch_api_detail(corp_code, rcept_dt):
    try:
        base = dt.datetime.strptime(rcept_dt, "%Y%m%d")
    except ValueError:
        try:
            base = dt.datetime.strptime(rcept_dt, "%Y-%m-%d")
        except ValueError:
            return {}
    bgn = (base - dt.timedelta(days=14)).strftime("%Y%m%d")
    end = (base + dt.timedelta(days=14)).strftime("%Y%m%d")
    d = dart("tsstkAqDecsn.json", corp_code=corp_code, bgn_de=bgn, end_de=end)
    rows = d.get("list") or []
    return rows[0] if rows else {}


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
        "message": f"backfill-buyback: {dt.datetime.now(dt.UTC).strftime('%Y-%m-%dT%H:%M:%SZ')}",
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


def main():
    today = dt.date.today()
    if len(sys.argv) >= 3:
        bgn_str, end_str = sys.argv[1], sys.argv[2]
    else:
        bgn_str = (today - dt.timedelta(days=365)).strftime("%Y%m%d")
        end_str = today.strftime("%Y%m%d")

    print(f"[backfill] 기간: {bgn_str} ~ {end_str}")

    data, sha = gh_get_file()
    existing = {e["rcept_no"] for e in data.get("entries", [])}
    added = 0

    bgn_date = dt.datetime.strptime(bgn_str, "%Y%m%d").date()
    end_date = dt.datetime.strptime(end_str, "%Y%m%d").date()

    chunk_start = bgn_date
    while chunk_start <= end_date:
        chunk_end = min(chunk_start + dt.timedelta(days=30), end_date)
        b = chunk_start.strftime("%Y%m%d")
        e = chunk_end.strftime("%Y%m%d")

        for corp_cls, market in [("Y", "KOSPI"), ("K", "KOSDAQ")]:
            print(f"\n[scan] {market} {b}~{e}")
            page = 1
            while True:
                d = dart("list.json", pblntf_ty="B", corp_cls=corp_cls,
                         bgn_de=b, end_de=e, page_no=page, page_count=100)
                if d.get("status") != "000":
                    print(f"  → {d.get('message', 'error')}")
                    break

                items = d.get("list") or []
                if not items:
                    break

                for item in items:
                    rcept_no = item.get("rcept_no", "")
                    report_nm = item.get("report_nm", "")
                    corp_code = item.get("corp_code", "")
                    corp_name = item.get("corp_name", "")
                    rcept_dt = item.get("rcept_dt", "")

                    if rcept_no in existing:
                        continue
                    if "자기주식처분" in report_nm:
                        continue
                    if "신탁계약" in report_nm:
                        continue
                    is_acq = "자기주식취득" in report_nm
                    is_cancel = "자기주식소각" in report_nm
                    if not (is_acq or is_cancel):
                        continue

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
                    time.sleep(0.5)

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

                    if entry["shares_common"] and entry["total_shares"]:
                        entry["ratio_pct"] = round(
                            entry["shares_common"] / entry["total_shares"] * 100, 2
                        )

                    ok = "✓" if entry["shares_common"] else "✗"
                    print(f"  [{ok}] {corp_name} / {report_nm}")

                    data["entries"].append(entry)
                    existing.add(rcept_no)
                    added += 1

                total_pages = int(d.get("total_page", 1))
                if page >= total_pages:
                    break
                page += 1
                time.sleep(0.3)

            time.sleep(0.3)

        chunk_start = chunk_end + dt.timedelta(days=1)

    data["entries"].sort(key=lambda e: e.get("rcept_no", ""), reverse=True)
    all_rcepts = [e["rcept_no"] for e in data["entries"] if e.get("rcept_no")]
    if all_rcepts:
        data["last_seen"] = max(all_rcepts)

    if added == 0:
        print("\n[info] 새 데이터 없음")
        return

    gh_put_file(data, sha)
    print(f"\n[done] 총 {added}건 추가, 전체 {len(data['entries'])}건")


if __name__ == "__main__":
    main()
