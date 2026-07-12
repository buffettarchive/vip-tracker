"""
fetch_13f.py — 미국 가치투자 거장 13F 공시 수집 + 한글 종목명 자동 번역
버핏아카이브 최종본
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
# 검증된 64명 CIK (SEC EDGAR 13F-HR 제출 투자자문사 기준)
# ══════════════════════════════════════════════════════════════════
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

    # ── 4차 추가: 데이터로마 누락분 17명 (SEC 직접 확인) ──
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
def parse_13f_xml(xml_content):
    text = xml_content.decode('utf-8', errors='ignore')
    text = re.sub(r'\sxmlns[^>]*', '', text)
    text = re.sub(r'<[a-zA-Z0-9\-]+:', '<', text)
    text = re.sub(r'</[a-zA-Z0-9\-]+:', '</', text)
    blocks = re.findall(r'<[a-zA-Z0-9_:-]*infoTable\b[^>]*>(.*?)</[a-zA-Z0-9_:-]*infoTable>', text, re.DOTALL | re.IGNORECASE)
    holdings = {}
    total_val = 0
    for block in blocks:
        m = re.search(r'<[^>]*nameOfIssuer[^>]*>(.*?)</[^>]*nameOfIssuer>', block, re.IGNORECASE)
        if not m: continue
        issuer = m.group(1).strip().upper().replace(".", "").replace(",", "").replace("&AMP;", "&")
        m2 = re.search(r'<[^>]*value[^>]*>(.*?)</[^>]*value>', block, re.IGNORECASE)
        try: val = int(float(m2.group(1).strip().replace(',', ''))) * 1000 if m2 else 0
        except: val = 0
        m3 = re.search(r'<[^>]*sshPrnamt[^>]*>(.*?)</[^>]*sshPrnamt>', block, re.IGNORECASE)
        try: shares = int(float(m3.group(1).strip().replace(',', ''))) if m3 else 0
        except: shares = 0
        if issuer in holdings:
            holdings[issuer]['value'] += val
            holdings[issuer]['shares'] += shares
        else:
            holdings[issuer] = {'name': issuer, 'value': val, 'shares': shares}
        total_val += val
    result = []
    for h in holdings.values():
        h['weight'] = round((h['value'] / total_val * 100), 2) if total_val > 0 else 0
        result.append(h)
    result.sort(key=lambda x: x['value'], reverse=True)
    return result, total_val

def get_valid_13f_holdings(cik):
    r = safe_get(f"https://data.sec.gov/submissions/CIK{cik}.json")
    if not r or r.status_code != 200:
        return [], 0, None
    recent = r.json().get("filings", {}).get("recent", {})
    forms = recent.get("form", [])
    hr_indices = [i for i, f in enumerate(forms) if f.startswith("13F-HR")]
    if not hr_indices:
        return [], 0, None
    for i in hr_indices[:3]:
        acc = recent["accessionNumber"][i].replace("-", "")
        date = recent["reportDate"][i]
        idx_r = safe_get(f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{acc}/index.json")
        if not idx_r or idx_r.status_code != 200:
            continue
        files = idx_r.json().get("directory", {}).get("item", [])
        xml_file = None
        for f in files:
            fn = f["name"].lower()
            if fn.endswith(".xml") and ("infotable" in fn or "info_table" in fn):
                xml_file = f["name"]; break
        if not xml_file:
            for f in files:
                fn = f["name"].lower()
                if fn.endswith(".xml") and "primary_doc" not in fn:
                    xml_file = f["name"]; break
        if not xml_file:
            continue
        xml_r = safe_get(f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{acc}/{xml_file}")
        if xml_r and xml_r.status_code == 200:
            holdings, total = parse_13f_xml(xml_r.content)
            if holdings:
                return holdings, total, date
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
    r = safe_get(url)
    if r and r.status_code == 200:
        return r.json()["sha"]
    return None

def gh_put(data, sha):
    url = f"{GH_API}/repos/{GH_OWNER}/{GH_REPO}/contents/{GH_PATH}"
    blob = json.dumps(data, ensure_ascii=False, indent=2)
    body = {
        "message": f"us_vips: {dt.datetime.now(dt.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')}",
        "content": base64.b64encode(blob.encode("utf-8")).decode("ascii"),
        "branch": GH_BRANCH,
    }
    if sha: body["sha"] = sha
    requests.put(url, headers=GH_HEADERS, json=body, timeout=15)

# ══════════════════════════════════════════════════════════════════
# 메인
# ══════════════════════════════════════════════════════════════════
def main():
    sha = gh_get_sha()
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
        time.sleep(1.5)
        if idx % 10 == 0 and idx < total:
            time.sleep(30)

    # ── 한글 종목명 번역 ──
    if portfolios:
        translate_portfolios(portfolios)

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
    print(f"{'='*50}")

if __name__ == "__main__":
    main()
