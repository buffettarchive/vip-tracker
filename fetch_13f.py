"""
fetch_13f.py - 미국 가치투자 거장 13F 공시 수집
버핏아카이브 최종본

v3 변경점
  - 구루 목록을 gurus.py로 분리, 제출 법인이 바뀐 구루는 CIK 여러 개를 함께 조회
  - 정정공시(13F-HR/A)는 제외하고 원공시(13F-HR) 중 기준일이 가장 늦은 것을 사용
  - 인포테이블 파일명이 제각각이어도 XML 전부를 순서대로 시도
  - 조회 실패한 구루는 기존 데이터를 유지 (목록에서 사라지지 않음)

v2 변경점
  - 종목마다 CUSIP(증권 고유번호), 증권종류(titleOfClass), 콜/풋 구분을 함께 저장
    → fetch_stock_prices.py가 CUSIP으로 정확한 티커를 찾음 (이름 추측 불필요)
  - 같은 이름이라도 CUSIP이 다르면 별도 종목으로 저장
    (예: "ISHARES TR" 아래의 여러 ETF가 하나로 뭉치던 문제 해결)
  - 한글/티커 자동 번역 중단 (잘못된 티커가 종목명에 붙던 문제 해결)
"""

import os, sys, json, time, re, base64
import datetime as dt
import requests
import urllib.parse

GH_TOKEN = os.environ.get("GH_TOKEN", "")
GH_OWNER   = "buffettarchive"
GH_REPO    = "vip-tracker"
GH_PATH    = "docs/us_vips.json"
GH_BRANCH  = "main"
GH_API     = "https://api.github.com"

s = requests.Session()
s.headers.update({
    "User-Agent": "BuffettArchive buffettarchive1@gmail.com",
    "Accept-Encoding": "gzip, deflate"
})

GH_HEADERS = {
    "Authorization": f"Bearer {GH_TOKEN}",
    "Accept": "application/vnd.github+json",
    "X-GitHub-Api-Version": "2022-11-28",
}

# ══════════════════════════════════════════════════════════════════
# 구루 목록은 gurus.py 한 곳에서 관리 (히스토리 스크립트와 공용)
# ══════════════════════════════════════════════════════════════════
from gurus import GURUS, cik_list

# ══════════════════════════════════════════════════════════════════
# SEC 요청 유틸리티 (레이트리밋 + 지수 백오프)
# ══════════════════════════════════════════════════════════════════
_last_sec_time = 0

def safe_get(url, timeout=15):
    global _last_sec_time
    for attempt in range(5):
        elapsed = time.time() - _last_sec_time
        if elapsed < 0.35:
            time.sleep(0.35 - elapsed)
        try:
            _last_sec_time = time.time()
            r = s.get(url, timeout=timeout)
            if r.status_code == 200:
                return r
            elif r.status_code in (403, 429):
                wait = min(5 * (2 ** attempt), 60)
                print(f"    [SEC 차단] {r.status_code}, {wait}초 대기 ({attempt+1}/5)")
                time.sleep(wait)
            else:
                return r
        except Exception as e:
            wait = min(5 * (2 ** attempt), 60)
            print(f"    [네트워크] {e}, {wait}초 대기 ({attempt+1}/5)")
            time.sleep(wait)
    return None

