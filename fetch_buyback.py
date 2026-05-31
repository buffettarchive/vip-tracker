"""
fetch_buyback.py — 자기주식 취득·소각 공시 자동 수집
──────────────────────────────────────────────────────
Render Cron Job이 5분마다 실행.
1) GitHub에서 기존 buyback.json 읽기
2) DART list.json (pblntf_ty='B') → 주요사항보고서 중
   "자기주식취득" / "자기주식소각" 필터
3) 취득 → 구조화 API(tsstkAqDecsn.json)로 상세 수집
   소각 → document.xml 본문 파싱
4) 변경 있으면 GitHub push

환경변수:
  DART_API_KEY : opendart 인증키 (40자)
  GH_TOKEN     : GitHub PAT (repo 권한)
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

SCAN_DAYS = 3   # 최근 N일 스캔

s = requests.Session()
s.headers.update({"User-Agent": "buyback-tracker/1.0"})

GH_HEADERS = {
    "Authorization": f"Bearer {GH_TOKEN}",
    "Accept": "application/vnd.github+json",
    "X-GitHub-Api-Version": "2022-11-28",
}

# ── DART helpers ───────────────────────────────────────

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
    """콤마·공백 제거 후 정수 변환. 실패 시 None."""
    if v is None:
        return None
    try:
        return int(str(v).replace(",", "").replace(" ", "").strip())
    except (ValueError, TypeError):
        return None


def to_float(v):
    if v is None:
        return None
    try:
        return float(str(v).replace(",", "").replace("%", "").replace(" ", "").strip())
    except (ValueError, TypeError):
        return None


# ── DART: 자기주식취득결정 구조화 API ──────────────────

def fetch_buyback_detail(corp_code, rcept_dt):
    """tsstkAqDecsn.json으로 취득 상세 조회. rcept_dt(YYYYMMDD) 전후 7일 범위."""
    base = dt.datetime.strptime(rcept_dt, "%Y%m%d")
    bgn = (base - dt.timedelta(days=7)).strftime("%Y%m%d")
    end = (base + dt.timedelta(days=7)).strftime("%Y%m%d")
    d = dart("tsstkAqDecsn.json", corp_code=corp_code, bgn_de=bgn, end_de=end)
    rows = d.get("list") or []
    # 같은 접수번호에 매칭되는 행을 우선 찾고, 없으면 첫 행
    for row in rows:
        if row.get("rcept_no", "").strip():
            return row
    return rows[0] if rows else {}


# ── DART: document.xml 본문 파싱 (소각용) ──────────────

def fetch_document_text(rcept_no):
    """document.xml ZIP을 받아 텍스트 추출. 본문 미반영 시 빈 문자열."""
    try:
        r = s.get(f"{DART}/document.xml",
                  params={"crtfc_key": DART_KEY, "rcept_no": rcept_no},
                  timeout=30)
        # ZIP 매직넘버(PK) 체크
        if not r.content[:2] == b"PK":
            print(f"[nodoc] {rcept_no}: 본문 아직 없음 (ZIP 아님)")
            return ""
        zf = zipfile.ZipFile(io.BytesIO(r.content))
        for name in zf.namelist():
            raw = zf.read(name)
            for enc in ("utf-8", "euc-kr", "cp949"):
                try:
                    text = raw.decode(enc)
                    # HTML/XML 태그 제거
                    text = re.sub(r"<[^>]+>", " ", text)
                    text = re.sub(r"\s+", " ", text).strip()
                    return text
                except (UnicodeDecodeError, LookupError):
                    continue
    except Exception as e:
        print(f"[err] document.xml {rcept_no}: {e}", file=sys.stderr)
    return ""


def parse_cancellation_doc(text):
    """소각 공시 본문에서 소각 주식수를 추출."""
    if not text:
        return {}
    result = {}

    # "소각할 주식의 수" 또는 "소각 주식수" 패턴
    # 보통 "보통주식 N주" 형태
    patterns = [
        r"소각[하할]{0,2}\s*(?:주식|주권)[^0-9]*?([0-9,]+)\s*주",
        r"소각\s*(?:예정\s*)?주식[^0-9]*?보통주[식권]?\s*([0-9,]+)",
        r"보통주[식권]?\s*([0-9,]+)\s*주.*?소각",
        r"소각\s*주식\s*수[^0-9]*?([0-9,]+)",
    ]
    for pat in patterns:
        m = re.search(pat, text)
        if m:
            result["shares"] = to_int(m.group(1))
            break

    # 발행주식총수
    m2 = re.search(r"발행주식\s*총수[^0-9]*?([0-9,]+)", text)
    if m2:
        result["total_shares"] = to_int(m2.group(1))

    return result


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
        "message": f"buyback: {dt.datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%SZ')}",
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

            # "자기주식처분" 제외, "자기주식취득" 또는 "자기주식소각" 포함
            if "자기주식처분" in report_nm:
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
                "shares_common": None,     # 보통주 주식수
                "shares_other": None,      # 기타주식 주식수
                "amount_common": None,     # 보통주 금액
                "amount_other": None,      # 기타주식 금액
                "acq_purpose": None,       # 취득목적
                "acq_method": None,        # 취득방법
                "acq_period_start": None,
                "acq_period_end": None,
                "acq_decision_date": None,
                "total_shares": None,      # 발행주식총수 (구할 수 있을 때)
                "ratio_pct": None,         # 비율(%) (구할 수 있을 때)
                "dart_url": f"https://dart.fss.or.kr/dsaf001/main.do?rcpNo={rcept_no}",
            }

            if is_acq:
                detail = fetch_buyback_detail(corp_code, rcept_dt)
                time.sleep(0.3)
                if detail:
                    entry["shares_common"] = to_int(detail.get("aqpln_stk_ostk"))
                    entry["shares_other"]  = to_int(detail.get("aqpln_stk_estk"))
                    entry["amount_common"] = to_int(detail.get("aqpln_prc_ostk"))
                    entry["amount_other"]  = to_int(detail.get("aqpln_prc_estk"))
                    entry["acq_purpose"]   = (detail.get("aq_pp") or "").strip() or None
                    entry["acq_method"]    = (detail.get("aq_mth") or "").strip() or None
                    entry["acq_period_start"] = (detail.get("aqexpd_bgd") or "").strip() or None
                    entry["acq_period_end"]   = (detail.get("aqexpd_edd") or "").strip() or None
                    entry["acq_decision_date"] = (detail.get("aq_dd") or "").strip() or None
                else:
                    print(f"    [warn] 구조화 API 데이터 없음 → 본문 파싱 시도")
                    text = fetch_document_text(rcept_no)
                    time.sleep(0.3)
                    if text:
                        # 본문에서 보통주 취득 주식수 파싱
                        m = re.search(r"보통주[식권]?\s*([0-9,]+)\s*주", text)
                        if m:
                            entry["shares_common"] = to_int(m.group(1))

            elif is_cancel:
                text = fetch_document_text(rcept_no)
                time.sleep(0.3)
                parsed = parse_cancellation_doc(text)
                if parsed.get("shares"):
                    entry["shares_common"] = parsed["shares"]
                if parsed.get("total_shares"):
                    entry["total_shares"] = parsed["total_shares"]

            # 비율 계산 (발행주식총수가 있을 때)
            if entry["shares_common"] and entry["total_shares"]:
                entry["ratio_pct"] = round(
                    entry["shares_common"] / entry["total_shares"] * 100, 2
                )

            data["entries"].append(entry)
            added += 1

    # last_seen 갱신 — 전체 entries 중 최대 rcept_no
    all_rcepts = [e["rcept_no"] for e in data.get("entries", []) if e.get("rcept_no")]
    if all_rcepts:
        data["last_seen"] = max(all_rcepts)

    if added == 0:
        print("[info] 새 자사주 공시 없음 — 변경 없이 종료")
        return

    # 최신순 정렬
    data["entries"].sort(key=lambda e: e.get("rcept_no", ""), reverse=True)

    gh_put_file(data, sha)
    print(f"[done] {added}건 추가 완료")


if __name__ == "__main__":
    main()
