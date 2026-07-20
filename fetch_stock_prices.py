#!/usr/bin/env python3
"""
fetch_stock_prices.py v9 — Yahoo + Finnhub 하이브리드

1. 기존 Yahoo 성공분 유지 (5698개)
2. 누락분만 Finnhub API로 채움 (검색 + 시세 + 52주)
3. Finnhub 무료 60회/분 → 누락 400개 ≈ 20분
"""

import json, time, logging, re, os
from datetime import datetime
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.parse import quote_plus

ARCHIVE_DIR = Path("docs/us_vips_archive")
PRICES_PATH = Path("docs/stock_prices.json")
TICKER_CACHE_PATH = Path("docs/ticker_cache.json")

YF_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
FINNHUB_KEY = os.environ.get("FINNHUB_API_KEY", "")
FINNHUB = "https://finnhub.io/api/v1"

FOREIGN_SUFFIXES = {'.SW','.MI','.MX','.L','.PA','.DE','.HK','.TO','.AX','.AS','.F'}

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S")
log = logging.getLogger("stock-prices")

MANUAL = {
    "COCA COLA CO":"KO","COCA-COLA CO":"KO","KROGER CO":"KR",
    "BK OF AMERICA CORP":"BAC","BANK AMERICA CORP":"BAC",
    "S&P GLOBAL INC":"SPGI","BLOCK H & R INC":"HRB",
    "PG&E CORP":"PCG","PG&amp;E CORP":"PCG",
    "KKR & CO L P DEL":"KKR","KKR &amp; CO L P DEL":"KKR","KKR & CO INC":"KKR",
    "CI&T INC/UNITED STATES-A":"CINT","CI&amp;T INC/UNITED STATES-A":"CINT",
    "AMAZON COM INC":"AMZN","DISNEY WALT CO":"DIS","WALT DISNEY CO":"DIS",
    "JEFFERIES FINANCIAL GROUP IN":"JEF","JEFFERIES FINANCIAL GROUP INC":"JEF",
    "TENCENT MUSIC ENTMT GROUP":"TME","ELEVANCE HEALTH INC FORMERLY":"ELV",
    "FERGUSON ENTERPRISES INC (FERG)":"FERG","FERGUSON ENTERPRISES INC":"FERG",
    "WILLIS TOWERS WATSON PLC LTD":"WTW","WILLIS TOWERS WATSON PLC":"WTW",
    "TOPBUILD COR":"BLD","TOPBUILD CORP":"BLD","EAGLE MATLS INC":"EXP",
    "SUN CTRY AIRLS HLDGS INC":"SNCY","MIDWESTONE FINL GROUP INC NE":"MOFG",
    "ERMENEGILDO ZEGNA N V":"ZGN","CENTRAIS ELET BRAS SA":"EBR",
    "FIRST AMERN FINL CORP":"FAF","FAIRFAX FINL HLDGS LTD":"FFH",
    "GENUINE PARTS CO":"GPC","AON PLC":"AON","MOLINA HEALTHCARE INC":"MOH",
    "ECHOSTAR CORPORATION":"SATS","CEMEX SAB DE CV":"CX",
    "CNH INDL N V":"CNHI","WIX COM LTD":"WIX",
    "INTERNATIONAL FLAVORS AND FRAGRANCES INC":"IFF",
    "AMERICAN ELECTRIC POWER COMPANY":"AEP",
    "JETBLUE AIRWAYS CORP":"JBLU","JETBLUE AIRWAYS CORP (JBLU)":"JBLU",
    "CAESARS ENTERTAINMENT INC":"CZR","ILLUMINA INC":"ILMN",
    "MASIMO CORP":"MASI","AIR LEASE CORP":"AL",
    "KENNEDY-WILSON HOLDINGS INC":"KW","SPROUTS FARMERS MARKET INC":"SFM",
    "SOUTHWEST GAS HLDGS INC":"SWX","MGM RESORTS INTERNATIONAL":"MGM",
    "HOLOGIC INC":"HOLX","COMERICA INC":"CMA","CIVITAS RESOURCES INC":"CIVI",
    "CONFLUENT INC":"CFLT","CYBERARK SOFTWARE LTD":"CYBR",
    "EVENTBRITE INC":"EB","GUESS INC":"GES","HILLENBRAND INC":"HLI",
    "NU HLDGS LTD":"NU","OLAPLEX HLDGS INC":"OLPX","ON HLDG AG":"ONON",
    "SEMRUSH HLDGS INC":"SEMR","SOLENO THERAPEUTICS INC":"SLNO",
    "SYNOVUS FINL CORP":"SNV","THERMON GROUP HLDGS INC":"THR",
    "TREEHOUSE FOODS INC":"THS","TRUECAR INC":"TRUE","UDEMY INC":"UDMY",
    "WHITE MTNS INS GROUP LTD":"WTM","DAYFORCE INC":"DAY","DENNYS CORP":"DENN",
    "DYNAVAX TECHNOLOGIES CORP":"DVAX","ENHABIT INC":"EHAB",
    "CALAVO GROWERS INC":"CVGW","CANTALOUPE INC":"CTLP",
    "POTLATCHDELTIC CORPORATION":"PCH","PLYMOUTH INDL REIT INC":"PLYM",
    "SUNOPTA INC":"STKL","TEGNA INC":"TGNA",
    "GENEDX HOLDINGS CORP":"WGS","VESTIS CORPORATION":"VSTS",
    "IAC INC":"IAC","FORTREA HLDGS INC":"FTRE","COSTAR GROUP INC":"CSGP",
    "LIONSGATE STUDIOS CORP":"LION","COTERRA ENERGY INC":"CTRA",
    "Coterra Energy Inc.":"CTRA","Tri Pointe Group Inc.":"TPH",
    "AVIDITY BIOSCIENCES INC":"RNA","ARCELLX INC":"ACLX",
    "APELLIS PHARMACEUTICALS INC":"APLS","AMICUS THERAPEUTIC":"FOLD",
    "ASTRIA THERAPEUTICS INC":"ATXS","AVADEL PHARMACEUTICALS PLC":"AVDL",
    "CENTESSA PHARMACEUTICALS PLC":"CNTA","CIDARA THERAPEUTICS INC":"CDTX",
    "CSG SYS INTL INC":"CSGS","KALVISTA PHARMACEUTICALS INC":"KALV",
    "VENTYX BIOSCIENCES INC":"VTYX","TERNS PHARMACEUTICALS INC":"TERN",
    "FLUSHING FINL CORP":"FFIC","ASSERTIO HOLDINGS INC":"ASRT",
    "STANDARD BIOTOOLS INC":"LAB","SYNCHRONOSS TECHNOLOGIES INC":"SNCR",
    "BITFARMS LTD/CANADA":"BITF","FERROVIAL SE":"FER",
    "RESTAURANT BRANDS INTL INC":"QSR","WESCO INTL INC":"WCC",
    "UNION PAC CORP":"UNP","ELEVANCE HEALTH INC":"ELV",
    "T-MOBILE US INC":"TMUS","META PLATFORMS INC":"META",
    "CHARTER COMMUNICATIONS INC":"CHTR","BOOKING HOLDINGS INC":"BKNG",
    "UNITEDHEALTH GROUP INC":"UNH","JOHNSON & JOHNSON":"JNJ",
    "PROCTER & GAMBLE CO":"PG","ESTEE LAUDER COMPANIES INC":"EL",
    "CHARLES SCHWAB CORP":"SCHW","FISERV INC":"FI",
    "AGILENT TECHNOLOGIES INC":"A","TYLER TECHNOLOGIES INC":"TYL",
    "ROPER TECHNOLOGIES INC":"ROP","DOLBY LABORATORIES INC":"DLB",
    "VIASAT INC":"VSAT","VAIL RESORTS INC":"MTN",
    "BROWN & BROWN INC":"BRO","GLOBAL PAYMENTS INC":"GPN",
    "ARCH CAP GROUP LTD":"ACGL","WATERS CORP":"WAT",
    "LIBERTY GLOBAL LTD":"LBTYA","MADISON SQUARE GARDEN SPORTS":"MSGS",
    "NVIDIA CORPORATION":"NVDA","PFIZER INC":"PFE","HALLIBURTON CO":"HAL",
    "PALANTIR TECHNOLOGIES INC":"PLTR","MAGNOLIA OIL & GAS CORP":"MGY",
    "HEICO CORP":"HEI","MSCI INC":"MSCI","SLM CORP":"SLM","BRUKER CORP":"BRKR",
    "NORWEGIAN CRUISE LINE HLDGS":"NCLH","AMERICOLD REALTY TRUST INC":"COLD",
    "GDS HLDGS LTD":"GDS","HERBALIFE LTD":"HLF","DNOW INC":"DNOW",
    "VAXCYTE INC":"PCVX","TELEFLEX INCORPORATED":"TFX",
    "EAST WEST BANCORP INC":"EWBC","CROCS INC":"CROX",
    "PDD HOLDINGS INC":"PDD","LULULEMON ATHLETICA INC":"LULU",
    "DAILY JOURNAL CORP":"DJCO","ON24 INC":"ONTF","ONESTREAM INC":"OS",
    "PEAKSTONE REALTY TRUST":"PKST","SEMLER SCIENTIFIC INC":"SMLR",
    "LINKBANCORP INC":"LNKB","MIDDLEFIELD BANC CORP":"MBCN",
    "LIBERTY MEDIA CORP":"LSXMA","LIBERTY BROADBAND CORP":"LBRDK",
}

