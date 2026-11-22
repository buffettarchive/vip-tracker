#!/usr/bin/env python3
"""
fetch_13f_history.py — 전체 구루 과거 13F-HR 수집 + 분기별 변동 계산

변경사항 (v4):
  - 구루 목록을 gurus.py로 분리, 제출 법인이 바뀐 구루는 CIK 여러 개의 공시를 이어 붙임
    (같은 분기는 리스트 앞쪽 법인 우선)
  - GURUS에서 빠진 이름은 아카이브, 변동내역에서 자동 정리
  - 보유내역이 새로 채워진 분기는 변동내역을 다시 계산
  - 인포테이블 후보 파일을 순서대로 모두 시도
  - us_vips_changes.json(최신 변동)은 항상 가장 최근 분기로 저장

변경사항 (v3):
  - XML 네임스페이스 접두사 범용 매칭 (ns1, ns2, n1, 등 모두 지원)
  - 파일 탐색 범위 확대 (.xml 외에 .txt infotable도 시도)
  - [DIAG] 진단 로그 추가 (첫 5건 실패에 대해 상세 출력)
  - --start-year 기본값 2013
"""

import json, os, re, sys, time, argparse, logging
from datetime import datetime
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

SEC_UA = "BuffettArchive buffettarchive1@gmail.com"
SEC_HEADERS = {"User-Agent": SEC_UA, "Accept": "application/json"}
MIN_INTERVAL = 0.35
COOLDOWN_EVERY = 10
COOLDOWN_SEC = 30
MAX_RETRIES = 4
BACKOFF_BASE = 5
DIAG_LIMIT = 5  # 첫 N건 실패만 상세 진단 출력

ARCHIVE_DIR = Path("docs/us_vips_archive")
CHANGES_DIR = Path("docs/us_vips_changes")
LATEST_CHANGES = Path("docs/us_vips_changes.json")
MANIFEST_PATH = Path("docs/us_vips_manifest.json")

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S")
log = logging.getLogger("13f-history")

_diag_count = 0

# 구루 목록은 gurus.py 한 곳에서 관리 (fetch_13f.py와 공용)
from gurus import GURUS, cik_list

_last_request_time = 0.0

def safe_get(url, accept="application/json"):
    global _last_request_time
    for attempt in range(MAX_RETRIES + 1):
        elapsed = time.time() - _last_request_time
        if elapsed < MIN_INTERVAL:
            time.sleep(MIN_INTERVAL - elapsed)
        _last_request_time = time.time()
        try:
            req = Request(url, headers={**SEC_HEADERS, "Accept": accept})
            with urlopen(req, timeout=30) as resp:
                return resp.read()
        except HTTPError as e:
            if e.code in (403, 429, 503):
                wait = min(BACKOFF_BASE * (2 ** attempt), 60)
                log.warning(f"  HTTP {e.code} → {wait}s 대기 ({attempt+1}/{MAX_RETRIES})")
                time.sleep(wait)
            else:
                return None
        except (URLError, TimeoutError):
            if attempt < MAX_RETRIES:
                time.sleep(BACKOFF_BASE * (2 ** attempt))
            else:
                return None
    return None


def report_date_to_quarter(date_str):
    d = datetime.strptime(date_str, "%Y-%m-%d")
    q = (d.month - 1) // 3 + 1
    return f"{d.year}_Q{q}"


def get_all_13f_filings(cik, start_year=2013):
    cik_padded = cik.zfill(10)
    url = f"https://data.sec.gov/submissions/CIK{cik_padded}.json"
    raw = safe_get(url)
    if not raw:
        return []
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return []

    filings_recent = data.get("filings", {}).get("recent", {})
    filings_files = data.get("filings", {}).get("files", [])

    all_forms = list(filings_recent.get("form", []))
    all_accessions = list(filings_recent.get("accessionNumber", []))
    all_filing_dates = list(filings_recent.get("filingDate", []))
    all_report_dates = list(filings_recent.get("reportDate", []))

    for fobj in filings_files:
        fname = fobj.get("name", "")
        if not fname:
            continue
        batch_raw = safe_get(f"https://data.sec.gov/submissions/{fname}")
        if not batch_raw:
            continue
        try:
            batch = json.loads(batch_raw)
        except json.JSONDecodeError:
            continue
        all_forms.extend(batch.get("form", []))
        all_accessions.extend(batch.get("accessionNumber", []))
        all_filing_dates.extend(batch.get("filingDate", []))
        all_report_dates.extend(batch.get("reportDate", []))

    results = []
    for i, form in enumerate(all_forms):
        if form != "13F-HR":
            continue
        if i >= len(all_accessions) or i >= len(all_report_dates):
            continue
        report_date = all_report_dates[i]
        if not report_date:
            continue
        try:
            if int(report_date[:4]) < start_year:
                continue
        except ValueError:
            continue
        results.append({
            "accession": all_accessions[i],
            "filing_date": all_filing_dates[i] if i < len(all_filing_dates) else "",
            "report_date": report_date,
            "quarter": report_date_to_quarter(report_date),
        })

    results.sort(key=lambda x: x["report_date"], reverse=True)
    return results


