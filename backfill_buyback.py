"""
backfill_buyback.py — 과거 데이터 재구축 (v3.2 - 빈칸 강제 복구 로직 포함)
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
s.headers.update({"User-Agent": "buyback-backfill/3.2"})
GH_HEADERS = {"Authorization": f"Bearer {GH_TOKEN}", "Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}

def dart(endpoint, **params):
    params["crtfc_key"] = DART_KEY
    for i in range(3):
        try:
            r = s.get(f"{DART}/{endpoint}", params=params, timeout=20)
            return r.json()
        except: time.sleep(1.5 * (i + 1))
    return {"status": "999", "list": []}

def to_int(v):
    if v is None: return None
    try: return int(str(v).replace(",", "").replace(" ", "").replace("주", "").replace("원", "").strip())
    except: return None

def fetch_document_text(rcept_no):
    try:
        r = s.get(f"{DART}/document.xml", params={"crtfc_key": DART_KEY, "rcept_no": rcept_no}, timeout=30)
        if not r.content[:2] == b"PK": return ""
        zf = zipfile.ZipFile(io.BytesIO(r.content))
        for name in zf.namelist():
            raw = zf.read(name)
            for enc in ("utf-8", "euc-kr", "cp949"):
                try:
                    text = raw.decode(enc)
                    text = re.sub(r"<[^>]+>", " ", text)
                    return re.sub(r"\s+", " ", text).strip()
                except: continue
    except: pass
    return ""

def parse_acq_doc(text):
    if not text: return {}
    result = {}
    for pat in [
        r"1\.\s*(?:취득|상환)예정주식.*?(?:보통주|종류주|우선주|기타주|상환전환우선주)?[식]?\s*([0-9, ]{3,})",
        r"(?:취득|상환)\s*예정\s*주식.*?(?:보통주|종류주|우선주|기타주|상환전환우선주)?[식]?\s*([0-9, ]{3,})",
        r"(?:보통주|종류주|우선주|기타주|상환전환우선주)[식]?\s*\(?주\)?\s*([0-9, ]{3,})",
        r"(?:보통주|종류주|우선주|기타주|상환전환우선주)[식]?\s*[:\s]*([0-9, ]{3,})",
        r"(?:취득|상환)\s*(?:할\s*)?주식[의]?\s*수[^0-9]*?([0-9, ]{3,})",
        r"(?:취득|상환)\s*수량[^0-9]*?([0-9, ]{3,})"
    ]:
        m = re.search(pat, text)
        if m:
            val = to_int(m.group(1))
            if val and val >= 10: result["shares_common"] = val; break
    for pat in [
        r"3\.\s*(?:취득|상환)예정금액.*?(?:보통주|종류주|우선주|기타주)?[식]?\s*([0-9, ]{4,})",
        r"(?:취득|상환)\s*예정\s*금액.*?(?:보통주|종류주|우선주|기타주)?[식]?\s*([0-9, ]{4,})",
        r"(?:취득|상환)\s*(?:할\s*)?금액[^0-9]*?([0-9, ]{4,})"
    ]:
        m = re.search(pat, text)
        if m:
            val = to_int(m.group(1))
            if val and val > 1000: result["amount_common"] = val; break
    for pat in [
        r"(?:취득|상환)\s*목적\s*[:\s]*([^\n\r]{2,100}?)(?:\s*\d+\.|\s*(?:취득|상환)\s*방법|\s*(?:취득|상환)\s*예상|\s*비고)",
        r"(?:취득|상환)\s*목적\s*[:\s]*(.{2,100}?)(?:취득방법|상환방법|취득예상|예상기간|이사회)"
    ]:
        m = re.search(pat, text)
        if m:
            val = m.group(1).strip().rstrip(".")
            if val and len(val) >= 2: result["acq_purpose"] = val; break
    for pat in [
        r"(?:취득|상환)\s*방법\s*[:\s]*([^\n\r]{2,100}?)(?:\s*\d+\.|\s*(?:취득|상환)\s*예상|\s*(?:취득|상환)\s*기간|\s*비고)",
        r"(?:취득|상환)\s*방법\s*[:\s]*(.{2,100}?)(?:취득예상|상환예상|예상기간|이사회|비고|기타)"
    ]:
        m = re.search(pat, text)
        if m:
            val = m.group(1).strip().rstrip(".")
            if val and len(val) >= 2: result["acq_method"] = val; break
    return result

def parse_cancel_doc(text):
    if not text: return {}
    result = {}
    for pat in [
        r"1\.\s*소각할\s*주식.*?(?:보통주|종류주|우선주|기타주|상환전환우선주)?[식]?\s*([0-9, ]{3,})",
        r"소각[하할]{0,2}\s*(?:주식|주권)[^0-9]*?([0-9, ]{3,})\s*주",
        r"(?:보통주|종류주|우선주|기타주|상환전환우선주)[식권]?\s*([0-9, ]{3,})\s*주.*?소각",
        r"소각\s*주식\s*수[^0-9]*?([0-9, ]{3,})"
    ]:
        m = re.search(pat, text)
        if m:
            val = to_int(m.group(1))
            if val and val >= 10: result["shares_common"] = val; break
    m2 = re.search(r"발행주식\s*총수[^0-9]*?([0-9,]+)", text)
    if m2: result["total_shares"] = to_int(m2.group(1))
    return result

def fetch_api_detail(corp_code, rcept_dt):
    try: base = dt.datetime.strptime(rcept_dt, "%Y%m%d")
    except:
        try: base = dt.datetime.strptime(rcept_dt, "%Y-%m-%d")
        except: return {}
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
        "message": f"backfill-buyback-fix: {dt.datetime.now(dt.UTC).strftime('%Y-%m-%dT%H:%M:%SZ')}",
        "content": base64.b64encode(blob.encode("utf-8")).decode("ascii"),
        "branch": GH_BRANCH,
    }
    if sha: body["sha"] = sha
    s.put(url, headers=GH_HEADERS, json=body, timeout=15)

def main():
    today = dt.date.today()
    if len(sys.argv) >= 3:
        bgn_str, end_str = sys.argv[1], sys.argv[2]
    else:
        bgn_str = (today - dt.timedelta(days=365)).strftime("%Y%m%d")
        end_str = today.strftime("%Y%m%d")

    data, sha = gh_get_file()
    existing_map = {e["rcept_no"]: e for e in data.get("entries", [])}
    added_or_fixed = 0

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
                d = dart("list.json", pblntf_ty="B", corp_cls=corp_cls, bgn_de=b, end_de=e, page_no=page, page_count=100)
                if d.get("status") != "000": break
                items = d.get("list") or []
                if not items: break

                for item in items:
                    rcept_no = item.get("rcept_no", "")
                    existing_entry = existing_map.get(rcept_no)
                    
                    # [핵심] 이미 존재하더라도 숫자가 비어있으면 건너뛰지 않고 억지로 다시 파싱함
                    if existing_entry and existing_entry.get("shares_common"):
                        continue
                        
                    report_nm = item.get("report_nm", "")
                    if "자기주식처분" in report_nm or "신탁계약" in report_nm: continue
                    is_acq = "자기주식취득" in report_nm
                    is_cancel = "자기주식소각" in report_nm
                    if not (is_acq or is_cancel): continue

                    entry = {
                        "rcept_no": rcept_no, "rcept_dt": item.get("rcept_dt", ""),
                        "corp_code": item.get("corp_code", ""), "corp_name": item.get("corp_name", ""),
                        "corp_cls": corp_cls, "report_nm": report_nm, "type": "취득" if is_acq else "소각",
                        "shares_common": None, "amount_common": None, "acq_purpose": None,
                        "acq_method": None, "acq_period_start": None, "acq_period_end": None,
                        "total_shares": None, "ratio_pct": None,
                        "dart_url": f"https://dart.fss.or.kr/dsaf001/main.do?rcpNo={rcept_no}",
                    }

                    text = fetch_document_text(rcept_no)
                    time.sleep(0.3)

                    if is_acq and text:
                        parsed = parse_acq_doc(text)
                        entry.update({k: v for k, v in parsed.items() if v})
                    elif is_cancel and text:
                        parsed = parse_cancel_doc(text)
                        entry.update({k: v for k, v in parsed.items() if v})

                    if is_acq and not entry["shares_common"]:
                        detail = fetch_api_detail(item.get("corp_code", ""), item.get("rcept_dt", ""))
                        time.sleep(0.3)
                        if detail:
                            if not entry["shares_common"]: entry["shares_common"] = to_int(detail.get("aqpln_stk_ostk"))
                            if not entry["amount_common"]: entry["amount_common"] = to_int(detail.get("aqpln_prc_ostk"))
                            if not entry["acq_purpose"]: entry["acq_purpose"] = (detail.get("aq_pp") or "").strip() or None
                            if not entry["acq_method"]: entry["acq_method"] = (detail.get("aq_mth") or "").strip() or None

                    if entry["shares_common"] and entry.get("total_shares"):
                        entry["ratio_pct"] = round(entry["shares_common"] / entry["total_shares"] * 100, 2)

                    # 빈칸 데이터 덮어쓰기 완료
                    if existing_entry:
                        existing_entry.update(entry)
                        print(f"  [빈칸복구✓] {item.get('corp_name', '')}")
                    else:
                        data["entries"].append(entry)
                        existing_map[rcept_no] = entry
                        print(f"  [신규추가✓] {item.get('corp_name', '')}")
                        
                    added_or_fixed += 1

                total_pages = int(d.get("total_page", 1))
                if page >= total_pages: break
                page += 1
                time.sleep(0.3)
            time.sleep(0.3)
        chunk_start = chunk_end + dt.timedelta(days=1)

    if added_or_fixed > 0:
        data["entries"].sort(key=lambda e: e.get("rcept_no", ""), reverse=True)
        all_rcepts = [e["rcept_no"] for e in data["entries"] if e.get("rcept_no")]
        if all_rcepts: data["last_seen"] = max(all_rcepts)
        gh_put_file(data, sha)

if __name__ == "__main__":
    main()
