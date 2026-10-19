#!/usr/bin/env python3
"""
fetch_stock_prices.py v15 - 구루 현재 포트폴리오 시세 업데이트 (완전자동 매핑)

[티커 결정 순서] 앞 단계에서 가격까지 확보되면 끝, 실패하면 다음 단계로 넘어감
  1. CUSIP -> 티커     : CUSIP 캐시 또는 OpenFIGI(Bloomberg 무료 API). 가장 정확
                        (CUSIP은 us_vips.json에 있으면 그것을, 없으면 13F 아카이브에서 이름으로 찾아 씀)
  2. MANUAL            : 사람이 확인한 매핑
  3. 종목명 끝 (티커)    : "WW GRAINGER INC (GWW)" 처럼 이름에 적힌 티커 (회사명 대조 통과 시)
  4. 미국 상장종목 목록  : Nasdaq Trader 공식 심볼 목록과 이름 대조
  5. 이름 캐시          : 과거 검색 결과 (회사명 대조 통과 시)
  6. Yahoo 이름검색     : 회사명 대조 통과 시

[상장폐지 종목] 최근 거래가 없으면 마지막 거래가를 그대로 쓰고 stale=true 표시
               (인수합병 종목은 마지막 가격이 곧 인수가격이라 정보가 됨)

[출력] docs/stock_prices.json  키 = 대문자 종목명, 그리고 CUSIP (둘 다 등록)
[환경변수] FINNHUB_API_KEY (선택), OPENFIGI_API_KEY (선택, 있으면 첫 실행이 훨씬 빠름)
"""
import json, time, logging, re, os, math, csv, io, unicodedata
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.parse import quote_plus, quote
from urllib.error import HTTPError

VIPS_PATH = Path("docs/us_vips.json")
ARCHIVE_DIR = Path("docs/us_vips_archive")
PRICES_PATH = Path("docs/stock_prices.json")
CACHE_PATH = Path("docs/ticker_cache.json")
YF_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
FH_KEY = os.environ.get("FINNHUB_API_KEY", "")
FH = "https://finnhub.io/api/v1"
FIGI_KEY = os.environ.get("OPENFIGI_API_KEY", "")
FIGI_URL = "https://api.openfigi.com/v3/mapping"
MISS_RETRY_DAYS = 7
MISS_PREFIX = "miss3:"   # 종목 키 형식이 바뀌어 이전 검색실패 기록은 무시
WORKERS = 8              # Yahoo 가격 동시조회 수 (429 오류가 많으면 줄일 것)
SEARCH_WORKERS = 4       # Yahoo 이름검색 동시 수
SEARCH_BUDGET_SEC = 600  # 이름검색에 쓰는 최대 시간 (남은 건 다음 실행 때 이어서)
DEAD = "DEAD"            # Yahoo가 "없는 종목"이라고 확답한 경우
STALE_DAYS = 14
FIGI_BUDGET_SEC = 2400   # OpenFIGI 조회 최대 시간 (키 없을 때 첫 실행용, 남은 건 다음 실행에 이어서)

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
    "STK", "AND", "OF", "TR", "TRUST", "FORMERLY", "SAB", "DE", "CV",
    "ASA", "OYJ", "SPA", "BHD", "SWITZ", "PAR", "NPV",
    "COMMON", "STOCK", "SHARES", "ORDINARY", "DEPOSITARY", "REGISTRY", "REG", "NY",
    "EACH", "REPRESENTING", "ONE", "TWO", "THREE", "FOUR", "FIVE", "TEN",
    "CAYMAN", "ISL", "ISLANDS", "BERMUDA", "JERSEY", "DBA", "D", "B", "A",
    "BENEFICIAL", "INTEREST", "INTERESTS", "UNIT", "REPSTG", "BE",
    "NON", "VTG", "VOTING", "NONVOTING", "SHR", "SHRS", "HLDNGS", "HLDG", "PL", "JSC", "PJSC",
    "JOINT", "PRF", "PFD", "SPONS", "NAMEN", "AKT", "SPN", "USD", "DELAWARE",
}
SPONSOR_SKIP = {"STATE", "STREET"}   # "State Street SPDR ..." 처럼 앞에 붙는 운용사명