def parse_13f_xml(xml_bytes):
    """범용 네임스페이스 지원 XML 파서. ns1:, ns2:, n1:, 접두사없음 모두 처리."""
    try:
        text = xml_bytes.decode("utf-8", errors="replace")
    except Exception:
        return []

    # 임의 네임스페이스 접두사 매칭: <prefix:tag> or <tag>
    NS = r"(?:\w+:)?"

    entries = []
    # infoTable 블록 분리 — 여러 네임스페이스 접두사 대응
    blocks = re.split(rf"</?{NS}infoTable\b[^>]*>", text, flags=re.IGNORECASE)

    for block in blocks:
        name_m = re.search(rf"<{NS}nameOfIssuer>(.*?)</{NS}nameOfIssuer>", block, re.I | re.S)
        cusip_m = re.search(rf"<{NS}cusip>(.*?)</{NS}cusip>", block, re.I | re.S)
        value_m = re.search(rf"<{NS}value>(.*?)</{NS}value>", block, re.I | re.S)
        shares_m = re.search(rf"<{NS}(?:sshPrnamt|Amt)>(.*?)</{NS}(?:sshPrnamt|Amt)>", block, re.I | re.S)
        type_m = re.search(rf"<{NS}(?:sshPrnamtType|Type)>(.*?)</{NS}(?:sshPrnamtType|Type)>", block, re.I | re.S)

        if not name_m or not value_m:
            continue
        name = name_m.group(1).strip()
        cusip = cusip_m.group(1).strip() if cusip_m else ""
        try:
            value = int(re.sub(r"[^\d]", "", value_m.group(1)))
        except ValueError:
            value = 0
        try:
            shares = int(re.sub(r"[^\d]", "", shares_m.group(1))) if shares_m else 0
        except ValueError:
            shares = 0
        stype = type_m.group(1).strip() if type_m else "SH"
        entries.append({"name": name, "cusip": cusip, "value_x1000": value, "shares": shares, "type": stype})
    return entries


def find_infotable_files(items):
    """index.json의 파일 목록에서 13F infotable 후보 파일을 우선순위 순서로 반환"""
    candidates = []
    for item in items:
        fname = item.get("name", "")
        fl = fname.lower()
        if fl.endswith(".xml") and fl != "primary_doc.xml":
            if "infotable" in fl or "info_table" in fl:
                candidates.append((0, fname))
            elif "13f" in fl or "table" in fl or "information" in fl:
                candidates.append((1, fname))
            else:
                candidates.append((2, fname))
        elif fl.endswith(".txt") and "index" not in fl:
            if "infotable" in fl:
                candidates.append((3, fname))
            elif "13f" in fl:
                candidates.append((4, fname))
    candidates.sort(key=lambda x: x[0])
    return [c[1] for c in candidates]


def find_infotable_file(items):
    c = find_infotable_files(items)
    return c[0] if c else None