# ══════════════════════════════════════════════════════════════════
# 13F XML 파싱 (정규식 방탄 파서)
# ══════════════════════════════════════════════════════════════════
# 운용사/신탁 이름만 있는 경우(ISHARES TR 등) 증권종류를 이름에 붙여 구분
TRUST_LIKE = re.compile(r"\b(TR|TRUST|FD|FDS|FUND|FUNDS|ETF TR|SER TR|SERIES|INDEX FDS|ETF)\b$|\b(ISHARES|SPDR|VANGUARD|INVESCO|PROSHARES|SCHWAB|FIDELITY|SELECT SECTOR)\b")
GENERIC_CLASS = {"COM", "COMMON", "COM NEW", "SHS", "SHARES", "ORD", "ORD SHS", "CL A", "CL B", "CL C",
                 "COM CL A", "COM CL B", "COM CL C", "CLASS A", "CLASS B", "CLASS C", "SPONSORED ADR",
                 "SPONS ADR", "ADR", "ADS", "UNIT", "UNITS", "COM SHS", "COM PAR", "NEW", "SH BEN INT",
                 "COM UNIT", "UT", "STOCK", "COMMON STOCK", "REG SHS", "NAMEN AKT", "CAP STK CL A",
                 "CAP STK CL C", "COM SER A", "COM SER C", "ETF", "SHS ETF"}


def _tag(block, tag):
    m = re.search(rf'<[^>/]*\b{tag}\b[^>]*>(.*?)</[^>]*\b{tag}\b[^>]*>', block, re.IGNORECASE | re.DOTALL)
    return m.group(1).strip() if m else ""


def _clean(t):
    t = t.replace("&amp;", "&").replace("&AMP;", "&")
    t = re.sub(r"<!\[CDATA\[|\]\]>", "", t)
    return re.sub(r"\s+", " ", t).strip()


def parse_13f_xml(xml_content, mult=1000):
    text = xml_content.decode('utf-8', errors='ignore')
    text = re.sub(r'\sxmlns[^>]*', '', text)
    text = re.sub(r'<[a-zA-Z0-9\-]+:', '<', text)
    text = re.sub(r'</[a-zA-Z0-9\-]+:', '</', text)
    blocks = re.findall(r'<[a-zA-Z0-9_:-]*infoTable\b[^>]*>(.*?)</[a-zA-Z0-9_:-]*infoTable>', text, re.DOTALL | re.IGNORECASE)
    holdings = {}
    total_val = 0
    for block in blocks:
        raw_name = _tag(block, "nameOfIssuer")
        if not raw_name: continue
        issuer = _clean(raw_name).upper().replace(".", "").replace(",", "")
        cusip = re.sub(r"[^0-9A-Za-z]", "", _tag(block, "cusip")).upper()
        title = _clean(_tag(block, "titleOfClass")).upper()
        put_call = _clean(_tag(block, "putCall")).upper()
        stype = _clean(_tag(block, "sshPrnamtType")).upper() or "SH"
        m2 = _tag(block, "value")
        try: val = int(float(m2.replace(',', ''))) * mult if m2 else 0
        except: val = 0
        m3 = _tag(block, "sshPrnamt")
        try: shares = int(float(m3.replace(',', ''))) if m3 else 0
        except: shares = 0

        name = issuer
        if title and title not in GENERIC_CLASS and TRUST_LIKE.search(issuer):
            name = f"{issuer} {title}"            # ISHARES TR CORE S&P500 ETF
        if put_call in ("PUT", "CALL"):
            name = f"{name} ({put_call})"         # 옵션은 주식과 별도 행

        key = (cusip or name) + "|" + put_call
        if key in holdings:
            holdings[key]['value'] += val
            holdings[key]['shares'] += shares
        else:
            holdings[key] = {'name': name, 'cusip': cusip, 'title': title, 'type': stype,
                             'put_call': put_call, 'value': val, 'shares': shares}
        total_val += val
    result = []
    for h in holdings.values():
        h['weight'] = round((h['value'] / total_val * 100), 2) if total_val > 0 else 0
        result.append(h)
    result.sort(key=lambda x: x['value'], reverse=True)
    return result, total_val

def _hr_filings(cik):
    """한 CIK의 원공시 13F-HR 목록 [(report_date, filing_date, accession)]"""
    r = safe_get(f"https://data.sec.gov/submissions/CIK{cik}.json")
    if not r or r.status_code != 200:
        print(f"    [CIK {cik}] submissions 조회 실패")
        return []
    recent = r.json().get("filings", {}).get("recent", {})
    out = []
    for i, f in enumerate(recent.get("form", [])):
        if f != "13F-HR":
            continue
        rd = recent["reportDate"][i]
        if rd:
            out.append((rd, recent["filingDate"][i], recent["accessionNumber"][i]))
    return out