# 13F에서 자주 쓰는 약어 -> 정식 단어 (부분수열로 안 잡히는 것만)
ABBR = {
    "BK": "BANK", "BKS": "BANKS", "ED": "EDUCATION", "EDL": "EDUCATIONAL",
    "PPTYS": "PROPERTIES", "PPTY": "PROPERTY", "CMNTYS": "COMMUNITIES", "CMNTY": "COMMUNITY",
    "TECHNOLOGY": "TECHNOLOGIES", "TECH": "TECHNOLOGIES", "TECHS": "TECHNOLOGIES",
    "COMMUNICATION": "COMMUNICATIONS", "COMMS": "COMMUNICATIONS", "COMM": "COMMUNICATIONS",
    "PHARMACEUTICAL": "PHARMACEUTICALS", "PHARMA": "PHARMACEUTICALS", "PHARMS": "PHARMACEUTICALS",
    "PHARM": "PHARMACEUTICALS",
    "LABS": "LABORATORIES", "LAB": "LABORATORIES", "LABORATORY": "LABORATORIES",
    "MUNIPL": "MUNICIPAL", "MUNI": "MUNICIPAL", "MUN": "MUNICIPAL",
    "ISHR": "ISHARES", "ISHRS": "ISHARES", "ISH": "ISHARES",
    "SS": "STATE", "STR": "STREET", "CR": "CORE", "BD": "BOND", "BDS": "BONDS",
    "AMER": "AMERICA", "AMERN": "AMERICA", "AMERICAN": "AMERICA", "AMERICAS": "AMERICA",
    "INTL": "INTERNATIONAL", "INTERNATL": "INTERNATIONAL", "INTRNTNL": "INTERNATIONAL",
    "BANCORPORATION": "BANCORP", "ENTMT": "ENTERTAINMENT", "SVCS": "SERVICES",
    "NATL": "NATIONAL", "FINL": "FINANCIAL", "MGMT": "MANAGEMENT", "MFG": "MANUFACTURING",
    "HLTH": "HEALTH", "HLTHCARE": "HEALTHCARE", "INS": "INSURANCE", "SYS": "SYSTEMS",
    "RLTY": "REALTY", "INVTS": "INVESTMENTS", "INVT": "INVESTMENT", "PRODS": "PRODUCTS",
    "RES": "RESOURCES", "MATLS": "MATERIALS", "ELEC": "ELECTRIC", "ENERGY": "ENERGY",
    "SMALLCAP": "SMALL", "MIDCAP": "MID", "LARGECAP": "LARGE", "SVC": "SERVICE",
    "PAC": "PACIFIC", "MTG": "MORTGAGE", "MTN": "MOUNTAIN", "MTNS": "MOUNTAINS",
    "MNG": "MINING", "MNGT": "MANAGEMENT", "WHSL": "WHOLESALE", "RY": "RAILWAY", "CDA": "CANADA",
    "MTR": "MOTOR", "MTRS": "MOTORS", "GRW": "GROWTH", "YLD": "YIELD", "EQ": "EQUITY",
    "DEV": "DEVELOPED", "TREAS": "TREASURY", "AGG": "AGGREGATE", "TRM": "TERM", "YR": "YEAR",
    "CHEM": "CHEMICAL", "CHEMS": "CHEMICALS", "ELECTRS": "ELECTRONICS", "SEMICONDUCTR": "SEMICONDUCTOR",
    "ETF": "FUND", "FD": "FUND", "FDS": "FUNDS", "ETFS": "FUNDS",
    "MFRS": "MANUFACTURERS", "PETE": "PETROLEUM", "PETRO": "PETROLEUM", "CTR": "CENTER", "CTRS": "CENTERS", "GRWTH": "GROWTH",
}
GLUED_SUFFIX = {"COM", "INC", "CORP", "CO", "LTD", "PLC", "GROUP", "HLDGS", "HOLDINGS", "NV", "SA", "AG"}
STOP_TAIL = {"NEW", "DEL"}   # 이름 맨 앞이 아닐 때만 무시 (NEW YORK TIMES는 살림)
ETF_HINT = re.compile(r"\b(ETF|ETFS|ETN|FUND|FD|FDS|TR|TRUST|INDEX|SHARES|ISHARES|ISHR|ISHRS|SPDR|PORTFOLIO|VANGUARD|INVESCO|PROSHARES|SCHWAB)\b")