def get_holdings_for_filing(cik, accession, guru_name=""):
    global _diag_count
    cik_plain = str(int(cik))
    acc_clean = accession.replace("-", "")
    index_url = f"https://www.sec.gov/Archives/edgar/data/{cik_plain}/{acc_clean}/index.json"

    raw = safe_get(index_url)
    if not raw:
        if _diag_count < DIAG_LIMIT:
            _diag_count += 1
            log.info(f"    [DIAG] index.json 로드 실패: {index_url}")
        return []

    try:
        idx = json.loads(raw)
    except json.JSONDecodeError:
        return []

    items = idx.get("directory", {}).get("item", [])
    cands = find_infotable_files(items)

    if not cands:
        if _diag_count < DIAG_LIMIT:
            _diag_count += 1
            fnames = [it.get("name", "") for it in items]
            log.info(f"    [DIAG] XML 파일 못 찾음. 디렉토리 파일들: {fnames}")
        return []

    for xml_filename in cands:
        xml_url = f"https://www.sec.gov/Archives/edgar/data/{cik_plain}/{acc_clean}/{xml_filename}"
        accept_type = "application/xml" if xml_filename.lower().endswith(".xml") else "text/plain"
        xml_raw = safe_get(xml_url, accept=accept_type)
        if not xml_raw:
            continue
        entries = parse_13f_xml(xml_raw)
        if entries:
            return entries

    if _diag_count < DIAG_LIMIT:
        _diag_count += 1
        log.info(f"    [DIAG] 파싱 0건. {guru_name} {accession} 후보 파일: {cands}")
    return []


def compute_changes(prev_holdings, curr_holdings):
    def make_key(h):
        return h.get("cusip") or h.get("name", "")
    def aggregate(holdings):
        m = {}
        for h in holdings:
            k = make_key(h)
            if not k:
                continue
            if k in m:
                m[k]["shares"] += h.get("shares", 0)
                m[k]["value_x1000"] += h.get("value_x1000", 0)
            else:
                m[k] = {**h, "shares": h.get("shares", 0), "value_x1000": h.get("value_x1000", 0)}
        return m

    prev_map = aggregate(prev_holdings)
    curr_map = aggregate(curr_holdings)
    changes = []

    for k in sorted(set(list(prev_map.keys()) + list(curr_map.keys()))):
        prev = prev_map.get(k)
        curr = curr_map.get(k)
        if curr and not prev:
            changes.append({"name": curr["name"], "cusip": curr.get("cusip", ""), "action": "NEW",
                            "shares": curr["shares"], "value_x1000": curr["value_x1000"],
                            "prev_shares": 0, "change_pct": None})
        elif prev and not curr:
            changes.append({"name": prev["name"], "cusip": prev.get("cusip", ""), "action": "EXIT",
                            "shares": 0, "value_x1000": 0,
                            "prev_shares": prev["shares"], "change_pct": -100.0})
        elif prev and curr and prev["shares"] != curr["shares"]:
            pct = round((curr["shares"] - prev["shares"]) / prev["shares"] * 100, 2) if prev["shares"] else None
            action = "ADD" if curr["shares"] > prev["shares"] else "REDUCE"
            changes.append({"name": curr["name"], "cusip": curr.get("cusip", ""), "action": action,
                            "shares": curr["shares"], "value_x1000": curr["value_x1000"],
                            "prev_shares": prev["shares"], "change_pct": pct})

    order = {"NEW": 0, "ADD": 1, "REDUCE": 2, "EXIT": 3}
    changes.sort(key=lambda x: (order.get(x["action"], 9), -(x.get("value_x1000") or 0)))
    return changes


def load_archive(quarter):
    path = ARCHIVE_DIR / f"{quarter}.json"
    if not path.exists():
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

def save_archive(quarter, archive):
    ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
    path = ARCHIVE_DIR / f"{quarter}.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(archive, f, ensure_ascii=False, indent=1)
    log.info(f"  📁 저장: {path} ({len(archive.get('portfolios', {}))}명)")

def save_changes(quarter, prev_quarter, all_changes):
    CHANGES_DIR.mkdir(parents=True, exist_ok=True)
    payload = {"period": quarter, "compared_to": prev_quarter,
               "generated_at": datetime.utcnow().isoformat() + "Z", "changes": all_changes}
    path = CHANGES_DIR / f"{quarter}.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=1)
    total = sum(len(v) for v in all_changes.values())
    log.info(f"  📊 변동저장: {path} (총 {total}건)")

def save_manifest():
    archive_quarters = sorted([f.stem for f in ARCHIVE_DIR.glob("*.json")]) if ARCHIVE_DIR.exists() else []
    changes_quarters = sorted([f.stem for f in CHANGES_DIR.glob("*.json")]) if CHANGES_DIR.exists() else []
    manifest = {"archive_quarters": archive_quarters, "changes_quarters": changes_quarters}
    with open(MANIFEST_PATH, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=1)
    log.info(f"  📋 매니페스트: 아카이브 {len(archive_quarters)}개, 변동 {len(changes_quarters)}개")