def load_json(p):
    if not p.exists(): return None
    with open(p,"r",encoding="utf-8") as f: return json.load(f)

def save_json(p,d):
    with open(p,"w",encoding="utf-8") as f: json.dump(d,f,ensure_ascii=False,indent=1)

def is_equity_cusip(c):
    if not c or len(c)<9: return True
    return c[6:8].isdigit()

def is_valid_us(t):
    if not t: return False
    if t[0].isdigit(): return False
    for s in FOREIGN_SUFFIXES:
        if t.upper().endswith(s.upper()): return False
    if '-P' in t.upper(): return False
    if t.upper().endswith('W') and len(t)>4: return False
    return True

def collect_stocks():
    stocks={}
    for af in sorted(ARCHIVE_DIR.glob("*.json"))[-2:]:
        log.info(f"  종목 수집: {af.name}")
        data=load_json(af)
        if not data: continue
        for gd in data.get("portfolios",{}).values():
            for h in gd.get("holdings",[]):
                cusip=h.get("cusip","").strip()
                name=h.get("name","").strip()
                if not name: continue
                if cusip and not is_equity_cusip(cusip): continue
                name=name.replace("&amp;","&").replace("&lt;","<").replace("&gt;",">")
                name=re.sub(r"<!\[CDATA\[|]]>","",name).strip()
                stocks[name.upper()]={"cusip":cusip,"name":name}
    return stocks

