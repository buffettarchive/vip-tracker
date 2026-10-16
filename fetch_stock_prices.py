#!/usr/bin/env python3
"""
fetch_stock_prices.py v12 - 구루 현재 포트폴리오 시세 업데이트 (완전자동 매핑)

[티커 결정 순서] 앞 단계에서 가격까지 확보되면 끝, 실패하면 다음 단계로 넘어감
  1. MANUAL           : 사람이 확인한 매핑 (신뢰)
  2. CUSIP 캐시        : 과거 OpenFIGI로 확정된 CUSIP -> 티커 (신뢰)
  3. 이름 캐시         : 과거 이름검색 결과 (불신 -> 회사명 대조 통과해야 채택)
  4. OpenFIGI         : CUSIP -> 티커 (Bloomberg 무료 API, 신뢰)
  5. Yahoo 이름검색    : 검색결과 회사명 대조 통과해야 채택
  6. Finnhub 이름검색  : 검색결과 회사명 대조 통과해야 채택

[자동 안전장치]
  - 회사명 대조: 13F 종목명과 Yahoo가 돌려준 회사명이 다르면 버림
    (예: NEW YORK TIMES -> ASML 같은 오매핑 자동 차단, 잘못된 캐시도 자동 삭제)
  - 채권 자동 제외: CUSIP 7~8번째 자리에 영문자가 있으면 채권(사채, MTN 등)
  - 상장폐지 추정: 최근 14일간 거래가 없으면 가격 없음으로 처리
  - 못 찾은 종목은 7일간 재검색 생략 (실행시간 단축)

[출력] docs/stock_prices.json 형식은 기존과 동일 (키 = 대문자 종목명)
[환경변수] FINNHUB_API_KEY (선택), OPENFIGI_API_KEY (선택, 없어도 작동)
"""
import json, time, logging, re, os
from datetime import datetime, timedelta
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.parse import quote_plus, quote
from urllib.error import HTTPError

VIPS_PATH = Path("docs/us_vips.json")
PRICES_PATH = Path("docs/stock_prices.json")
CACHE_PATH = Path("docs/ticker_cache.json")
YF_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
FH_KEY = os.environ.get("FINNHUB_API_KEY", "")
FH = "https://finnhub.io/api/v1"
FIGI_KEY = os.environ.get("OPENFIGI_API_KEY", "")
FIGI_URL = "https://api.openfigi.com/v3/mapping"
MISS_RETRY_DAYS = 7
STALE_DAYS = 14

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S")
log = logging.getLogger("prices")