def prune_removed_gurus():
    """GURUS에서 빠진 이름을 아카이브, 변동내역에서 제거. 수정된 분기 집합 반환"""
    keep = set(GURUS.keys())
    touched = set()
    if ARCHIVE_DIR.exists():
        for path in sorted(ARCHIVE_DIR.glob("*.json")):
            data = load_archive(path.stem)
            if not data:
                continue
            gone = [k for k in data.get("portfolios", {}) if k not in keep]
            if gone:
                for k in gone:
                    del data["portfolios"][k]
                save_archive(path.stem, data)
                touched.add(path.stem)
                log.info(f"  🧹 {path.stem}: 목록 외 구루 제거 {gone}")
    if CHANGES_DIR.exists():
        for path in sorted(CHANGES_DIR.glob("*.json")):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
            except Exception:
                continue
            ch = data.get("changes", {})
            gone = [k for k in ch if k not in keep]
            if gone:
                for k in gone:
                    del ch[k]
                with open(path, "w", encoding="utf-8") as f:
                    json.dump(data, f, ensure_ascii=False, indent=1)
    return touched


def write_latest_changes():
    """가장 최근 분기의 변동내역을 us_vips_changes.json으로 복사"""
    if not CHANGES_DIR.exists():
        return
    files = sorted(CHANGES_DIR.glob("*.json"))
    if not files:
        return
    with open(files[-1], "r", encoding="utf-8") as f:
        payload = json.load(f)
    with open(LATEST_CHANGES, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=1)
    log.info(f"  📌 최신 변동: {files[-1].stem}")