IDF = {}
IDF_MAX = 6.0


def tokens(s):
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))     # América -> America
    s = s.upper().replace("'", "").replace("\u2019", "")   # MOODY'S -> MOODYS
    s = re.sub(r"\s*\([A-Z0-9.\-/ ]{1,12}\)\s*$", "", s)        # 끝의 (티커) 제거
    s = re.sub(r"\s*\([A-Z0-9.\-/ ]{1,12}\)\s*$", "", s)
    s = re.sub(r"AMERICAN DEPOSITARY (SHARES|RECEIPTS?)", " ", s)
    s = re.sub(r"\bCAP(ITAL)? STK\b", " ", s)                  # ALPHABET INC CAP STK CL C
    s = re.sub(r"[\-\s]+(SP|SPON|SPONS|SPONSORED|UNSPON)?\s*ADRS?\b", " ", s)
    s = re.sub(r"(?<=[A-Z])(?=\d{2,})|(?<=\d)(?=[A-Z]{2})", " ", s)   # S&P500 -> S&P 500
    s = re.sub(r"\b([A-Z])\s+(?=[A-Z]\b)", r"\1", s)           # P G & E -> PG & E
    s = re.sub(r"\b([A-Z]{1,3})\s*&\s*([A-Z]{1,3})\b", r"\1\2", s)  # PG&E -> PGE, S&P -> SP, AT&T -> ATT
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