# ── Yahoo (기존 검증된 방식) ──
def yf_search(name):
    variants=[]
    n=re.sub(r'\s*\([^)]*\)','',name).strip()
    n=re.sub(r'\s+FORMERLY$','',n,flags=re.I).strip()
    variants.append(n)
    c=re.sub(r'\s+(INC|CORP|CO|LTD|PLC|LP|LLC|NV|SA|AG|SE|SWITZ|CORPORATION|HLDGS|HOLDINGS|GROUP)\.?$','',n,flags=re.I)
    c=re.sub(r'\s+(INC|CORP|CO|LTD)\.?$','',c,flags=re.I).strip()
    if c!=n: variants.append(c)
    if '&' in c: variants.append(c.replace('&','AND'))
    words=c.split()
    if len(words)>=3: variants.append(" ".join(words[:2]))
    if len(words)>=1 and len(words[0])>=4: variants.append(words[0])
    us_ex={"NYQ","NMS","NGM","NAS","PCX","ASE","BTS","NYS","OPR","NCM"}
    for q in variants:
        url=f"https://query1.finance.yahoo.com/v1/finance/search?q={quote_plus(q)}&quotesCount=5&newsCount=0&listsCount=0"
        try:
            with urlopen(Request(url,headers={"User-Agent":YF_UA}),timeout=10) as r:
                data=json.loads(r.read())
            for qt in data.get("quotes",[]):
                sym=qt.get("symbol","")
                if qt.get("quoteType")=="EQUITY" and qt.get("exchange","") in us_ex and is_valid_us(sym):
                    return sym
            for qt in data.get("quotes",[]):
                sym=qt.get("symbol","")
                if qt.get("quoteType")=="EQUITY" and is_valid_us(sym) and "." not in sym:
                    return sym
        except: pass
        time.sleep(0.3)
    return None