def collect_history(max_quarters=None, guru_filter=None, start_year=2013, end_quarter=None):
    global _diag_count
    _diag_count = 0

    gurus = GURUS
    if guru_filter:
        gurus = {k: v for k, v in GURUS.items() if guru_filter in k}
        if not gurus:
            log.error(f"'{guru_filter}' 에 매칭되는 구루 없음")
            return
        log.info(f"필터: {list(gurus.keys())}")

    log.info(f"수집 범위: {start_year}년 이후 (XML 포맷)")
    log.info(f"━━━ 1단계: {len(gurus)}명 파일링 목록 수집 ━━━")
    quarter_guru_filings = {}

    prune_removed_gurus()
    modified = set()

    for idx, (name, cik_value) in enumerate(gurus.items()):
        ciks = cik_list(cik_value)
        log.info(f"[{idx+1}/{len(gurus)}] {name} (CIK {', '.join(ciks)})")
        by_quarter = {}
        for cik in ciks:
            for f in get_all_13f_filings(cik, start_year=start_year):
                if f["quarter"] not in by_quarter:      # 앞쪽 법인, 최근 제출분 우선
                    by_quarter[f["quarter"]] = {**f, "cik": cik}
        filings = sorted(by_quarter.values(), key=lambda x: x["report_date"], reverse=True)
        if not filings:
            log.warning(f"  ⚠️ {start_year}년 이후 13F-HR 없음")
            continue
        if max_quarters:
            filings = filings[:max_quarters]
        log.info(f"  📋 {len(filings)}개 분기: {filings[0]['quarter']} ~ {filings[-1]['quarter']}")
        for f in filings:
            q = f["quarter"]
            if q not in quarter_guru_filings:
                quarter_guru_filings[q] = {}
            quarter_guru_filings[q][name] = {
                "cik": f["cik"], "accession": f["accession"],
                "filing_date": f["filing_date"], "report_date": f["report_date"],
            }
        if (idx + 1) % COOLDOWN_EVERY == 0 and (idx + 1) < len(gurus):
            log.info(f"  ⏳ 쿨다운 {COOLDOWN_SEC}초...")
            time.sleep(COOLDOWN_SEC)

    all_quarters = sorted(quarter_guru_filings.keys())
    if end_quarter:
        all_quarters = [q for q in all_quarters if q <= end_quarter]
        log.info(f"종료 분기: {end_quarter}")
    if not all_quarters:
        log.error("수집할 분기 없음")
        return
    log.info(f"\n총 {len(all_quarters)}개 분기: {all_quarters[0]} ~ {all_quarters[-1]}")

    log.info(f"\n━━━ 2단계: 분기별 보유내역 수집 ━━━")
    for qi, quarter in enumerate(all_quarters):
        existing = load_archive(quarter)
        guru_filings = quarter_guru_filings[quarter]
        already_done = set(existing["portfolios"].keys()) if existing else set()
        to_collect = {k: v for k, v in guru_filings.items() if k not in already_done}

        if not to_collect:
            log.info(f"[Q {qi+1}/{len(all_quarters)}] {quarter} — 이미 완료 ({len(already_done)}명), 스킵")
            continue

        log.info(f"[Q {qi+1}/{len(all_quarters)}] {quarter} — {len(to_collect)}명 수집 (기존 {len(already_done)}명)")
        archive = existing or {"period": quarter, "collected_at": "", "portfolios": {}}
        collected = 0
        failed = 0
        for gi, (guru_name, finfo) in enumerate(to_collect.items()):
            holdings = get_holdings_for_filing(finfo["cik"], finfo["accession"], guru_name)
            if holdings:
                total_val = sum(h.get("value_x1000", 0) for h in holdings)
                archive["portfolios"][guru_name] = {
                    "cik": finfo["cik"], "filing_date": finfo["filing_date"],
                    "report_date": finfo["report_date"], "holdings": holdings,
                    "total_value_x1000": total_val, "holding_count": len(holdings),
                }
                collected += 1
            else:
                failed += 1
                log.warning(f"    ✗ {guru_name}: 파싱 실패")
            if (gi + 1) % COOLDOWN_EVERY == 0 and (gi + 1) < len(to_collect):
                log.info(f"    ⏳ 쿨다운 {COOLDOWN_SEC}초...")
                time.sleep(COOLDOWN_SEC)

        archive["collected_at"] = datetime.utcnow().isoformat() + "Z"
        save_archive(quarter, archive)
        if collected:
            modified.add(quarter)
        log.info(f"  → {quarter}: ✓{collected}명 성공 / ✗{failed}명 실패, 총 {len(archive['portfolios'])}명\n")

    log.info(f"\n━━━ 3단계: 분기별 변동내역 계산 ━━━")
    for i in range(1, len(all_quarters)):
        prev_q = all_quarters[i - 1]
        curr_q = all_quarters[i]
        changes_path = CHANGES_DIR / f"{curr_q}.json"
        if changes_path.exists() and curr_q not in modified and prev_q not in modified:
            log.info(f"  {curr_q} vs {prev_q} — 이미 계산됨, 스킵")
            continue
        prev_archive = load_archive(prev_q)
        curr_archive = load_archive(curr_q)
        if not prev_archive or not curr_archive:
            continue
        all_changes = {}
        both = set(prev_archive["portfolios"].keys()) & set(curr_archive["portfolios"].keys())
        for guru_name in sorted(both):
            prev_h = prev_archive["portfolios"][guru_name].get("holdings", [])
            curr_h = curr_archive["portfolios"][guru_name].get("holdings", [])
            changes = compute_changes(prev_h, curr_h)
            if changes:
                all_changes[guru_name] = changes
        if all_changes:
            save_changes(curr_q, prev_q, all_changes)

    write_latest_changes()
    save_manifest()

    log.info(f"\n━━━ 완료 ━━━")
    archive_files = sorted(ARCHIVE_DIR.glob("*.json")) if ARCHIVE_DIR.exists() else []
    log.info(f"아카이브: {len(archive_files)}개 분기")
    if archive_files:
        log.info(f"기간: {archive_files[0].stem} ~ {archive_files[-1].stem}")


def main():
    parser = argparse.ArgumentParser(description="전체 구루 13F 히스토리 백필")
    parser.add_argument("--quarters", type=int, default=None, help="구루당 최대 분기 수")
    parser.add_argument("--guru", type=str, default=None, help="특정 구루만 (이름 일부)")
    parser.add_argument("--start-year", type=int, default=2014, help="수집 시작년도 (기본: 2014)")
    parser.add_argument("--end-quarter", type=str, default=None, help="수집 종료 분기 (예: 2026_Q1)")
    args = parser.parse_args()
    collect_history(max_quarters=args.quarters, guru_filter=args.guru, start_year=args.start_year, end_quarter=args.end_quarter)


if __name__ == "__main__":
    main()
