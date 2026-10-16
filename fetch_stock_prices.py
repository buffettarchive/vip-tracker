#!/usr/bin/env python3
"""
fetch_stock_prices.py v14 - 구루 현재 포트폴리오 시세 업데이트 (완전자동 매핑)

[티커 결정 순서] 앞 단계에서 가격까지 확보되면 끝, 실패하면 다음 단계로 넘어감
  1. MANUAL            : 사람이 확인한 매핑
  2. CUSIP 캐시/OpenFIGI : us_vips.json에 CUSIP이 있을 때만 (현재는 없음)
  3. 종목명 끝 (티커)    : "WW GRAINGER INC (GWW)" 처럼 이름에 적힌 티커
  4. 미국 상장종목 목록  : Nasdaq Trader 공식 심볼 목록(약 1만 2천 종목)과 이름 대조 ★핵심
  5. 이름 캐시          : 과거 검색 결과 (회사명 대조 통과해야 채택)
  6. Yahoo 이름검색     : 회사명 대조 통과해야 채택

[회사명 대조] 13F 약어(FINL, HLDGS, RLTY, PPTYS ...)를 풀어서 비교하고,
  흔한 단어(ETF, ISHARES 등)보다 드문 단어(회사 고유명)에 가중치를 둠.
  NEW YORK TIMES -> ASML, ISHARES ... -> ENHE 같은 오매핑은 자동 차단 및 캐시 삭제.

[출력] docs/stock_prices.json 형식은 기존과 동일 (키 = 대문자 종목명)
[환경변수] FINNHUB_API_KEY (선택), OPENFIGI_API_KEY (선택)
"""
import json, time, logging, re, os, math, csv, io
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
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
MISS_PREFIX = "miss2:"   # 이전 버전의 검색실패 기록은 무시하고 새로 시도
WORKERS = 8              # Yahoo 가격 동시조회 수 (429 오류가 많으면 줄일 것)
SEARCH_WORKERS = 4       # Yahoo 이름검색 동시 수
SEARCH_BUDGET_SEC = 600  # 이름검색에 쓰는 최대 시간 (남은 건 다음 실행 때 이어서)
DEAD = "DEAD"            # Yahoo가 "없는 종목"이라고 확답한 경우
STALE_DAYS = 14

# 미국 상장종목 공식 목록 (앞이 원본, 뒤가 GitHub 미러)
DIRECTORY_SOURCES = [
    (["https://www.nasdaqtrader.com/dynamic/SymDir/nasdaqlisted.txt",
      "https://raw.githubusercontent.com/datasets/nasdaq-listings/master/data/nasdaq-listed-symbols.csv"], "Symbol"),
    (["https://www.nasdaqtrader.com/dynamic/SymDir/otherlisted.txt",
      "https://raw.githubusercontent.com/datasets/nyse-other-listings/main/data/other-listed.csv"], "ACT Symbol"),
]

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

# ━━━━━━━━━━━━━━━━━━━━━━ 회사명 정규화와 대조 ━━━━━━━━━━━━━━━━━━━━━━

# 회사명 대조 시 무시하는 단어 (법인격, 주식종류, 등록지 표기 등)
STOP = {
    "INC", "INCORPORATED", "CORP", "CORPORATION", "CO", "COMPANY", "COMPANIES", "COS",
    "LTD", "LIMITED", "PLC", "LP", "LLC", "NV", "SA", "AG", "SE", "THE", "PLUS",
    "HOLDINGS", "HOLDING", "HLDGS", "HLDG", "GROUP", "GRP",
    "COM", "CL", "CLASS", "ADR", "ADS", "SPONSORED", "SPON", "SHS", "SH", "ORD",
    "CAP", "STK", "AND", "OF", "TR", "TRUST", "FORMERLY", "SAB", "DE", "CV",
    "ASA", "OYJ", "SPA", "BHD", "SWITZ", "PAR", "NPV",
    "COMMON", "STOCK", "SHARES", "ORDINARY", "DEPOSITARY", "REGISTRY", "REG", "NY",
    "EACH", "REPRESENTING", "ONE", "TWO", "THREE", "FOUR", "FIVE", "TEN",
    "CAYMAN", "ISL", "ISLANDS", "BERMUDA", "JERSEY", "DBA", "D", "B", "A",
    "BENEFICIAL", "INTEREST", "INTERESTS", "UNIT", "REPSTG", "MTN", "BE",
}
SPONSOR_SKIP = {"STATE", "STREET"}   # "State Street SPDR ..." 처럼 앞에 붙는 운용사명