def _xml_candidates(files):
    """인포테이블일 가능성이 높은 순서로 XML 파일명 정렬"""
    xmls = [f["name"] for f in files
            if f["name"].lower().endswith(".xml") and "primary_doc" not in f["name"].lower()]
    def rank(n):
        l = n.lower()
        if "infotable" in l or "info_table" in l: return 0
        if "13f" in l or "table" in l or "information" in l: return 1
        return 2
    return sorted(xmls, key=rank)


def _holdings_from_filing(cik, acc, date):
    acc = acc.replace("-", "")
    base = f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{acc}"
    idx_r = safe_get(f"{base}/index.json")
    if not idx_r or idx_r.status_code != 200:
        return [], 0
    files = idx_r.json().get("directory", {}).get("item", [])
    # 2022-12-31 기준일 이후 공시는 금액이 달러 단위 (이전은 천 달러 단위)
    mult = 1 if (date or "") >= "2022-12-31" else 1000
    for xml_file in _xml_candidates(files):
        xml_r = safe_get(f"{base}/{xml_file}")
        if xml_r and xml_r.status_code == 200:
            holdings, total = parse_13f_xml(xml_r.content, mult)
            if holdings:
                return holdings, total
    return [], 0


def get_valid_13f_holdings(cik_value):
    """최신 13F-HR 보유내역. cik_value는 CIK 문자열 또는 리스트"""
    cands = []
    for order, cik in enumerate(cik_list(cik_value)):
        for rd, fd, acc in _hr_filings(cik):
            cands.append((rd, -order, fd, cik, acc))
    if not cands:
        return [], 0, None
    # 기준일 최신순, 같은 기준일이면 리스트 앞쪽 법인 우선, 그다음 최근 제출분
    cands.sort(key=lambda x: (x[0], x[1], x[2]), reverse=True)
    for rd, _, fd, cik, acc in cands[:4]:
        holdings, total = _holdings_from_filing(cik, acc, rd)
        if holdings:
            return holdings, total, rd
        print(f"    [파싱 실패] CIK {cik} {acc} ({rd}), 이전 공시 시도")
    return [], 0, None

# ══════════════════════════════════════════════════════════════════
# 한글 종목명 자동 번역 시스템
# 구조: SEC company_tickers.json(1회 다운로드) → 티커 매칭
#       → 네이버 API(캐시 미스분만) → docs/stock_names_kr.json 캐시
# ══════════════════════════════════════════════════════════════════
KR_CACHE_PATH = "docs/stock_names_kr.json"

def build_ticker_map():
    """SEC 전체 종목 데이터에서 종목명→티커 매핑 (요청 1회)"""
    r = safe_get("https://www.sec.gov/files/company_tickers.json")
    if not r or r.status_code != 200:
        print("[한글화] SEC 티커 데이터 실패, 번역 건너뜀")
        return {}
    tmap = {}
    for entry in r.json().values():
        title = re.sub(r'[^A-Z0-9& ]', '', entry.get("title", "").upper()).strip()
        ticker = entry.get("ticker", "")
        if title and ticker:
            tmap[title] = ticker
    print(f"[한글화] SEC 티커맵 {len(tmap)}건 로드")
    return tmap

def match_ticker(name, tmap):
    """13F 종목명 → 티커 매칭 (정확→접두어→첫2단어 순)"""
    clean = re.sub(r'[^A-Z0-9& ]', '', name.upper()).strip()
    if clean in tmap: return tmap[clean]
    for title, ticker in tmap.items():
        if len(clean) >= 6 and (title.startswith(clean) or clean.startswith(title)):
            return ticker
    words = clean.split()[:2]
    if len(words) >= 2:
        prefix = ' '.join(words)
        for title, ticker in tmap.items():
            if title.startswith(prefix):
                return ticker
    return None

