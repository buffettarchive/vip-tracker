#!/usr/bin/env python3
"""
fetch_stock_prices.py — 81명 구루 현재 포트폴리오 시세 업데이트

★ us_vips.json(현재 보유)만 대상. 히스토리/아카이브 무시.
★ 13F 공시 = 모두 상장기업 = 100% 매핑 가능해야 함.
★ ~2500개 종목 × 0.2초 = ~8분이면 완료.
"""
import json,time,logging,re,os
from datetime import datetime
from pathlib import Path
from urllib.request import Request,urlopen
from urllib.parse import quote_plus

VIPS_PATH=Path("docs/us_vips.json")
PRICES_PATH=Path("docs/stock_prices.json")
CACHE_PATH=Path("docs/ticker_cache.json")
YF_UA="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
FH_KEY=os.environ.get("FINNHUB_API_KEY","")
FH="https://finnhub.io/api/v1"

logging.basicConfig(level=logging.INFO,format="%(asctime)s [%(levelname)s] %(message)s",datefmt="%H:%M:%S")
log=logging.getLogger("prices")

# ── 수동 매핑: Yahoo/Finnhub 검색이 안 되는 종목 ──
MANUAL={
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
    "CNH INDL N V":"CNHI","WIX COM LTD":"WIX",
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

def load_json(p):
    if not p.exists():return None
    with open(p,"r",encoding="utf-8") as f:return json.load(f)
def save_json(p,d):
    with open(p,"w",encoding="utf-8") as f:json.dump(d,f,ensure_ascii=False,indent=1)
def valid(t):
    if not t or t[0].isdigit():return False
    for s in ['.SW','.MI','.MX','.L','.PA','.DE','.HK','.TO','.AX']:
        if t.upper().endswith(s):return False
    if '-P' in t.upper():return False
    return True

def collect():
    """us_vips.json에서 현재 보유 종목만 수집."""
    vips=load_json(VIPS_PATH)
    if not vips:
        log.error("us_vips.json 로드 실패")
        return {}
    portfolios=vips.get("portfolios",vips)
    names={}
    for guru,data in portfolios.items():
        for h in data.get("holdings",[]):
            n=h.get("name","").strip()
            if not n:continue
            n=n.replace("&amp;","&").replace("&lt;","<").replace("&gt;",">")
            n=re.sub(r"<!\[CDATA\[|]]>","",n).strip()
            names[n.upper()]=n
    return names

def yf_search(name):
    vs=[]
    n=re.sub(r'\s*\([^)]*\)','',name).strip()
    n=re.sub(r'\s+FORMERLY$','',n,flags=re.I).strip()
    vs.append(n)
    c=re.sub(r'\s+(INC|CORP|CO|LTD|PLC|LP|LLC|NV|SA|AG|SE|SWITZ|CORPORATION|HLDGS|HOLDINGS|GROUP)\.?$','',n,flags=re.I)
    c=re.sub(r'\s+(INC|CORP|CO|LTD)\.?$','',c,flags=re.I).strip()
    if c!=n:vs.append(c)
    if '&' in c:vs.append(c.replace('&','AND'))
    w=c.split()
    if len(w)>=3:vs.append(" ".join(w[:2]))
    if len(w)>=1 and len(w[0])>=4:vs.append(w[0])
    us={"NYQ","NMS","NGM","NAS","PCX","ASE","BTS","NYS","OPR","NCM"}
    for q in vs:
        try:
            url=f"https://query1.finance.yahoo.com/v1/finance/search?q={quote_plus(q)}&quotesCount=5&newsCount=0"
            with urlopen(Request(url,headers={"User-Agent":YF_UA}),timeout=10) as r:
                d=json.loads(r.read())
            for qt in d.get("quotes",[]):
                s=qt.get("symbol","")
                if qt.get("quoteType")=="EQUITY" and qt.get("exchange","") in us and valid(s):return s
            for qt in d.get("quotes",[]):
                s=qt.get("symbol","")
                if qt.get("quoteType")=="EQUITY" and valid(s) and "." not in s:return s
        except:pass
        time.sleep(0.25)
    return None

def yf_price(t):
    for rng,iv in [("1y","1wk"),("6mo","1d"),("3mo","1d")]:
        try:
            url=f"https://query1.finance.yahoo.com/v8/finance/chart/{t}?range={rng}&interval={iv}&includePrePost=false"
            with urlopen(Request(url,headers={"User-Agent":YF_UA}),timeout=15) as r:
                d=json.loads(r.read())
            res=d.get("chart",{}).get("result",[])
            if not res:continue
            cur=res[0].get("meta",{}).get("regularMarketPrice",0)
            if not cur:continue
            cl=res[0].get("indicators",{}).get("quote",[{}])[0].get("close",[])
            cl=[x for x in cl if x]
            if not cl:continue
            return{"current_price":round(cur,2),"week52_low":round(min(cl),2),"week52_high":round(max(cl),2)}
        except:continue
    return None

_fc=0;_ft=time.time()
def _fr():
    global _fc,_ft
    _fc+=1
    if _fc>=55:
        e=time.time()-_ft
        if e<62:time.sleep(62-e)
        _fc=0;_ft=time.time()

def fh_search(name):
    if not FH_KEY:return None
    c=re.sub(r'\s*\([^)]*\)','',name).strip()
    c=re.sub(r'\s+(INC|CORP|CO|LTD|PLC|CORPORATION|FORMERLY)\.?$','',c,flags=re.I)
    c=re.sub(r'\s+(INC|CORP|CO|LTD)\.?$','',c,flags=re.I).strip().replace('&','AND')
    _fr()
    try:
        url=f"{FH}/search?q={quote_plus(c)}&token={FH_KEY}"
        with urlopen(Request(url),timeout=10) as r:
            d=json.loads(r.read())
        for i in d.get("result",[]):
            s=i.get("symbol","")
            if i.get("type","") in ("Common Stock","ADR","EQS","") and valid(s) and "." not in s:return s
    except:pass
    return None

def fh_price(t):
    if not FH_KEY:return None
    _fr()
    try:
        with urlopen(Request(f"{FH}/quote?symbol={t}&token={FH_KEY}"),timeout=10) as r:
            q=json.loads(r.read())
        cur=q.get("c",0)
        if not cur:return None
    except:return None
    _fr()
    try:
        with urlopen(Request(f"{FH}/stock/metric?symbol={t}&metric=all&token={FH_KEY}"),timeout=10) as r:
            m=json.loads(r.read())
        mt=m.get("metric",{})
        return{"current_price":round(cur,2),"week52_low":round(mt.get("52WeekLow",cur),2),"week52_high":round(mt.get("52WeekHigh",cur),2)}
    except:
        return{"current_price":round(cur,2),"week52_low":round(cur,2),"week52_high":round(cur,2)}

def main():
    names=collect()
    log.info(f"현재 포트폴리오 고유 종목: {len(names)}개")
    if not names:return

    cache=load_json(CACHE_PATH) or {}
    # 외국 티커 정리
    for k in list(cache.keys()):
        if cache[k] and not valid(cache[k]):del cache[k]

    # ━━ 1단계: 전체 티커 매핑 ━━
    tmap={}; need=[]
    for nk,name in names.items():
        nc=re.sub(r'\s*\([^)]*\)','',nk).strip()
        nc2=re.sub(r'\s+FORMERLY$','',nc,flags=re.I).strip()
        t=MANUAL.get(nk) or MANUAL.get(nc) or MANUAL.get(nc2) or MANUAL.get(name) or cache.get(nk)
        if t and valid(t):
            tmap[nk]=t
        else:
            need.append((nk,name))
    log.info(f"매핑 완료: {len(tmap)}개, 검색 필요: {len(need)}개")

    if need:
        # Yahoo 검색
        yf_ok=0
        for nk,name in need:
            t=yf_search(name)
            if t:tmap[nk]=t;cache[nk]=t;yf_ok+=1
            time.sleep(0.15)
        log.info(f"  Yahoo 검색: {yf_ok}개")
        # Finnhub 검색 (Yahoo 실패분)
        still=[x for x in need if x[0] not in tmap]
        if still and FH_KEY:
            fh_ok=0
            for nk,name in still:
                t=fh_search(name)
                if t:tmap[nk]=t;cache[nk]=t;fh_ok+=1
            log.info(f"  Finnhub 검색: {fh_ok}개")
        save_json(CACHE_PATH,cache)

    no_ticker=[nk for nk in names if nk not in tmap]
    if no_ticker:
        log.info(f"티커 미매핑: {len(no_ticker)}개")
        for nk in no_ticker[:20]:log.info(f"  ? {names[nk]}")

    # ━━ 2단계: 가격 조회 (Yahoo → Finnhub fallback) ━━
    # 동일 티커 중복 제거
    uniq={}
    for nk,t in tmap.items():
        if t not in uniq:uniq[t]=nk

    log.info(f"━━ 가격 조회: {len(uniq)}개 티커 ━━")
    prices={};failed=[];ok=0

    for idx,(t,nk) in enumerate(uniq.items()):
        name=names.get(nk,t)
        pd=yf_price(t)
        if not pd and FH_KEY:
            pd=fh_price(t)
        if pd:
            prices[nk]={"ticker":t,"name":name,**pd};ok+=1
        else:
            failed.append((nk,name,t))
        time.sleep(0.18)
        if(idx+1)%200==0:
            log.info(f"  {idx+1}/{len(uniq)} (✓{ok} ✗{len(failed)})")

    # 동일 티커 다른 이름도 등록 (같은 가격)
    for nk,t in tmap.items():
        if nk not in prices:
            src=next((k for k,v in prices.items() if v.get("ticker")==t),None)
            if src:prices[nk]={**prices[src],"name":names.get(nk,nk)}

    log.info(f"━━━ 최종: ✓{len(prices)}개 / {len(names)}개 ━━━")
    if failed:
        log.info(f"가격 실패 ({len(failed)}개):")
        for nk,n,t in failed[:30]:log.info(f"  ✗ {n} ({t})")
    if no_ticker:
        log.info(f"티커 없음 ({len(no_ticker)}개):")
        for nk in no_ticker[:30]:log.info(f"  ✗ {names[nk]}")

    save_json(PRICES_PATH,{"updated_at":datetime.utcnow().isoformat()+"Z","count":len(prices),"prices":prices})
    log.info(f"저장 완료: {PRICES_PATH}")

if __name__=="__main__":
    main()