# 13F에서 자주 쓰는 약어 -> 정식 단어 (부분수열로 안 잡히는 것만)
ABBR = {
    "BK": "BANK", "BKS": "BANKS", "ED": "EDUCATION", "EDL": "EDUCATIONAL",
    "PPTYS": "PROPERTIES", "PPTY": "PROPERTY", "CMNTYS": "COMMUNITIES", "CMNTY": "COMMUNITY",
    "TECHNOLOGIES": "TECH", "TECHNOLOGY": "TECH", "TECHNOLOGI": "TECH", "TECHS": "TECH",
    "COMMUNICATIONS": "COMM", "COMMUNICATION": "COMM", "COMMUNICATNS": "COMM", "COMMS": "COMM",
    "PHARMACEUTICALS": "PHARM", "PHARMACEUTICAL": "PHARM", "PHARMA": "PHARM", "PHARMS": "PHARM",
    "LABORATORIES": "LAB", "LABS": "LAB", "LABORATORY": "LAB",
    "MUNICIPAL": "MUNI", "MUNIPL": "MUNI", "MUN": "MUNI",
    "ISHR": "ISHARES", "ISHRS": "ISHARES", "ISH": "ISHARES",
    "SS": "STATE", "STR": "STREET", "CR": "CORE", "BD": "BOND", "BDS": "BONDS",
    "AMER": "AMERICAN", "AMERN": "AMERICAN", "AMERICA": "AMERICA",
    "INTL": "INTERNATIONAL", "INTERNATL": "INTERNATIONAL", "INTRNTNL": "INTERNATIONAL",
    "BANCORPORATION": "BANCORP", "ENTMT": "ENTERTAINMENT", "SVCS": "SERVICES",
    "NATL": "NATIONAL", "FINL": "FINANCIAL", "MGMT": "MANAGEMENT", "MFG": "MANUFACTURING",
    "HLTH": "HEALTH", "HLTHCARE": "HEALTHCARE", "INS": "INSURANCE", "SYS": "SYSTEMS",
    "RLTY": "REALTY", "INVTS": "INVESTMENTS", "INVT": "INVESTMENT", "PRODS": "PRODUCTS",
    "RES": "RESOURCES", "MATLS": "MATERIALS", "ELEC": "ELECTRIC", "ENERGY": "ENERGY",
    "SMALLCAP": "SMALL", "MIDCAP": "MID", "LARGECAP": "LARGE", "SVC": "SERVICE",
    "MFRS": "MANUFACTURERS", "PETE": "PETROLEUM", "PETRO": "PETROLEUM", "CTR": "CENTER", "CTRS": "CENTERS", "GRWTH": "GROWTH",
}
GLUED_SUFFIX = {"COM", "INC", "CORP", "CO", "LTD", "PLC", "GROUP", "HLDGS", "HOLDINGS", "NV", "SA", "AG"}
STOP_TAIL = {"NEW", "DEL"}   # 이름 맨 앞이 아닐 때만 무시 (NEW YORK TIMES는 살림)
ETF_HINT = re.compile(r"\b(ETF|ETFS|ETN|FUND|FD|FDS|TR|TRUST|INDEX|SHARES|ISHARES|ISHR|ISHRS|SPDR|PORTFOLIO|VANGUARD|INVESCO|PROSHARES|SCHWAB)\b")