# ── 수동 매핑 (사람이 확인한 것만, 더 이상 추가할 필요 없음) ──
# 여기 티커가 가격 조회에 실패하면(티커 변경 등) 자동으로 다음 단계로 넘어감
MANUAL = {
    "COCA COLA CO":"KO","COCA-COLA CO":"KO","KROGER CO":"KR",
    "BK OF AMERICA CORP":"BAC","BANK AMERICA CORP":"BAC",
    "S&P GLOBAL INC":"SPGI","BLOCK H & R INC":"HRB",
    "PG&E CORP":"PCG","KKR & CO L P DEL":"KKR","KKR & CO INC":"KKR",
    "CI&T INC/UNITED STATES-A":"CINT",
    "AMAZON COM INC":"AMZN","DISNEY WALT CO":"DIS","WALT DISNEY CO":"DIS",
    "JEFFERIES FINANCIAL GROUP IN":"JEF","JEFFERIES FINANCIAL GROUP INC":"JEF",
    "TENCENT MUSIC ENTMT GROUP":"TME",
    "ELEVANCE HEALTH INC FORMERLY":"ELV","ELEVANCE HEALTH INC":"ELV",
    "FERGUSON ENTERPRISES INC (FERG)":"FERG","FERGUSON ENTERPRISES INC":"FERG",
    "WILLIS TOWERS WATSON PLC LTD":"WTW","WILLIS TOWERS WATSON PLC":"WTW",
    "TOPBUILD COR":"BLD","TOPBUILD CORP":"BLD","EAGLE MATLS INC":"EXP",
    "SUN CTRY AIRLS HLDGS INC":"SNCY","MIDWESTONE FINL GROUP INC NE":"MOFG",
    "ERMENEGILDO ZEGNA N V":"ZGN","CENTRAIS ELET BRAS SA":"EBR",
    "FIRST AMERN FINL CORP":"FAF","FAIRFAX FINL HLDGS LTD":"FFH",
    "GENUINE PARTS CO":"GPC","AON PLC":"AON","MOLINA HEALTHCARE INC":"MOH",
    "ECHOSTAR CORPORATION":"SATS","CEMEX SAB DE CV":"CX",
    "CNH INDL N V":"CNH","WIX COM LTD":"WIX",
    "INTERNATIONAL FLAVORS AND FRAGRANCES INC":"IFF",
    "AMERICAN ELECTRIC POWER COMPANY":"AEP",
    "JETBLUE AIRWAYS CORP":"JBLU","JETBLUE AIRWAYS CORP (JBLU)":"JBLU",
    "CAESARS ENTERTAINMENT INC":"CZR","ILLUMINA INC":"ILMN",
    "MASIMO CORP":"MASI","AIR LEASE CORP":"AL",
    "KENNEDY-WILSON HOLDINGS INC":"KW","SPROUTS FARMERS MARKET INC":"SFM",
    "SOUTHWEST GAS HLDGS INC":"SWX","MGM RESORTS INTERNATIONAL":"MGM",
    "HOLOGIC INC":"HOLX","COMERICA INC":"CMA","CIVITAS RESOURCES INC":"CIVI",
    "CHEVRON CORPORATION":"CVX","CHEVRON CORP":"CVX",
    "CHUBB LTD SWITZ":"CB","CHUBB LTD":"CB",
    "SIRIUSXM HOLDINGS INC":"SIRI","SIRIUS XM HOLDINGS INC":"SIRI",
    "BERKSHIRE HATHAWAY INC DEL":"BRK-B",
    "CONFLUENT INC":"CFLT","CYBERARK SOFTWARE LTD":"CYBR",
    "EVENTBRITE INC":"EB","GUESS INC":"GES","HILLENBRAND INC":"HLI",
    "NU HLDGS LTD":"NU","OLAPLEX HLDGS INC":"OLPX","ON HLDG AG":"ONON",
    "SYNOVUS FINL CORP":"SNV","THERMON GROUP HLDGS INC":"THR",
    "TREEHOUSE FOODS INC":"THS","WHITE MTNS INS GROUP LTD":"WTM",
    "DAYFORCE INC":"DAY","DENNYS CORP":"DENN",
    "CALAVO GROWERS INC":"CVGW","CANTALOUPE INC":"CTLP",
    "POTLATCHDELTIC CORPORATION":"PCH","PLYMOUTH INDL REIT INC":"PLYM",
    "SUNOPTA INC":"STKL","TEGNA INC":"TGNA",
    "GENEDX HOLDINGS CORP":"WGS","VESTIS CORPORATION":"VSTS",
    "IAC INC":"IAC","FORTREA HLDGS INC":"FTRE","COSTAR GROUP INC":"CSGP",
    "LIONSGATE STUDIOS CORP":"LION","COTERRA ENERGY INC":"CTRA",
    "Coterra Energy Inc.":"CTRA","Tri Pointe Group Inc.":"TPH",
    "RESTAURANT BRANDS INTL INC":"QSR","WESCO INTL INC":"WCC",
    "UNION PAC CORP":"UNP","T-MOBILE US INC":"TMUS","META PLATFORMS INC":"META",
    "CHARTER COMMUNICATIONS INC":"CHTR","BOOKING HOLDINGS INC":"BKNG",
    "UNITEDHEALTH GROUP INC":"UNH","JOHNSON & JOHNSON":"JNJ",
    "PROCTER & GAMBLE CO":"PG","CHARLES SCHWAB CORP":"SCHW","FISERV INC":"FI",
    "AGILENT TECHNOLOGIES INC":"A","TYLER TECHNOLOGIES INC":"TYL",
    "ROPER TECHNOLOGIES INC":"ROP","BROWN & BROWN INC":"BRO",
    "GLOBAL PAYMENTS INC":"GPN","ARCH CAP GROUP LTD":"ACGL","WATERS CORP":"WAT",
    "LIBERTY GLOBAL LTD":"LBTYA","MADISON SQUARE GARDEN SPORTS":"MSGS",
    "NVIDIA CORPORATION":"NVDA","PFIZER INC":"PFE","HALLIBURTON CO":"HAL",
    "PALANTIR TECHNOLOGIES INC":"PLTR","MAGNOLIA OIL & GAS CORP":"MGY",
    "HEICO CORP":"HEI","MSCI INC":"MSCI","SLM CORP":"SLM","BRUKER CORP":"BRKR",
    "NORWEGIAN CRUISE LINE HLDGS":"NCLH","AMERICOLD REALTY TRUST INC":"COLD",
    "GDS HLDGS LTD":"GDS","HERBALIFE LTD":"HLF","DNOW INC":"DNOW",
    "VAXCYTE INC":"PCVX","TELEFLEX INCORPORATED":"TFX",
    "EAST WEST BANCORP INC":"EWBC","CROCS INC":"CROX","PDD HOLDINGS INC":"PDD",
    "LULULEMON ATHLETICA INC":"LULU","DAILY JOURNAL CORP":"DJCO",
    "LIBERTY MEDIA CORP":"LSXMA","LIBERTY BROADBAND CORP":"LBRDK",
    "STANDARD BIOTOOLS INC":"LAB","PEAKSTONE REALTY TRUST":"PKST",
    "DOLBY LABORATORIES INC":"DLB","VIASAT INC":"VSAT","VAIL RESORTS INC":"MTN",
    "ESTEE LAUDER COMPANIES INC":"EL","FLYEXCLUSIVE INC":"FLYX",
    "ARDAGH METAL PACKAGING S A":"AMBP",
    "FLUSHING FINL CORP":"FFIC","MARKEL GROUP INC":"MKL",
}
MANUAL_UP = {k.upper(): v for k, v in MANUAL.items()}

