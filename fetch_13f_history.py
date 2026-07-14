#!/usr/bin/env python3
"""
fetch_13f_history.py — 81명 구루 과거 13F-HR 수집 + 분기별 변동 계산

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

GURUS = {
    "마이클 버리 (사이언 에셋)": "0001649339",
    "워런 버핏 (버크셔 해서웨이)": "0001067983",
    "빌 애크먼 (퍼싱 스퀘어)": "0001336528",
    "세스 클라만 (바우포스트 그룹)": "0001061768",
    "리 루 (히말라야 캐피탈)": "0001709323",
    "넬슨 펠츠 (트리안 펀드)": "0001345471",
    "바이킹 글로벌 (안드레아스 할보센)": "0001103804",
    "칼 아이칸 (아이칸 캐피탈)": "0000921669",
    "단 롭 (서드 포인트)": "0001040273",
    "빌 밀러 (밀러 밸류 파트너스)": "0001135778",
    "프렘 왓사 (페어팩스)": "0000915191",
    "토마스 게이너 (마켈 그룹)": "0001096343",
    "리차드 제나 (제나 인베스트먼트)": "0001390777",
    "모니시 파브라이 (파브라이 인베스트먼트)": "0001549575",
    "데이비드 테퍼 (아팔루사)": "0001656456",
    "스탠리 드러켄밀러 (듀케인)": "0001536411",
    "하워드 막스 (오크트리)": "0001535472",
    "데이비드 아인혼 (그린라이트)": "0001079114",
    "밸류액트 캐피탈": "0001397545",
    "빌 & 멀린다 게이츠 재단 (캐스케이드)": "0001166559",
    "체이스 콜먼 (타이거 글로벌)": "0001167483",
    "스티븐 맨델 (론 파인)": "0001061165",
    "브루스 버코위츠 (페어홈)": "0001056831",
    "메이슨 호킨스 (사우스이스턴)": "0000807985",
    "척 아크레 (아크레 캐피탈)": "0001112520",
    "도지 앤 콕스": "0000315066",
    "크리스 혼 (TCI 펀드)": "0001647251",
    "퍼스트 이글 인베스트먼트": "0000810958",
    "데이비드 에이브럼스 (아브람스 캐피탈)": "0001358706",
    "트위디 브라운": "0000732905",
    "리 애인슬리 (매버릭 캐피탈)": "0000934639",
    "빌 니그렌 (해리스 어소시에이츠)": "0000813917",
    "글렌 그린버그 (브레이브 워리어)": "0001553733",
    "존 로저스 (아리엘 인베스트먼트)": "0000936753",
    "크리스토퍼 데이비스 (데이비스 어드바이저스)": "0001036325",
    "토마스 루소 (가드너 루소)": "0000860643",
    "데이비드 롤프 (웨지우드)": "0000859804",
    "윌리엄 폰 뮈플링 (칸티용)": "0001279936",
    "퍼스트 퍼시픽 어드바이저스": "0001377581",
    "레온 쿠퍼만 (오메가)": "0000898202",
    "헨리 엘렌보겐 (듀러블 캐피탈)": "0001798849",
    "데니스 홍 (쇼스프링)": "0001766908",
    "데이비드 카츠 (매트릭스)": "0001016287",
    "크리스토퍼 블룸스트란 (셈퍼 아우구스투스)": "0001115373",
    "루안 커니프 (세쿼이아)": "0001720792",
    "알타록 파트너스": "0001631014",
    "폴렌 캐피탈": "0001034524",
    "써드 애비뉴 매니지먼트": "0001099281",
    "스티븐 체크 (체크 캐피탈)": "0001032814",
    "토레이 펀드": "0000098758",
    "얙트먼 에셋 매니지먼트": "0000905567",
    "로버트 올스타인 (올스타인)": "0000947996",
    "그린헤이븐 어소시에이츠": "0000846222",
    "뮬렌캠프": "0001133219",
    "브라이언 로렌스 (오크클리프)": "0001657335",
    "팻 도시 (도시 애셋)": "0001671657",
    "힐만 캐피탈": "0001314620",
    "톰 밴크로프트 (마카이라)": "0001540866",
    "사만다 맥레모어 (페이션트)": "0001854794",
    "클리포드 소신 (CAS)": "0001697591",
    "글렌 웰링 (인게이지드)": "0001559771",
    "밸리 포지 캐피탈": "0001697868",
    "린셀 트레인": "0001484150",
    "프란시스 추 (추 어소시에이츠)": "0001389403",
    "리차드 프제나 (프제나)": "0001027796",
    "가이 스피어 (아쿠아마린)": "0001404599",
    "단 용핑 (H&H)": "0001759760",
    "아브람스 바이슨": "0001317588",
    "노버트 루 (펀치 카드)": "0001419050",
    "트리플 프론드 파트너스": "0001454502",
    "프랑수아 로숑 (지베르니)": "0001641864",
    "존 아미티지 (에저턴)": "0001581811",
    "테리 스미스 (펀드스미스)": "0001569205",
    "알렉스 뢰퍼스 (아틀란틱)": "0001063296",
    "사라 케터러 (코즈웨이)": "0001165797",
    "월러스 웨이츠 (웨이츠)": "0000883965",
    "메이어스 & 파워": "0001070134",
    "벌칸 밸류 파트너스": "0001556785",
    "칸 브라더스": "0001039565",
    "해리 번 (사운드 쇼어)": "0000820124",
    "젠슨 인베스트먼트": "0001106129",
}

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


def find_infotable_file(items):
    """index.json의 파일 목록에서 13F infotable 파일을 찾는다. 우선순위 순서."""
    candidates = []
    for item in items:
        fname = item.get("name", "")
        fl = fname.lower()
        # 1순위: infotable이 이름에 있는 XML
        if "infotable" in fl and fl.endswith(".xml"):
            return fname
        # 2순위: 13f + xml
        if "13f" in fl and fl.endswith(".xml"):
            candidates.append(("a", fname))
        # 3순위: information + xml
        if "information" in fl and fl.endswith(".xml"):
            candidates.append(("b", fname))
        # 4순위: 아무 XML (primary_doc 제외)
        if fl.endswith(".xml") and fl != "primary_doc.xml" and "R" not in fname[:2]:
            candidates.append(("c", fname))
        # 5순위: infotable이 이름에 있는 txt (내용이 XML인 경우 많음)
        if "infotable" in fl and fl.endswith(".txt"):
            candidates.append(("b2", fname))
        # 6순위: 13f가 이름에 있는 txt
        if "13f" in fl and fl.endswith(".txt") and "index" not in fl:
            candidates.append(("e", fname))

    if candidates:
        candidates.sort(key=lambda x: x[0])
        return candidates[0][1]
    return None


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
    xml_filename = find_infotable_file(items)

    if not xml_filename:
        if _diag_count < DIAG_LIMIT:
            _diag_count += 1
            fnames = [it.get("name", "") for it in items]
            log.info(f"    [DIAG] XML 파일 못 찾음. 디렉토리 파일들: {fnames}")
        return []

    xml_url = f"https://www.sec.gov/Archives/edgar/data/{cik_plain}/{acc_clean}/{xml_filename}"
    accept_type = "application/xml" if xml_filename.lower().endswith(".xml") else "text/plain"
    xml_raw = safe_get(xml_url, accept=accept_type)
    if not xml_raw:
        if _diag_count < DIAG_LIMIT:
            _diag_count += 1
            log.info(f"    [DIAG] XML 다운로드 실패: {xml_filename}")
        return []

    entries = parse_13f_xml(xml_raw)
    if not entries and _diag_count < DIAG_LIMIT:
        _diag_count += 1
        preview = xml_raw[:500].decode("utf-8", errors="replace")
        log.info(f"    [DIAG] XML 파싱 0건. 파일: {xml_filename}, 처음 500자:\n{preview}")

    return entries


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
    with open(LATEST_CHANGES, "w", encoding="utf-8") as f:
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


def collect_history(max_quarters=None, guru_filter=None, start_year=2013):
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

    for idx, (name, cik) in enumerate(gurus.items()):
        log.info(f"[{idx+1}/{len(gurus)}] {name} (CIK {cik})")
        filings = get_all_13f_filings(cik, start_year=start_year)
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
                "cik": cik, "accession": f["accession"],
                "filing_date": f["filing_date"], "report_date": f["report_date"],
            }
        if (idx + 1) % COOLDOWN_EVERY == 0 and (idx + 1) < len(gurus):
            log.info(f"  ⏳ 쿨다운 {COOLDOWN_SEC}초...")
            time.sleep(COOLDOWN_SEC)

    all_quarters = sorted(quarter_guru_filings.keys())
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
        log.info(f"  → {quarter}: ✓{collected}명 성공 / ✗{failed}명 실패, 총 {len(archive['portfolios'])}명\n")

    log.info(f"\n━━━ 3단계: 분기별 변동내역 계산 ━━━")
    for i in range(1, len(all_quarters)):
        prev_q = all_quarters[i - 1]
        curr_q = all_quarters[i]
        changes_path = CHANGES_DIR / f"{curr_q}.json"
        if changes_path.exists():
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

    save_manifest()

    log.info(f"\n━━━ 완료 ━━━")
    archive_files = sorted(ARCHIVE_DIR.glob("*.json")) if ARCHIVE_DIR.exists() else []
    log.info(f"아카이브: {len(archive_files)}개 분기")
    if archive_files:
        log.info(f"기간: {archive_files[0].stem} ~ {archive_files[-1].stem}")


def main():
    parser = argparse.ArgumentParser(description="81명 구루 13F 히스토리 백필")
    parser.add_argument("--quarters", type=int, default=None, help="구루당 최대 분기 수")
    parser.add_argument("--guru", type=str, default=None, help="특정 구루만 (이름 일부)")
    parser.add_argument("--start-year", type=int, default=2014, help="수집 시작년도 (기본: 2014)")
    args = parser.parse_args()
    collect_history(max_quarters=args.quarters, guru_filter=args.guru, start_year=args.start_year)


if __name__ == "__main__":
    main()