IDF = {}
IDF_MAX = 6.0


def tokens(s):
    s = s.upper().replace("'", "").replace("\u2019", "")   # MOODY'S -> MOODYS
    s = re.sub(r"\s*\([A-Z0-9.\-]{1,8}\)\s*$", "", s)          # 끝의 (티커) 제거
    s = re.sub(r"AMERICAN DEPOSITARY (SHARES|RECEIPTS?)", " ", s)
    s = re.sub(r"[()&+]", " ", s)
    s = re.sub(r"[^A-Z0-9]+", " ", s)
    raw, out, run = s.split(), [], ""
    for w in raw:                                               # U S -> US, D R -> DR, 1 3 -> 13
        if len(w) == 1:
            run += w
            continue
        if len(run) >= 2:
            out.append(run)
        run = ""
        out.append(w)
    if len(run) >= 2:
        out.append(run)
    res = []
    for w in out:
        w = ABBR.get(w, w)
        if len(w) >= 2 and w not in STOP and not (res and w in STOP_TAIL):
            res.append(w)
    return res


def _subseq(short, long_):
    it = iter(long_)
    return all(ch in it for ch in short)


def tok_eq(a, b, last=False):
    """a(13F 쪽 단어)와 b(정식 회사명 단어)가 같은 단어인지. 약어는 a가 줄임말일 때만 인정"""
    if a == b:
        return True
    if last and len(a) >= 2 and len(b) > len(a) and b.startswith(a):
        return True                                          # 13F 이름 끝 잘림 (TREASURY BO = BOND)
    s, l = (a, b) if len(a) <= len(b) else (b, a)
    if len(s) < 3 or s.isdigit() or l.isdigit():
        return False
    if l.startswith(s):
        # 법인격이 붙어버린 경우만 인정 (13F AMAZONCOM = AMAZON). EMERALD != EMERA, SQUARE != SQUARED
        return a == l and len(b) >= 4 and a[len(b):] in GLUED_SUFFIX
    # 약어: 13F 쪽이 짧고, 첫 글자와 끝 글자가 같고 부분수열 (FINL=FINANCIAL, CTRY=COUNTRY)
    return (len(a) < len(b) and len(a) >= 4 and len(a) / len(b) >= 0.4
            and a[0] == b[0] and a[-1] == b[-1] and _subseq(a, b))


def _w(t):
    return IDF.get(t, IDF_MAX)


def name_score(ta, tb, truncated=False):
    """0~1. 13F 이름 토큰(ta)과 상대 회사명 토큰(tb)의 가중 F1. 첫 단어 일치 필수"""
    if not ta or not tb:
        return 0.0
    # 붙여쓰기 차이 보정: JPMORGAN = JP MORGAN, SIRIUSXM = SIRIUS XM
    if len(tb) > 1 and ta[0] == tb[0] + tb[1]:
        tb = [ta[0]] + tb[2:]
    elif len(ta) > 1 and tb[0] == ta[0] + ta[1]:
        ta = [tb[0]] + ta[2:]
    if not any(tok_eq(ta[0], y) for y in tb[:3]):
        return 0.0
    # 상대 회사명의 첫 단어도 13F 이름 안에 있어야 함 (GENERAL ELECTRIC != PORTLAND GENERAL ELECTRIC)
    if tb[0] not in SPONSOR_SKIP and not any(tok_eq(x, tb[0]) for x in ta):
        return 0.0
    used, num_a, den_a = set(), 0.0, 0.0
    n = len(ta)
    for i, x in enumerate(ta):
        hit = None
        for j, y in enumerate(tb):
            if j not in used and tok_eq(x, y, last=(truncated and i == n - 1)):
                hit = j
                break
        if hit is None:
            den_a += _w(x)
        else:
            used.add(hit)
            w = _w(tb[hit])
            num_a += w if x == tb[hit] else 0.85 * w           # 정확히 같은 단어 우대
            den_a += w
    den_b = sum(_w(y) for y in tb)
    num_b = sum(_w(tb[j]) for j in used)
    p = num_a / den_a if den_a else 0
    r = num_b / den_b if den_b else 0
    return 2 * p * r / (p + r) if p + r else 0.0