def yf_price(ticker):
    for rng,intv in [("1y","1wk"),("6mo","1d"),("3mo","1d")]:
        url=f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}?range={rng}&interval={intv}&includePrePost=false"
        try:
            with urlopen(Request(url,headers={"User-Agent":YF_UA}),timeout=15) as r:
                data=json.loads(r.read())
            res=data.get("chart",{}).get("result",[])
            if not res: continue
            cur=res[0].get("meta",{}).get("regularMarketPrice",0)
            if not cur: continue
            closes=res[0].get("indicators",{}).get("quote",[{}])[0].get("close",[])
            closes=[c for c in closes if c is not None]
            if not closes: continue
            return {"current_price":round(cur,2),"week52_low":round(min(closes),2),"week52_high":round(max(closes),2)}
        except: continue
    return None

# ── Finnhub (Yahoo 실패분 보완) ──
_fh_calls=0
_fh_window_start=time.time()

def _fh_rate():
    """Finnhub 60회/분 rate limit."""
    global _fh_calls, _fh_window_start
    _fh_calls+=1
    if _fh_calls>=55:
        elapsed=time.time()-_fh_window_start
        if elapsed<62:
            wait=62-elapsed
            log.info(f"    Finnhub rate limit 대기 {wait:.0f}초...")
            time.sleep(wait)
        _fh_calls=0
        _fh_window_start=time.time()

def fh_search(name):
    if not FINNHUB_KEY: return None
    clean=re.sub(r'\s*\([^)]*\)','',name).strip()
    clean=re.sub(r'\s+(INC|CORP|CO|LTD|PLC|LP|LLC|SWITZ|FORMERLY|CORPORATION)\.?$','',clean,flags=re.I)
    clean=re.sub(r'\s+(INC|CORP|CO|LTD)\.?$','',clean,flags=re.I).strip()
    clean=clean.replace('&','AND')
    url=f"{FINNHUB}/search?q={quote_plus(clean)}&token={FINNHUB_KEY}"
    _fh_rate()
    try:
        with urlopen(Request(url),timeout=10) as r:
            data=json.loads(r.read())
        for item in data.get("result",[]):
            sym=item.get("symbol","")
            typ=item.get("type","")
            if typ in ("Common Stock","ADR","EQS","") and is_valid_us(sym) and "." not in sym:
                return sym
    except: pass
    return None

def fh_price(ticker):
    if not FINNHUB_KEY: return None
    # quote
    _fh_rate()
    try:
        url=f"{FINNHUB}/quote?symbol={ticker}&token={FINNHUB_KEY}"
        with urlopen(Request(url),timeout=10) as r:
            q=json.loads(r.read())
        cur=q.get("c",0)
        if not cur or cur==0: return None
    except: return None
    # 52주
    _fh_rate()
    try:
        url=f"{FINNHUB}/stock/metric?symbol={ticker}&metric=all&token={FINNHUB_KEY}"
        with urlopen(Request(url),timeout=10) as r:
            m=json.loads(r.read())
        met=m.get("metric",{})
        w52h=met.get("52WeekHigh",cur)
        w52l=met.get("52WeekLow",cur)
        return {"current_price":round(cur,2),"week52_low":round(w52l,2),"week52_high":round(w52h,2)}
    except:
        return {"current_price":round(cur,2),"week52_low":round(cur,2),"week52_high":round(cur,2)}