def naver_korean_name(ticker):
    """네이버 증권 API로 한글 종목명 조회 (5초 타임아웃 엄수)"""
    for ex in ['O', 'N', 'A']:  # NASDAQ, NYSE, AMEX
        try:
            r = requests.get(
                f"https://m.stock.naver.com/api/stock/{ticker}.{ex}/basic",
                timeout=5,
                headers={"User-Agent": "Mozilla/5.0"}
            )
            if r.status_code == 200:
                name = r.json().get("stockName", "")
                if name:
                    return f"{name} ({ticker})"
        except requests.exceptions.Timeout:
            print(f"    [네이버] {ticker} 타임아웃, 건너뜀")
            return None
        except:
            pass
    return None

def load_kr_cache():
    """GitHub에서 한글명 캐시 로드"""
    url = f"{GH_API}/repos/{GH_OWNER}/{GH_REPO}/contents/{KR_CACHE_PATH}?ref={GH_BRANCH}"
    try:
        r = requests.get(url, headers=GH_HEADERS, timeout=10)
        if r.status_code == 200:
            data = json.loads(base64.b64decode(r.json()["content"]).decode("utf-8"))
            print(f"[한글화] 캐시 {len(data)}건 로드")
            return data, r.json()["sha"]
    except:
        pass
    return {}, None

def save_kr_cache(cache, sha):
    """한글명 캐시 GitHub 저장"""
    url = f"{GH_API}/repos/{GH_OWNER}/{GH_REPO}/contents/{KR_CACHE_PATH}"
    blob = json.dumps(cache, ensure_ascii=False, indent=2)
    body = {
        "message": f"kr_names: {len(cache)} stocks",
        "content": base64.b64encode(blob.encode("utf-8")).decode("ascii"),
        "branch": GH_BRANCH,
    }
    if sha: body["sha"] = sha
    try:
        requests.put(url, headers=GH_HEADERS, json=body, timeout=15)
        print(f"[한글화] 캐시 저장 ({len(cache)}건)")
    except:
        print("[한글화] 캐시 저장 실패 (다음 실행에서 재시도)")

def translate_portfolios(portfolios):
    """전체 포트폴리오 종목명 한글 번역 (안전 + 자동 누적)"""
    cache, cache_sha = load_kr_cache()
    tmap = build_ticker_map()
    if not tmap:
        return  # SEC 데이터 실패 시 번역 단계 통째로 건너뜀

    # 고유 종목명 수집
    all_names = set()
    for g in portfolios.values():
        for h in g["holdings"]:
            all_names.add(h["name"])

    # 캐시 미스 목록
    miss = [n for n in all_names if n not in cache]
    print(f"[한글화] 종목 {len(all_names)}건 중 캐시 히트 {len(all_names)-len(miss)}건, 신규 {len(miss)}건")

    # ── 신규 종목만 네이버 API 조회 (시간 예산 10분, 2초 간격) ──
    start = time.time()
    MAX_TIME = 600  # 10분
    done = 0
    for name in miss:
        if time.time() - start > MAX_TIME:
            print(f"[한글화] 시간 예산 초과, {len(miss)-done}건 다음 실행으로 이월")
            break
        ticker = match_ticker(name, tmap)
        if ticker:
            kr = naver_korean_name(ticker)
            if kr:
                cache[name] = kr
            else:
                cache[name] = f"{name} ({ticker})"  # 네이버 실패 → 영문+티커
        # 티커 못 찾으면 캐시 안 넣고 원문 유지 (다음 실행에서 재시도)
        done += 1
        time.sleep(2)  # ★ 네이버 차단 방지 핵심

    # 적용
    for g in portfolios.values():
        for h in g["holdings"]:
            if h["name"] in cache:
                h["name"] = cache[h["name"]]

    # 캐시 저장 (신규 번역이 있을 때만)
    if done > 0:
        save_kr_cache(cache, cache_sha)

    print(f"[한글화] 완료: 번역 {done}건")