def names_match(a, b, th=0.6):
    if not a or not b:
        return False
    ta, tb = tokens(a), tokens(b)
    if not ta or not tb:
        ca = re.sub(r"[^A-Z0-9]", "", a.upper())
        cb = re.sub(r"[^A-Z0-9]", "", b.upper())
        return len(ca) >= 2 and ca[:5] == cb[:5]
    return name_score(ta[:6], tb[:8], len(a) >= 24) >= th


def share_class(s):
    s = s.upper()
    m = re.search(r"\bCL(?:ASS)?[\s\-]*([A-C])\b", s) or re.search(r"[\-\s]([A-C])$", s.strip())
    return m.group(1) if m else ""


BAD_SEC = re.compile(r"\b(WARRANTS?|RIGHTS?|UNITS?|PREFERRED|PREF|NOTES?|DEBENTURES?|DUE \d{4}|SUBORDINATED)\b|%")


class Directory:
    """미국 상장 전 종목 목록 (Nasdaq Trader 심볼 디렉터리). 이름 -> 티커 로컬 매칭"""

    CUT = re.compile(r"\s+(American Depositary|ADS\b|Common Stock|Common Shares|Ordinary Shares?|Class [A-Z]\b|"
                     r"Series [A-Z]\b|Capital Stock|Depositary|Limited Voting|Subordinate Voting|"
                     r"New York Registry|Registered Shares|Shares of Beneficial|Common Units)", re.I)

    def __init__(self):
        self.entries = []   # (sym, tokens, cls, name, is_etf)
        self.by_letter = {}
        self.by_sym = {}

    def add_rows(self, rows, sym_col):
        n = 0
        for row in rows:
            sym = (row.get(sym_col) or "").strip()
            name = (row.get("Security Name") or "").strip()
            if not sym or not name or sym.startswith("File Creation"):
                continue
            if (row.get("Test Issue") or "N").strip().upper() == "Y":
                continue
            if "$" in sym or BAD_SEC.search(name.upper()):
                continue
            ysym = sym.replace(".", "-").replace("/", "-")
            base = self.CUT.split(name.split(" - ")[0])[0]
            tk = tokens(base)
            if not tk or ysym in self.by_sym:
                continue
            etf = (row.get("ETF") or "N").strip().upper() == "Y"
            self.by_sym[ysym] = name
            self.entries.append((ysym, tk, share_class(name), name, etf))
            n += 1
        return n

    def finalize(self):
        global IDF, IDF_MAX
        df = {}
        for _, tk, _, _, _ in self.entries:
            for t in set(tk):
                df[t] = df.get(t, 0) + 1
        N = max(len(self.entries), 1)
        IDF = {t: math.log(1 + N / c) for t, c in df.items()}
        IDF_MAX = math.log(1 + N)
        for i, (_, tk, _, _, _) in enumerate(self.entries):
            for L in {t[0] for t in tk[:3]}:
                self.by_letter.setdefault(L, []).append(i)

    def match(self, name, th=0.72, margin=0.05):
        ta = tokens(name)[:6]
        if not ta:
            return None
        cls = share_class(name)
        etf_ok = bool(ETF_HINT.search(name.upper()))
        trunc = len(name) >= 24   # 13F 종목명은 보통 28~30자에서 잘림
        scored = []
        for i in self.by_letter.get(ta[0][0], []):
            sym, tb, ecls, ename, etf = self.entries[i]
            if etf and not etf_ok:
                continue  # 일반 기업명이 ETF로 매칭되는 것 방지
            s = name_score(ta, tb[:8], trunc)
            if s <= 0:
                continue
            if cls:
                if ecls:
                    s += 0.03 if cls == ecls else -0.03
                if sym.endswith("-" + cls):
                    s += 0.02
            scored.append((s, -len(sym), sym, ename))
        if not scored:
            return None
        scored.sort(reverse=True)
        best = scored[0]
        if best[0] < th:
            return None
        if len(scored) > 1:
            second = scored[1]
            base = lambda n: tokens(self.CUT.split(n.split(" - ")[0])[0])
            same_issuer = base(second[3]) == base(best[3])
            if best[0] - second[0] < margin and not same_issuer:
                return None
        return best[2]