def tok_eq(a, b, last=False, first=False):
    """a(13F 쪽 단어)와 b(정식 회사명 단어)가 같은 단어인지. 약어는 a가 줄임말일 때만 인정"""
    if a == b:
        return True
    if last and len(a) >= 2 and len(b) > len(a) and b.startswith(a):
        return True                                          # 13F 이름 끝 잘림 (TREASURY BO = BOND)
    s, l = (a, b) if len(a) <= len(b) else (b, a)
    if len(s) < 3 or s.isdigit() or l.isdigit():
        return False
    if l.startswith(s):
        if a == s:
            # 13F 쪽이 잘린 약어 (CHEM = CHEMICAL, NEV = NEVADA). 한 글자 차이는 불인정 (SQUARE != SQUARED)
            # 회사명 첫 단어는 확실한 약어만 인정 (CAN = CANADIAN 은 인정, LUMEN != LUMENTUM)
            if first and not (len(a) <= 4 or len(a) / len(b) <= 0.5):
                return False
            return len(b) - len(a) >= 2
        # 법인격이 붙어버린 경우 (13F AMAZONCOM = AMAZON). EMERALD != EMERA
        return len(b) >= 4 and a[len(b):] in GLUED_SUFFIX
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
    if not any(tok_eq(ta[0], y, first=True) for y in tb[:3]):
        return 0.0
    # 상대 회사명의 첫 단어도 13F 이름 안에 있어야 함 (GENERAL ELECTRIC != PORTLAND GENERAL ELECTRIC)
    if tb[0] not in SPONSOR_SKIP and not any(tok_eq(x, tb[0]) for x in ta):
        return 0.0
    used, num_a, den_a = set(), 0.0, 0.0
    n = len(ta)
    for i, x in enumerate(ta):
        hit = None
        for j, y in enumerate(tb):
            if j not in used and tok_eq(x, y, last=(truncated and i == n - 1), first=(i == 0)):
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
        self.by_base = {}   # 티커 -> 회사명 부분 (Common Stock 등 제거)
        self.bad_syms = set()  # 우선주, 채권, 워런트 등 (주식 아님)

    def add_rows(self, rows, sym_col):
        n = 0
        for row in rows:
            sym = (row.get(sym_col) or "").strip()
            name = (row.get("Security Name") or "").strip()
            if not sym or not name or sym.startswith("File Creation"):
                continue
            if (row.get("Test Issue") or "N").strip().upper() == "Y":
                continue
            name = name.replace(")", ") ")
            base = self.CUT.split(name.split(" - ")[0])[0]
            up = name.upper()
            ysym = sym.replace(".", "-").replace("/", "-").replace("$", "-P")
            if "$" in sym or "%" in up or BAD_SEC.search(base.upper()) \
                    or re.search(r"\b(WARRANTS?|RIGHTS?|UNITS?)\s*$", up.strip()) \
                    or ("AMERICAN DEPOSITARY" not in up and re.search(r"\b(PREFERRED|PREF)\b", up)):
                self.bad_syms.add(ysym)
                continue
            tk = tokens(base)
            if not tk or ysym in self.by_sym:
                continue
            etf = (row.get("ETF") or "N").strip().upper() == "Y"
            self.by_sym[ysym] = name
            self.by_base[ysym] = base
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

    def match(self, name, th=0.75, margin=0.05):
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
    if not t or not isinstance(t, str) or t[0].isdigit() or t[0] in "^=" or "=" in t:
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
    try:
        cl = [x for x in res["indicators"]["quote"][0]["close"] if x]
    except Exception:
        cl = []
    hi = meta.get("fiftyTwoWeekHigh") or (max(cl) if cl else cur)
    lo = meta.get("fiftyTwoWeekLow") or (min(cl) if cl else cur)
    hi, lo = max(hi, cur), min(lo, cur)
    name = meta.get("longName") or meta.get("shortName") or ""
    pd = {"current_price": round(cur, 2), "week52_low": round(lo, 2), "week52_high": round(hi, 2)}
    mt = meta.get("regularMarketTime")
    if mt and time.time() - mt > STALE_DAYS * 86400:
        # 장기간 거래 없음 = 상장폐지/인수합병/거래정지 추정 → 마지막 거래가를 표시용으로 남김
        pd["stale"] = True
        pd["last_trade"] = datetime.utcfromtimestamp(mt).strftime("%Y-%m-%d")
    return (pd, name)


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
    prof = fh_get(f"stock/profile2?symbol={quote(t)}") or {}
    m = (fh_get(f"stock/metric?symbol={quote(t)}&metric=all") or {}).get("metric", {}) or {}
    hi = max(m.get("52WeekHigh") or cur, cur)
    lo = min(m.get("52WeekLow") or cur, cur)
    pd = {"current_price": round(cur, 2), "week52_low": round(lo, 2), "week52_high": round(hi, 2)}
    if ts and time.time() - ts > STALE_DAYS * 86400:
        pd["stale"] = True
        pd["last_trade"] = datetime.utcfromtimestamp(ts).strftime("%Y-%m-%d")
    return (pd, prof.get("name", ""))


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
            if names_match(name, qn) or initials_ok(name, s, qn):
                return s
        time.sleep(0.2)
    return None


def openfigi(cusips):
    """CUSIP 리스트 -> ({cusip: ticker}, 주식 티커가 없다고 확인된 CUSIP 집합).
    주식 외(채권, 옵션, 워런트, 우선주)는 버림"""
    if not cusips:
        return {}, set()
    headers = {"Content-Type": "application/json"}
    if FIGI_KEY:
        headers["X-OPENFIGI-APIKEY"] = FIGI_KEY
    size, gap, wait429 = (100, 0.3, 7) if FIGI_KEY else (10, 2.5, 61)
    out, misses = {}, set()
    err_streak = 0
    st = {"ok": 0, "nomatch": 0, "nonequity": 0, "err": 0}
    first_err = None
    t_start = time.time()
    for i in range(0, len(cusips), size):
        if time.time() - t_start > FIGI_BUDGET_SEC:
            log.info(f"  OpenFIGI 시간 예산 초과 → 남은 {len(cusips) - i}개는 다음 실행에서 조회")
            break
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
            err_streak += 1
            if err_streak >= 3:
                log.info("  OpenFIGI 연속 오류 → 이번 실행에서는 중단 (이름 기반으로 대체)")
                break
        else:
            err_streak = 0
            for c, item in zip(batch, data):
                rows = (item or {}).get("data") or []
                if not rows:
                    st["nomatch"] += 1
                    misses.add(c)
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
                    misses.add(c)
        time.sleep(gap)
    log.info(f"  OpenFIGI: 성공 {st['ok']}, 미발견 {st['nomatch']}, 주식아님 {st['nonequity']}, 오류 {st['err']}")
    if first_err:
        log.info(f"  OpenFIGI 첫 오류: {first_err}")
    return out, misses