# ══════════════════════════════════════════════════════════════════
# GitHub 파일 I/O
# ══════════════════════════════════════════════════════════════════
def gh_get_sha():
    url = f"{GH_API}/repos/{GH_OWNER}/{GH_REPO}/contents/{GH_PATH}?ref={GH_BRANCH}"
    try:
        r = requests.get(url, headers=GH_HEADERS, timeout=20)
        if r.status_code == 200:
            return r.json()["sha"]
    except Exception:
        pass
    return None


def gh_get_existing():
    """기존 us_vips.json (실패한 구루의 직전 데이터 유지용)"""
    url = f"{GH_API}/repos/{GH_OWNER}/{GH_REPO}/contents/{GH_PATH}?ref={GH_BRANCH}"
    try:
        r = requests.get(url, headers={**GH_HEADERS, "Accept": "application/vnd.github.raw"}, timeout=60)
        if r.status_code == 200:
            return r.json().get("portfolios", {})
    except Exception as e:
        print(f"[기존 데이터] 로드 실패: {e}")
    return {}

def gh_put(data, sha):
    url = f"{GH_API}/repos/{GH_OWNER}/{GH_REPO}/contents/{GH_PATH}"
    blob = json.dumps(data, ensure_ascii=False, indent=2)
    body = {
        "message": f"us_vips: {dt.datetime.now(dt.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')}",
        "content": base64.b64encode(blob.encode("utf-8")).decode("ascii"),
        "branch": GH_BRANCH,
    }
    if sha: body["sha"] = sha
    r = requests.put(url, headers=GH_HEADERS, json=body, timeout=120)
    print(f"[업로드] {GH_PATH}: HTTP {r.status_code}")
    if r.status_code not in (200, 201):
        print(r.text[:500])
        sys.exit(1)

# ══════════════════════════════════════════════════════════════════
# 메인
# ══════════════════════════════════════════════════════════════════
def main():
    sha = gh_get_sha()
    previous = gh_get_existing()
    portfolios = {}
    failed = []
    total = len(GURUS)

    print(f"[시작] {total}명 거장 조회")
    for idx, (name, cik) in enumerate(GURUS.items(), 1):
        print(f"[{idx}/{total}] {name}")
        try:
            holdings, val, date = get_valid_13f_holdings(cik)
            if holdings:
                portfolios[name] = {"report_date": date, "total_value_usd": val, "holdings": holdings}
                print(f"  ✓ {len(holdings)}종목 ({date})")
            else:
                failed.append(name)
                print(f"  ✗ 실패")
        except Exception as e:
            failed.append(name)
            print(f"  ✗ 에러: {e}")
        if name not in portfolios and name in previous:
            portfolios[name] = previous[name]
            print(f"  → 기존 데이터 유지 ({previous[name].get('report_date')})")
        time.sleep(1.5)
        if idx % 10 == 0 and idx < total:
            time.sleep(30)

    # 한글/티커 자동 번역은 중단 (잘못된 티커가 종목명에 붙는 문제). 영문 원문 유지.

    # ── 업로드 ──
    payload = {
        "updated_at": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "portfolios": portfolios
    }
    if portfolios:
        gh_put(payload, sha)

    print(f"\n{'='*50}")
    print(f"성공: {len(portfolios)}명 / 실패: {len(failed)}명")
    if failed:
        for f in failed: print(f"  - {f}")
    stale = sorted((v.get("report_date") or "", k) for k, v in portfolios.items())
    latest = stale[-1][0] if stale else ""
    old = [(d, k) for d, k in stale if d < latest]
    if old:
        print(f"최신 기준일({latest})보다 오래된 구루 {len(old)}명:")
        for d, k in old: print(f"  - {k}: {d}")
    print(f"{'='*50}")

if __name__ == "__main__":
    main()