def main():
    stocks=collect_stocks()
    log.info(f"고유 종목: {len(stocks)}개 (채권 제외)")
    if not stocks: return
    log.info(f"Finnhub API: {'사용 가능' if FINNHUB_KEY else '키 없음 — Yahoo만 사용'}")

    cache=load_json(TICKER_CACHE_PATH) or {}

    # 외국 티커 캐시 정리
    bad=sum(1 for k in list(cache.keys()) if cache[k] and not is_valid_us(cache[k]) and not cache.pop(k,None) is None)

    # 기존 가격 유지
    existing=(load_json(PRICES_PATH) or {}).get("prices",{})
    prices={}; skipped=0
    for nk,info in stocks.items():
        c=info["cusip"]
        if c and c in existing and existing[c].get("current_price"):
            prices[c]=existing[c]; skipped+=1

    # 이전 실패 캐시 삭제
    for nk,info in stocks.items():
        c=info["cusip"]
        if c and c not in prices:
            cache.pop(c,None); cache.pop(nk,None)

    # 누락분 찾기
    to_do={}
    for nk,info in stocks.items():
        if info["cusip"] not in prices:
            to_do[nk]=info

    log.info(f"기존 유지: {skipped}개, 누락 조회: {len(to_do)}개")

    # ── 누락분 처리: 수동매핑 → 캐시 → Finnhub (Yahoo 스킵) ──
    success=0; failed=[]
    for idx,(nk,info) in enumerate(to_do.items()):
        cusip=info["cusip"]; name=info["name"]

        # 티커 매핑: 수동 → 캐시 → Finnhub
        nk_clean=re.sub(r'\s*\([^)]*\)','',nk).strip()
        nk_clean2=re.sub(r'\s+FORMERLY$','',nk_clean,flags=re.I).strip()
        t = MANUAL.get(nk) or MANUAL.get(nk_clean) or MANUAL.get(nk_clean2) or MANUAL.get(name)
        if not t: t=cache.get(nk) or cache.get(cusip)
        if (not t or not is_valid_us(t)) and FINNHUB_KEY:
            t=fh_search(name)
        if not t:
            failed.append((cusip,name,"티커없음")); continue
        cache[nk]=t
        if cusip: cache[cusip]=t

        # 가격: Finnhub 우선 (빠름), 실패 시 Yahoo
        pd=None
        if FINNHUB_KEY:
            pd=fh_price(t)
        if not pd:
            pd=yf_price(t)
            time.sleep(0.2)

        if pd:
            prices[cusip or nk]={"ticker":t,"name":name,**pd}; success+=1
        else:
            failed.append((cusip,name,t))

        if (idx+1)%50==0:
            log.info(f"  진행: {idx+1}/{len(to_do)} (✓{success} ✗{len(failed)})")

    save_json(TICKER_CACHE_PATH,cache)

    total=len(prices); fails=len(stocks)-total
    log.info(f"━━━ 최종: ✓{total}개 성공, ✗{fails}개 실패 ━━━")
    if failed:
        log.info(f"실패 ({len(failed)}개):")
        for c,n,t in failed[:60]:
            log.info(f"  ✗ {n} (ticker:{t})")
        if len(failed)>60: log.info(f"  ... 외 {len(failed)-60}개")

    save_json(PRICES_PATH,{"updated_at":datetime.utcnow().isoformat()+"Z","count":total,"prices":prices})
    log.info(f"저장: {PRICES_PATH} ({total}개)")

if __name__=="__main__":
    main()