# ━━━━━━━━━━━━━━━━━━━━━━ 메인 ━━━━━━━━━━━━━━━━━━━━━━

def base_name(n):
    """이름 비교용 정규형: 끝의 (티커) 제거, 마침표/쉼표 제거"""
    n = clean_name(n).upper()
    for _ in range(2):
        n = re.sub(r"\s*\([A-Z0-9.\-/ ]{1,12}\)\s*$", "", n)
    n = n.replace(".", "").replace(",", "")
    return re.sub(r"\s+", " ", n).strip()


def archive_cusips():
    """13F 아카이브(최근 8개 분기)에서 '종목명 -> CUSIP'. 같은 이름에 주식 CUSIP이 하나뿐일 때만 사용"""
    out = {}
    if not ARCHIVE_DIR.exists():
        return {}
    for f in sorted(ARCHIVE_DIR.glob("*.json"), reverse=True)[:8]:
        a = load_json(f) or {}
        for g in (a.get("portfolios") or {}).values():
            for h in g.get("holdings", []) or []:
                c = norm_cusip(h.get("cusip"))
                if not c or is_debt_cusip(c) or (h.get("type") or "SH").upper() == "PRN":
                    continue
                out.setdefault(base_name(h.get("name", "")), set()).add(c)
    return {k: next(iter(v)) for k, v in out.items() if len(v) == 1 and k}


def collect():
    """us_vips.json 현재 보유 종목을 CUSIP(없으면 이름) 단위로 묶음"""
    vips = load_json(VIPS_PATH)
    if not vips:
        log.error("us_vips.json 로드 실패")
        return {}
    portfolios = vips.get("portfolios", vips)
    amap = archive_cusips()
    items = {}
    for guru, data in portfolios.items():
        if not isinstance(data, dict):
            continue
        for h in data.get("holdings", []) or []:
            n = clean_name(str(h.get("name", "")).strip())
            if not n or n.upper() in ("NONE", "N/A"):
                continue
            if (h.get("type") or "SH").upper() == "PRN":
                continue                                   # 채권
            c = norm_cusip(h.get("cusip") or h.get("CUSIP"))
            src = "13F" if c else ""
            if not c:
                c = amap.get(base_name(n), "")
                src = "아카이브" if c else ""
            if c and is_debt_cusip(c):
                continue                                   # 채권 CUSIP
            key = c or ("N:" + n.upper())
            e = items.setdefault(key, {"name": n, "names": set(), "cusip": c, "src": src})
            e["names"].add(n.upper())
    return items


def days_since(d, today):
    try:
        return (today - datetime.strptime(d, "%Y-%m-%d").date()).days
    except Exception:
        return 9999