def parse_table(text):
    first = text.splitlines()[0] if text else ""
    delim = "|" if first.count("|") > first.count(",") else ","
    return list(csv.DictReader(io.StringIO(text), delimiter=delim))


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


# ━━━━━━━━━━━━━━━━━━━━━━ HTTP ━━━━━━━━━━━━━━━━━━━━━━

def fetch(url, timeout=15, tries=3):
    """반환: (HTTP코드, json). 네트워크 실패면 (0, None)"""
    for i in range(tries):
        try:
            with urlopen(Request(url, headers={"User-Agent": YF_UA}), timeout=timeout) as r:
                return 200, json.loads(r.read())
        except HTTPError as e:
            if e.code == 429:
                time.sleep(10 * (i + 1))
                continue
            if e.code >= 500:
                time.sleep(2)
                continue
            return e.code, None
        except Exception:
            time.sleep(1)
    return 0, None


def get_json(url, timeout=15, tries=3):
    return fetch(url, timeout, tries)[1]


# ━━━━━━━━━━━━━━━━━━━━━━ 가격 조회 ━━━━━━━━━━━━━━━━━━━━━━

def yf_price(t):
    """반환: (가격dict, 회사명) / DEAD(없는 종목 확정) / None(일시적 실패)"""
    code, d = fetch(f"https://query1.finance.yahoo.com/v8/finance/chart/{quote(t)}?range=1y&interval=1d&includePrePost=false")
    if code in (400, 404, 422):
        return DEAD
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
        return DEAD  # 장기간 거래 없음 = 상장폐지/거래정지 추정
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
    if r == DEAD:
        return None
    if not r and FH_KEY:
        r = fh_price(t)  # Yahoo가 일시적으로 막혔을 때만 Finnhub 사용
    return r


def prefetch(tickers, pmemo):
    """Yahoo 가격을 여러 개 동시에 조회해 pmemo에 채움 (속도 핵심)"""
    todo = sorted({t for t in tickers if t and valid(t) and t not in pmemo})
    if not todo:
        return
    t0 = time.time()
    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        for t, r in zip(todo, ex.map(yf_price, todo)):
            if r == DEAD:
                pmemo[t] = None
            elif r:
                pmemo[t] = r
            # None(일시적 실패)은 비워둠 -> 나중에 한 번 더 시도 + Finnhub
    ok = sum(1 for t in todo if pmemo.get(t))
    log.info(f"  가격 동시조회 {len(todo)}개: 성공 {ok}, {time.time()-t0:.0f}초")


# ━━━━━━━━━━━━━━━━━━━━━━ 상장종목 목록 / 검색 ━━━━━━━━━━━━━━━━━━━━━━

def fetch_text(url, timeout=30):
    try:
        with urlopen(Request(url, headers={"User-Agent": YF_UA}), timeout=timeout) as r:
            return r.read().decode("utf-8", errors="ignore")
    except Exception:
        return ""


def load_directory():
    d = Directory()
    for urls, sym_col in DIRECTORY_SOURCES:
        for u in urls:
            text = fetch_text(u)
            if len(text) < 10000:
                continue
            n = d.add_rows(parse_table(text), sym_col)
            log.info(f"  상장종목 목록: {u.split('/')[-1]} {n}개")
            break
        else:
            log.info(f"  상장종목 목록 다운로드 실패: {urls[0]}")
    d.finalize()
    return d