US_EXCH = {"NYQ", "NMS", "NGM", "NCM", "NAS", "PCX", "ASE", "BTS", "NYS", "OPR", "PNK", "OQX", "OQB", "OEM"}

# 회사명 대조 시 무시하는 단어 (법인격, 주식종류 표기 등)
STOP = {
    "INC", "INCORPORATED", "CORP", "CORPORATION", "CO", "COMPANY", "COMPANIES",
    "LTD", "LIMITED", "PLC", "LP", "LLC", "NV", "SA", "AG", "SE", "THE",
    "HOLDINGS", "HOLDING", "HLDGS", "HLDG", "GROUP", "GRP", "DEL", "NEW",
    "COM", "CL", "CLASS", "ADR", "ADS", "SPONSORED", "SPON", "SHS", "ORD",
    "CAP", "STK", "AND", "OF", "TR", "TRUST", "FORMERLY", "SAB", "DE", "CV",
    "ASA", "OYJ", "SPA", "BHD", "SWITZ", "PAR", "VALUE", "NPV",
}


# ━━━━━━━━━━━━━━━━━━━━━━ 유틸 ━━━━━━━━━━━━━━━━━━━━━━

def load_json(p):
    if not p.exists():
        return None
    try:
        with open(p, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def save_json(p, d):
    with open(p, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=1)


def valid(t):
    """미국 시장에서 조회 가능한 티커 형식인지"""
    if not t or not isinstance(t, str) or t[0].isdigit():
        return False
    u = t.upper()
    for s in [".SW", ".MI", ".MX", ".L", ".PA", ".DE", ".HK", ".TO", ".AX", ".SI", ".KS", ".T", ".SS", ".SZ", ".V", ".F"]:
        if u.endswith(s):
            return False
    if "-P" in u and not u.startswith("BRK"):
        return False
    return True


def clean_name(n):
    n = n.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
    n = re.sub(r"<!\[CDATA\[|]]>", "", n).strip()
    return n


def norm_cusip(c):
    c = re.sub(r"[^0-9A-Za-z]", "", str(c or "")).upper()
    return c if len(c) == 9 and c != "000000000" else ""


def is_debt_cusip(c):
    """CUSIP 7~8번째 자리(발행번호)에 영문자 = 채권. 주식은 숫자(10, 20, 30 ...)"""
    return bool(c) and (c[6].isalpha() or c[7].isalpha())


# ━━━━━━━━━━━━━━━━━━━━━━ 회사명 대조 ━━━━━━━━━━━━━━━━━━━━━━

def tokens(s):
    s = re.sub(r"\([^)]*\)", " ", s.upper())
    s = re.sub(r"[^A-Z0-9]+", " ", s)
    return [w for w in s.split() if len(w) >= 2 and w not in STOP]


def _subseq(short, long_):
    it = iter(long_)
    return all(ch in it for ch in short)


def tok_eq(a, b):
    """같은 단어이거나 약어 관계 (FINL=FINANCIAL, HLDGS=HOLDINGS, CTRY=COUNTRY 등)"""
    if a == b:
        return True
    s, l = (a, b) if len(a) <= len(b) else (b, a)
    if len(s) < 3:
        return False
    if l.startswith(s):
        return True
    return s[0] == l[0] and _subseq(s, l)


def names_match(a, b):
    """13F 종목명(a)과 데이터 제공처 회사명(b)이 같은 회사인지"""
    if not a or not b:
        return False
    ta, tb = tokens(a)[:4], tokens(b)[:6]
    if not ta or not tb:
        ca = re.sub(r"[^A-Z0-9]", "", a.upper())
        cb = re.sub(r"[^A-Z0-9]", "", b.upper())
        return len(ca) >= 2 and ca[:5] == cb[:5]
    # 첫 단어는 상대 회사명 앞쪽 3단어 안에 반드시 있어야 함
    if not any(tok_eq(ta[0], y) for y in tb[:3]):
        return False
    hit = sum(1 for x in ta if any(tok_eq(x, y) for y in tb))
    need = min(2, len(ta), len(tb))
    return hit >= need and hit / len(ta) >= 0.5


# ━━━━━━━━━━━━━━━━━━━━━━ HTTP ━━━━━━━━━━━━━━━━━━━━━━

def get_json(url, timeout=15, tries=3):
    for i in range(tries):
        try:
            with urlopen(Request(url, headers={"User-Agent": YF_UA}), timeout=timeout) as r:
                return json.loads(r.read())
        except HTTPError as e:
            if e.code == 429:
                time.sleep(10 * (i + 1))
                continue
            if e.code >= 500:
                time.sleep(2)
                continue
            return None
        except Exception:
            time.sleep(1)
    return None


# ━━━━━━━━━━━━━━━━━━━━━━ 가격 조회 ━━━━━━━━━━━━━━━━━━━━━━

def yf_price(t):
    """반환: (가격dict, 회사명) 또는 None"""
    d = get_json(f"https://query1.finance.yahoo.com/v8/finance/chart/{quote(t)}?range=1y&interval=1d&includePrePost=false")
    try:
        res = d["chart"]["result"][0]
    except Exception:
        return None
    meta = res.get("meta", {}) or {}
    cur = meta.get("regularMarketPrice")
    if not cur:
        return None
    mt = meta.get("regularMarketTime")
    if mt and time.time() - mt > STALE_DAYS * 86400:
        return None  # 장기간 거래 없음 = 상장폐지/거래정지 추정
    try:
        cl = [x for x in res["indicators"]["quote"][0]["close"] if x]
    except Exception:
        cl = []
    hi = meta.get("fiftyTwoWeekHigh") or (max(cl) if cl else cur)
    lo = meta.get("fiftyTwoWeekLow") or (min(cl) if cl else cur)
    hi, lo = max(hi, cur), min(lo, cur)
    name = meta.get("longName") or meta.get("shortName") or ""
    return ({"current_price": round(cur, 2), "week52_low": round(lo, 2), "week52_high": round(hi, 2)}, name)


_fc = 0
_ft = time.time()


def _fr():
    global _fc, _ft
    _fc += 1
    if _fc >= 55:
        e = time.time() - _ft
        if e < 62:
            time.sleep(62 - e)
        _fc = 0
        _ft = time.time()


def fh_get(path):
    _fr()
    return get_json(f"{FH}/{path}&token={FH_KEY}", timeout=10, tries=2)


def fh_price(t):
    if not FH_KEY:
        return None
    q = fh_get(f"quote?symbol={quote(t)}")
    cur = (q or {}).get("c", 0)
    if not cur:
        return None
    ts = (q or {}).get("t")
    if ts and time.time() - ts > STALE_DAYS * 86400:
        return None
    prof = fh_get(f"stock/profile2?symbol={quote(t)}") or {}
    m = (fh_get(f"stock/metric?symbol={quote(t)}&metric=all") or {}).get("metric", {}) or {}
    hi = max(m.get("52WeekHigh") or cur, cur)
    lo = min(m.get("52WeekLow") or cur, cur)
    return ({"current_price": round(cur, 2), "week52_low": round(lo, 2), "week52_high": round(hi, 2)}, prof.get("name", ""))


def get_price(t):
    r = yf_price(t)
    if not r and FH_KEY:
        r = fh_price(t)
    return r


# ━━━━━━━━━━━━━━━━━━━━━━ 티커 검색 ━━━━━━━━━━━━━━━━━━━━━━

def query_variants(name):
    n = re.sub(r"\s*\([^)]*\)", "", name).strip()
    n = re.sub(r"\s+FORMERLY$", "", n, flags=re.I).strip()
    vs = [n]
    c = re.sub(r"\s+(INC|CORP|CO|LTD|PLC|LP|LLC|NV|SA|AG|SE|SWITZ|CORPORATION|HLDGS|HOLDINGS|GROUP|DEL|NEW)\.?$", "", n, flags=re.I)
    c = re.sub(r"\s+(INC|CORP|CO|LTD|DEL)\.?$", "", c, flags=re.I).strip()
    if c and c != n:
        vs.append(c)
    if "&" in c:
        vs.append(c.replace("&", "AND"))
    w = c.split()
    if len(w) >= 3:
        vs.append(" ".join(w[:2]))
    out = []
    for v in vs:
        if v and v not in out:
            out.append(v)
    return out


def yf_search(name):
    for q in query_variants(name):
        d = get_json(f"https://query1.finance.yahoo.com/v1/finance/search?q={quote_plus(q)}&quotesCount=8&newsCount=0", timeout=10, tries=2)
        quotes = (d or {}).get("quotes", [])
        ranked = sorted(quotes, key=lambda x: 0 if x.get("exchange", "") in US_EXCH else 1)
        for qt in ranked:
            s = qt.get("symbol", "")
            if qt.get("quoteType") not in ("EQUITY", "ETF") or not valid(s) or "." in s:
                continue
            qn = qt.get("longname") or qt.get("shortname") or ""
            if names_match(name, qn):
                return s
        time.sleep(0.25)
    return None


def fh_search(name):
    if not FH_KEY:
        return None
    for q in query_variants(name)[:2]:
        d = fh_get(f"search?q={quote_plus(q.replace('&', 'AND'))}")
        for i in (d or {}).get("result", []):
            s = i.get("symbol", "")
            if i.get("type", "") not in ("Common Stock", "ADR", "EQS", "ETP", "REIT", ""):
                continue
            if valid(s) and "." not in s and names_match(name, i.get("description", "")):
                return s
    return None


def openfigi(cusips):
    """CUSIP 리스트 -> {cusip: ticker}. 주식 외(채권, 옵션, 워런트, 우선주)는 버림"""
    if not cusips:
        return {}
    headers = {"Content-Type": "application/json"}
    if FIGI_KEY:
        headers["X-OPENFIGI-APIKEY"] = FIGI_KEY
    size, gap, wait429 = (100, 0.3, 7) if FIGI_KEY else (10, 2.6, 61)
    out = {}
    st = {"ok": 0, "nomatch": 0, "nonequity": 0, "err": 0}
    first_err = None
    for i in range(0, len(cusips), size):
        batch = cusips[i:i + size]
        body = json.dumps([{"idType": "ID_CUSIP", "idValue": c, "exchCode": "US"} for c in batch]).encode()
        data = None
        for attempt in range(4):
            try:
                req = Request(FIGI_URL, data=body, headers=headers, method="POST")
                with urlopen(req, timeout=30) as r:
                    data = json.loads(r.read())
                break
            except HTTPError as e:
                if e.code == 429:
                    time.sleep(wait429)
                    continue
                first_err = first_err or f"HTTP {e.code}: {e.read()[:200]!r}"
                break
            except Exception as e:
                first_err = first_err or repr(e)
                time.sleep(3)
        if not isinstance(data, list):
            st["err"] += len(batch)
        else:
            for c, item in zip(batch, data):
                rows = (item or {}).get("data") or []
                if not rows:
                    st["nomatch"] += 1
                    continue
                pick = None
                for row in rows:
                    t = (row.get("ticker") or "").strip().replace("/", "-").replace(" ", "-")
                    stype = f"{row.get('securityType', '')} {row.get('securityType2', '')}".upper()
                    if row.get("marketSector") != "Equity":
                        continue
                    if any(x in stype for x in ("OPTION", "WARRANT", "PREFERENCE", "PREFERRED", "RIGHT")):
                        continue
                    if valid(t):
                        pick = t
                        break
                if pick:
                    out[c] = pick
                    st["ok"] += 1
                else:
                    st["nonequity"] += 1
        time.sleep(gap)
    log.info(f"  OpenFIGI: 성공 {st['ok']}, 미발견 {st['nomatch']}, 주식아님 {st['nonequity']}, 오류 {st['err']}")
    if first_err:
        log.info(f"  OpenFIGI 첫 오류: {first_err}")
    return out


# ━━━━━━━━━━━━━━━━━━━━━━ 메인 ━━━━━━━━━━━━━━━━━━━━━━

def collect():
    """us_vips.json 현재 보유 종목: {대문자이름: {"name": 원래이름, "cusips": set}}"""
    vips = load_json(VIPS_PATH)
    if not vips:
        log.error("us_vips.json 로드 실패")
        return {}
    portfolios = vips.get("portfolios", vips)
    out = {}
    for guru, data in portfolios.items():
        if not isinstance(data, dict):
            continue
        for h in data.get("holdings", []):
            n = clean_name(str(h.get("name", "")).strip())
            if not n:
                continue
            k = n.upper()
            e = out.setdefault(k, {"name": n, "cusips": set()})
            c = norm_cusip(h.get("cusip") or h.get("CUSIP"))
            if c:
                e["cusips"].add(c)
    return out


def main():
    stocks = collect()
    log.info(f"현재 포트폴리오 고유 종목: {len(stocks)}개")
    if not stocks:
        return
    n_cusip = sum(1 for v in stocks.values() if v["cusips"])
    log.info(f"CUSIP 보유 종목: {n_cusip}개 (없으면 이름검색 + 회사명 대조로 처리)")

    raw = load_json(CACHE_PATH) or {}
    cache = {k: v for k, v in raw.items() if isinstance(v, str)}
    today = datetime.utcnow().date()

    prices, pmemo = {}, {}
    rejected, no_price, manual_bad, bonds = [], {}, [], []
    dead = set()  # 신뢰 티커인데 현재가 없음 = 상장폐지 추정

    def try_ticker(k, t, trusted, src):
        if not t or not valid(t):
            return False
        if t not in pmemo:
            pmemo[t] = get_price(t)
            time.sleep(0.15)
        r = pmemo[t]
        if not r:
            no_price[k] = t
            if trusted:
                dead.add(k)
            return False
        pd, pname = r
        if not trusted and pname and not names_match(stocks[k]["name"], pname):
            rejected.append((stocks[k]["name"], t, pname, src))
            return False
        prices[k] = {"ticker": t, "name": stocks[k]["name"], **pd}
        no_price.pop(k, None)
        return True

    # ━━ 1단계: MANUAL, CUSIP 캐시, 이름 캐시 ━━
    pending = []
    for idx, (k, v) in enumerate(stocks.items()):
        eq = [c for c in v["cusips"] if not is_debt_cusip(c)]
        if v["cusips"] and not eq:
            bonds.append(v["name"])
            continue
        if k in ("NONE", "N/A", ""):
            continue
        v["eq"] = eq
        nc = re.sub(r"\s*\([^)]*\)", "", k).strip()
        nc2 = re.sub(r"\s+FORMERLY$", "", nc).strip()
        mt = MANUAL_UP.get(k) or MANUAL_UP.get(nc) or MANUAL_UP.get(nc2)
        if mt:
            if try_ticker(k, mt, True, "MANUAL"):
                continue
            manual_bad.append((v["name"], mt))
        done = False
        for c in eq:
            ct = cache.get(f"cusip:{c}")
            if ct and try_ticker(k, ct, True, "CUSIP캐시"):
                done = True
                break
        if not done and cache.get(k):
            if try_ticker(k, cache[k], False, "이름캐시"):
                done = True
            elif any(r[0] == v["name"] for r in rejected):
                cache.pop(k, None)  # 잘못된 캐시 자동 삭제 (NYT -> ASML 등)
        if not done:
            pending.append(k)
        if (idx + 1) % 500 == 0:
            log.info(f"  1단계 {idx+1}/{len(stocks)} (성공 {len(prices)})")
    log.info(f"1단계 완료: 성공 {len(prices)}, 채권 제외 {len(bonds)}, 남음 {len(pending)}")

    # 최근에 못 찾은 종목은 재검색 생략
    def recently_missed(k):
        d = cache.get(f"miss:{k}")
        try:
            return d and (today - datetime.strptime(d, "%Y-%m-%d").date()).days < MISS_RETRY_DAYS
        except Exception:
            return False

    skipped = [k for k in pending if recently_missed(k)]
    pending = [k for k in pending if not recently_missed(k)]
    if skipped:
        log.info(f"최근 {MISS_RETRY_DAYS}일 내 검색 실패 종목 {len(skipped)}개는 이번 실행에서 생략")

    # ━━ 2단계: OpenFIGI (CUSIP -> 티커) ━━
    tried_cusip_cache = {c for k in pending for c in stocks[k]["eq"] if cache.get(f"cusip:{c}")}
    q = sorted({c for k in pending for c in stocks[k]["eq"]} - tried_cusip_cache)
    if q:
        log.info(f"2단계 OpenFIGI 조회: CUSIP {len(q)}개")
        fmap = openfigi(q)
        for c, t in fmap.items():
            cache[f"cusip:{c}"] = t
        still = []
        for k in pending:
            ok = False
            for c in stocks[k]["eq"]:
                if c in fmap and try_ticker(k, fmap[c], True, "OpenFIGI"):
                    cache[k] = fmap[c]
                    ok = True
                    break
            if not ok:
                still.append(k)
        pending = still
        log.info(f"2단계 완료: 누적 성공 {len(prices)}, 남음 {len(pending)}")

    # ━━ 3단계: Yahoo / Finnhub 이름검색 (회사명 대조 필수) ━━
    if pending:
        log.info(f"3단계 이름검색: {len(pending)}개")
        still = []
        for k in pending:
            if k in dead:
                # CUSIP으로 티커는 확정됐는데 가격만 없음 = 상장폐지 추정, 이름검색 불필요
                still.append(k)
                continue
            name = stocks[k]["name"]
            t = yf_search(name)
            if t and try_ticker(k, t, False, "Yahoo검색"):
                cache[k] = t
                continue
            t = fh_search(name)
            if t and try_ticker(k, t, False, "Finnhub검색"):
                cache[k] = t
                continue
            still.append(k)
            time.sleep(0.15)
        pending = still

    for k in pending:
        cache[f"miss:{k}"] = today.isoformat()
    for k in prices:
        cache.pop(f"miss:{k}", None)

    # ━━ 결과 로그 ━━
    log.info(f"━━━ 최종: 성공 {len(prices)} / 전체 {len(stocks)} ━━━")
    delisted = [(stocks[k]["name"], no_price[k]) for k in pending if k in no_price]
    unknown = [stocks[k]["name"] for k in pending if k not in no_price]
    if delisted:
        log.info(f"티커는 찾았으나 현재가 없음 (상장폐지, 인수합병, 거래정지 추정) {len(delisted)}개:")
        for n, t in delisted[:40]:
            log.info(f"  - {n} ({t})")
    if unknown:
        log.info(f"티커 못 찾음 (외국 상장, 비상장, 기타) {len(unknown)}개:")
        for n in unknown[:40]:
            log.info(f"  - {n}")
    if rejected:
        log.info(f"회사명 불일치로 거절한 매핑 {len(rejected)}건 (오매핑 차단):")
        for n, t, pn, src in rejected[:40]:
            log.info(f"  - {n} -> {t} ({pn}) [{src}]")
    if manual_bad:
        log.info(f"MANUAL 티커 가격조회 실패 {len(manual_bad)}건 (자동으로 다른 방법 시도함):")
        for n, t in manual_bad[:20]:
            log.info(f"  - {n} -> {t}")
    if bonds:
        log.info(f"채권 CUSIP이라 제외 {len(bonds)}개 (예: {', '.join(bonds[:5])})")

    save_json(PRICES_PATH, {"updated_at": datetime.utcnow().isoformat() + "Z", "count": len(prices), "prices": prices})
    save_json(CACHE_PATH, cache)
    log.info(f"저장 완료: {PRICES_PATH}")


if __name__ == "__main__":
    main()