def main():
    t_start = time.time()
    items = collect()
    if not items:
        return
    n13 = sum(1 for e in items.values() if e["src"] == "13F")
    nar = sum(1 for e in items.values() if e["src"] == "아카이브")
    log.info(f"현재 포트폴리오 고유 종목: {len(items)}개 (CUSIP: 13F {n13}개, 아카이브 {nar}개, 없음 {len(items)-n13-nar}개)")

    raw = load_json(CACHE_PATH) or {}
    cache = {k: v for k, v in raw.items() if isinstance(v, str) and not k.startswith(("miss:", "miss2:"))}
    today = datetime.utcnow().date()

    # ━━ 1단계: CUSIP -> 티커 (캐시에 없는 것만 OpenFIGI, 못 찾은 건 30일간 재조회 안 함) ━━
    need = sorted({e["cusip"] for e in items.values()
                   if e["cusip"] and not cache.get(f"cusip:{e['cusip']}")
                   and days_since(cache.get(f"figimiss:{e['cusip']}", ""), today) > 30})
    if need:
        est = len(need) / (100 if FIGI_KEY else 10) * (0.3 if FIGI_KEY else 2.5) / 60
        log.info(f"1단계 OpenFIGI 조회: CUSIP {len(need)}개 (예상 약 {est:.0f}분)")
        fmap, fmiss = openfigi(need)
        for c, t in fmap.items():
            cache[f"cusip:{c}"] = t
            cache.pop(f"figimiss:{c}", None)
        for c in fmiss:
            cache[f"figimiss:{c}"] = today.isoformat()

    log.info("상장종목 목록 불러오는 중")
    directory = load_directory()
    log.info(f"  총 {len(directory.entries)}개 종목")

    # ━━ 2단계: 종목별 후보 티커 정리 ━━
    plans = {}
    for k, e in items.items():
        plan = []
        if e["cusip"] and cache.get(f"cusip:{e['cusip']}"):
            plan.append((cache[f"cusip:{e['cusip']}"], True, "CUSIP"))
        for nm in sorted(e["names"]):
            nc = re.sub(r"\s*\([^)]*\)", "", nm).strip()
            nc2 = re.sub(r"\s+FORMERLY$", "", nc).strip()
            mt = MANUAL_UP.get(nm) or MANUAL_UP.get(nc) or MANUAL_UP.get(nc2)
            if mt:
                plan.append((mt, True, "MANUAL"))
                break
        pt = paren_ticker(e["name"])
        if pt:
            plan.append((pt, False, "이름속티커"))
        dt = directory.match(e["name"]) if directory.entries else None
        if dt:
            plan.append((dt, True, "상장종목목록"))
        for nm in sorted(e["names"]):
            if cache.get(nm):
                plan.append((cache[nm], False, "이름캐시"))
                break
        plans[k] = plan

    # ━━ 3단계: 후보 티커 가격 동시조회 후 채택 ━━
    log.info(f"3단계 가격 동시조회 (동시 {WORKERS}개)")
    pmemo = {}
    prefetch({t for p in plans.values() for t, _, _ in p}, pmemo)

    result = {}          # key -> (ticker, pd, src)
    rejected, manual_bad = [], []
    dead = {}            # key -> ticker (CUSIP으로 확정된 티커인데 가격 자체가 없음)

    def check(k, t, trusted, src):
        if not t or not valid(t):
            return None
        if not trusted and t in directory.bad_syms:
            return None          # 같은 회사의 우선주, 채권, 워런트 티커는 제외
        if t not in pmemo:
            pmemo[t] = get_price(t)
            time.sleep(0.1)
        r = pmemo[t]
        if not r:
            return None
        pd, pname = r
        if not trusted:
            n = items[k]["name"]
            dn = directory.by_base.get(t)
            ok = (not pname) or names_match(n, pname) or initials_ok(n, t, pname) or (dn and names_match(n, dn))
            if not ok:
                rejected.append((n, t, pname, src))
                return None
        return pd

    def choose(k, plan):
        stale_pick = None
        for t, trusted, src in plan:
            pd = check(k, t, trusted, src)
            if pd is None:
                if src == "MANUAL":
                    manual_bad.append((items[k]["name"], t))
                if src == "CUSIP":
                    dead[k] = t
                continue
            if src == "CUSIP" or not pd.get("stale"):
                return (t, pd, src)        # CUSIP 티커는 상장폐지여도 그대로 사용 (가장 정확)
            if stale_pick is None:
                stale_pick = (t, pd, src)
        return stale_pick

    pending = []
    for k, plan in plans.items():
        pick = choose(k, plan)
        if pick:
            result[k] = pick
            dead.pop(k, None)
        else:
            if any(r[0] == items[k]["name"] and r[3] == "이름캐시" for r in rejected[-3:]):
                for nm in items[k]["names"]:
                    cache.pop(nm, None)   # 잘못된 이름 캐시 자동 삭제
            pending.append(k)
    log.info(f"3단계 완료: 성공 {len(result)}, 남음 {len(pending)}")

    # ━━ 4단계: Yahoo 이름검색 (회사명 대조 필수, 시간 제한, 실패 종목은 7일간 생략) ━━
    targets = [k for k in pending if k not in dead
               and days_since(cache.get(MISS_PREFIX + k, ""), today) >= MISS_RETRY_DAYS]
    if targets:
        log.info(f"4단계 Yahoo 이름검색: {len(targets)}개 (동시 {SEARCH_WORKERS}개, 최대 {SEARCH_BUDGET_SEC}초)")
        t0 = time.time()
        deadline = t0 + SEARCH_BUDGET_SEC
        with ThreadPoolExecutor(max_workers=SEARCH_WORKERS) as ex:
            found = dict(zip(targets, ex.map(lambda k: yf_search(items[k]["name"], deadline), targets)))
        prefetch([t for t in found.values() if t and t != "SKIP"], pmemo)
        for k in targets:
            t = found.get(k)
            if t == "SKIP":
                continue
            pd = check(k, t, False, "Yahoo검색") if t else None
            if pd is not None:
                result[k] = (t, pd, "Yahoo검색")
                cache.pop(MISS_PREFIX + k, None)
            else:
                cache[MISS_PREFIX + k] = today.isoformat()
        log.info(f"4단계 완료: 누적 성공 {len(result)}, {time.time()-t0:.0f}초")

    # ━━ 저장 ━━
    prices, src_count, n_stale = {}, {}, 0
    for k, (t, pd, src) in result.items():
        e = items[k]
        rec = {"ticker": t, "name": e["name"], **pd}
        for nm in e["names"]:
            prices[nm] = rec
        if src != "MANUAL":
            cache[e["name"].upper()] = t
        if e["cusip"]:
            prices[e["cusip"]] = rec
        src_count[src] = src_count.get(src, 0) + 1
        n_stale += 1 if pd.get("stale") else 0

    missing = [k for k in items if k not in result]
    log.info(f"━━━ 최종: 성공 {len(result)} / 전체 {len(items)} ({time.time()-t_start:.0f}초) ━━━")
    log.info("성공 경로별: " + ", ".join(f"{s} {n}" for s, n in sorted(src_count.items(), key=lambda x: -x[1])))
    if n_stale:
        log.info(f"이 중 최근 거래 없음(상장폐지/인수합병 추정, 마지막 거래가 표시): {n_stale}개")
    if dead:
        log.info(f"CUSIP으로 티커는 확정됐으나 가격 조회 불가 {len(dead)}개:")
        for k, t in list(dead.items())[:40]:
            log.info(f"  - {items[k]['name']} ({t})")
    unknown = [k for k in missing if k not in dead]
    if unknown:
        log.info(f"티커 못 찾음 {len(unknown)}개 (외국 상장, 비상장, 사명변경 등):")
        for k in unknown[:80]:
            e = items[k]
            log.info(f"  - {e['name']}" + (f" [CUSIP {e['cusip']}]" if e["cusip"] else ""))
    if rejected:
        log.info(f"회사명 불일치로 거절한 매핑 {len(rejected)}건 (오매핑 차단):")
        for n, t, pn, src in rejected[:40]:
            log.info(f"  - {n} -> {t} ({pn}) [{src}]")
    if manual_bad:
        log.info(f"MANUAL 티커 가격조회 실패 {len(manual_bad)}건 (다른 방법으로 자동 대체 시도함)")

    save_json(PRICES_PATH, {"updated_at": datetime.utcnow().isoformat() + "Z", "count": len(result), "prices": prices})
    save_json(CACHE_PATH, cache)
    log.info(f"저장 완료: {PRICES_PATH}")


if __name__ == "__main__":
    main()