def initials_ok(name13f, ticker, other_name):
    """GENERAL ELECTRIC = GE, WABTEC = WAB(Westinghouse Air Brake) 같은 사명변경/약칭 허용"""
    t = ticker.split("-")[0].upper()
    if len(t) < 2:
        return False
    ta = tokens(name13f)
    if "".join(w[0] for w in ta[:len(t)]) == t and len(ta) >= len(t):
        return True
    tb = tokens(other_name or "")
    compact = re.sub(r"[^A-Z]", "", name13f.upper())
    return (len(tb) >= len(t) and "".join(w[0] for w in tb[:len(t)]) == t
            and compact.startswith(t))


def paren_ticker(name):
    m = re.search(r"\(([A-Z]{1,5}(?:[.\-][A-Z])?)\)\s*$", name.upper())
    return m.group(1).replace(".", "-") if m else None


def query_variants(name):
    n = re.sub(r"\s*\([^)]*\)\s*$", "", name).strip()
    n = re.sub(r"\s+FORMERLY$", "", n, flags=re.I).strip()
    vs = [n]
    expanded = " ".join(ABBR.get(w, w) for w in re.sub(r"[^A-Za-z0-9& ]", " ", n.upper()).split())
    vs.append(expanded)
    c = re.sub(r"\s+(INC|CORP|CO|LTD|PLC|LP|LLC|NV|SA|AG|SE|SWITZ|CORPORATION|HLDGS|HOLDINGS|GROUP|DEL|NEW)\.?$", "", expanded, flags=re.I)
    c = re.sub(r"\s+(INC|CORP|CO|LTD|DEL)\.?$", "", c, flags=re.I).strip()
    vs.append(c)
    out = []
    for v in vs:
        if v and v not in out:
            out.append(v)
    return out[:3]


def yf_search(name, deadline):
    """반환: 티커 / None(못 찾음) / "SKIP"(시간초과, 다음 실행 때 재시도)"""
    for q in query_variants(name):
        if time.time() > deadline:
            return "SKIP"
        code, d = fetch(f"https://query1.finance.yahoo.com/v1/finance/search?q={quote_plus(q)}&quotesCount=8&newsCount=0",
                        timeout=10, tries=2)
        if code in (0, 429):
            return "SKIP"
        quotes = (d or {}).get("quotes", [])
        ranked = sorted(quotes, key=lambda x: 0 if x.get("exchange", "") in US_EXCH else 1)
        for qt in ranked:
            s = qt.get("symbol", "")
            if qt.get("quoteType") not in ("EQUITY", "ETF") or not valid(s) or "." in s:
                continue
            qn = qt.get("longname") or qt.get("shortname") or ""
            if names_match(name, qn):
                return s
        time.sleep(0.2)
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
    t_start = time.time()
    stocks = collect()
    log.info(f"현재 포트폴리오 고유 종목: {len(stocks)}개")
    if not stocks:
        return
    n_cusip = sum(1 for v in stocks.values() if v["cusips"])
    log.info(f"CUSIP 보유 종목: {n_cusip}개")

    raw = load_json(CACHE_PATH) or {}
    cache = {k: v for k, v in raw.items() if isinstance(v, str) and not k.startswith("miss:")}
    today = datetime.utcnow().date()

    log.info("상장종목 목록 불러오는 중")
    directory = load_directory()
    log.info(f"  총 {len(directory.entries)}개 종목")

    prices, pmemo = {}, {}
    rejected, no_price, manual_bad, bonds = [], {}, [], []
    dead = set()   # 확실한 티커인데 현재가 없음 = 상장폐지 추정
    src_count = {}

    def verified(k, t, pname):
        n = stocks[k]["name"]
        if not pname:
            return True
        if names_match(n, pname) or initials_ok(n, t, pname):
            return True
        dn = directory.by_sym.get(t)
        return bool(dn) and names_match(n, dn)

    def try_ticker(k, t, trusted, src):
        if not t or not valid(t):
            return False
        if t not in pmemo:
            pmemo[t] = get_price(t)
            time.sleep(0.1)
        r = pmemo[t]
        if not r:
            no_price[k] = t
            if trusted:
                dead.add(k)
            return False
        pd, pname = r
        if not trusted and not verified(k, t, pname):
            rejected.append((stocks[k]["name"], t, pname, src))
            return False
        prices[k] = {"ticker": t, "name": stocks[k]["name"], **pd}
        no_price.pop(k, None)
        dead.discard(k)
        src_count[src] = src_count.get(src, 0) + 1
        return True

    # ━━ 1단계: 후보 티커 모으기 (MANUAL, CUSIP 캐시, 이름 속 티커, 상장종목 목록, 이름 캐시) ━━
    t0 = time.time()
    plans = {}
    for k, v in stocks.items():
        eq = [c for c in v["cusips"] if not is_debt_cusip(c)]
        v["eq"] = eq
        if v["cusips"] and not eq:
            bonds.append(v["name"])
            continue
        if k in ("NONE", "N/A", ""):
            continue
        nc = re.sub(r"\s*\([^)]*\)", "", k).strip()
        nc2 = re.sub(r"\s+FORMERLY$", "", nc).strip()
        plan = []
        mt = MANUAL_UP.get(k) or MANUAL_UP.get(nc) or MANUAL_UP.get(nc2)
        if mt:
            plan.append((mt, True, "MANUAL"))
        for c in eq:
            if cache.get(f"cusip:{c}"):
                plan.append((cache[f"cusip:{c}"], True, "CUSIP캐시"))
        pt = paren_ticker(v["name"])
        if pt:
            plan.append((pt, False, "이름속티커"))
        dt = directory.match(v["name"]) if directory.entries else None
        if dt:
            plan.append((dt, True, "상장종목목록"))
        if cache.get(k):
            plan.append((cache[k], False, "이름캐시"))
        plans[k] = plan
    log.info(f"1단계 후보 정리: {len(plans)}개 종목, {time.time()-t0:.0f}초")

    # ━━ 2단계: 후보 티커 가격 동시조회 후 순서대로 채택 ━━
    log.info(f"2단계 가격 동시조회 (동시 {WORKERS}개)")
    prefetch({t for p in plans.values() for t, _, _ in p}, pmemo)
    pending = []
    for k, plan in plans.items():
        won = None
        for t, trusted, src in plan:
            before = len(rejected)
            if try_ticker(k, t, trusted, src):
                won = src
                break
            if src == "MANUAL":
                manual_bad.append((stocks[k]["name"], t))
            if src == "이름캐시" and len(rejected) > before:
                cache.pop(k, None)   # 잘못된 캐시 자동 삭제 (NYT -> ASML 등)
        if won:
            if won != "MANUAL":
                cache[k] = prices[k]["ticker"]
        else:
            pending.append(k)
    log.info(f"2단계 완료: 성공 {len(prices)}, 채권 제외 {len(bonds)}, 남음 {len(pending)}")

    # ━━ 3단계: OpenFIGI (CUSIP이 있을 때만) ━━
    q = sorted({c for k in pending for c in stocks[k]["eq"] if not cache.get(f"cusip:{c}")})
    if q:
        log.info(f"3단계 OpenFIGI 조회: CUSIP {len(q)}개")
        fmap = openfigi(q)
        for c, t in fmap.items():
            cache[f"cusip:{c}"] = t
        prefetch(fmap.values(), pmemo)
        still = []
        for k in pending:
            if any(c in fmap and try_ticker(k, fmap[c], True, "OpenFIGI") for c in stocks[k]["eq"]):
                cache[k] = prices[k]["ticker"]
            else:
                still.append(k)
        pending = still

    # ━━ 4단계: Yahoo 이름검색 (회사명 대조 필수, 시간 제한) ━━
    def recently_missed(k):
        d = cache.get(MISS_PREFIX + k)
        try:
            return bool(d) and (today - datetime.strptime(d, "%Y-%m-%d").date()).days < MISS_RETRY_DAYS
        except Exception:
            return False

    targets = [k for k in pending if k not in dead and not recently_missed(k)]
    skipped_recent = sum(1 for k in pending if k not in dead and recently_missed(k))
    searched_none = set()
    if targets:
        log.info(f"4단계 Yahoo 이름검색: {len(targets)}개 (동시 {SEARCH_WORKERS}개, 최대 {SEARCH_BUDGET_SEC}초)"
                 + (f", 최근 실패 {skipped_recent}개 생략" if skipped_recent else ""))
        t0 = time.time()
        deadline = t0 + SEARCH_BUDGET_SEC
        with ThreadPoolExecutor(max_workers=SEARCH_WORKERS) as ex:
            found = dict(zip(targets, ex.map(lambda k: yf_search(stocks[k]["name"], deadline), targets)))
        prefetch([t for t in found.values() if t and t != "SKIP"], pmemo)
        n_skip = 0
        for k in targets:
            t = found.get(k)
            if t == "SKIP":
                n_skip += 1
                continue
            if t and try_ticker(k, t, False, "Yahoo검색"):
                cache[k] = t
                continue
            searched_none.add(k)
        log.info(f"4단계 완료: 누적 성공 {len(prices)}, {time.time()-t0:.0f}초"
                 + (f", 시간초과로 다음 실행에 미룸 {n_skip}개" if n_skip else ""))

    for k in searched_none:
        if k not in prices:
            cache[MISS_PREFIX + k] = today.isoformat()
    for k in prices:
        cache.pop(MISS_PREFIX + k, None)

    # ━━ 결과 로그 ━━
    missing = [k for k in plans if k not in prices]
    log.info(f"━━━ 최종: 성공 {len(prices)} / 전체 {len(stocks)} ({time.time()-t_start:.0f}초) ━━━")
    log.info("성공 경로별: " + ", ".join(f"{s} {n}" for s, n in sorted(src_count.items(), key=lambda x: -x[1])))
    delisted = [(stocks[k]["name"], no_price[k]) for k in missing if k in dead]
    unknown = [stocks[k]["name"] for k in missing if k not in dead]
    if delisted:
        log.info(f"티커는 확실한데 현재가 없음 (상장폐지, 인수합병, 거래정지 추정) {len(delisted)}개:")
        for n, t in delisted[:50]:
            log.info(f"  - {n} ({t})")
    if unknown:
        log.info(f"티커 못 찾음 (외국 상장, 상장폐지, 사명변경 등) {len(unknown)}개:")
        for n in unknown[:80]:
            log.info(f"  - {n}")
    if rejected:
        log.info(f"회사명 불일치로 거절한 매핑 {len(rejected)}건 (오매핑 차단):")
        for n, t, pn, src in rejected[:50]:
            log.info(f"  - {n} -> {t} ({pn}) [{src}]")
    if manual_bad:
        log.info(f"MANUAL 티커 가격조회 실패 {len(manual_bad)}건 (다른 방법으로 자동 대체 시도함):")
        for n, t in manual_bad[:20]:
            log.info(f"  - {n} -> {t}")
    if bonds:
        log.info(f"채권 CUSIP이라 제외 {len(bonds)}개")

    save_json(PRICES_PATH, {"updated_at": datetime.utcnow().isoformat() + "Z", "count": len(prices), "prices": prices})
    save_json(CACHE_PATH, cache)
    log.info(f"저장 완료: {PRICES_PATH}")


if __name__ == "__main__":
    main()
