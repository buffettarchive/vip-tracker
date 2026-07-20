#!/usr/bin/env python3
"""
fetch_stock_prices.py v10 — 매일 전체 갱신
Yahoo(빠름) → Finnhub(Yahoo 실패분만 보완)
"""
import json,time,logging,re,os
from datetime import datetime
from pathlib import Path
from urllib.request import Request,urlopen
from urllib.parse import quote_plus

ARCHIVE_DIR=Path("docs/us_vips_archive")
PRICES_PATH=Path("docs/stock_prices.json")
CACHE_PATH=Path("docs/ticker_cache.json")
YF_UA="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
FH_KEY=os.environ.get("FINNHUB_API_KEY","")
FH="https://finnhub.io/api/v1"
FOREIGN={'.SW','.MI','.MX','.L','.PA','.DE','.HK','.TO','.AX','.AS','.F'}

logging.basicConfig(level=logging.INFO,format="%(asctime)s [%(levelname)s] %(message)s",datefmt="%H:%M:%S")
log=logging.getLogger("prices")

MANUAL={
    "COCA COLA CO":"KO","COCA-COLA CO":"KO","KROGER CO":"KR",
    "BK OF AMERICA CORP":"BAC","BANK AMERICA CORP":"BAC",
    "S&P GLOBAL INC":"SPGI","BLOCK H & R INC":"HRB",
    "PG&E CORP":"PCG","PG&amp;E CORP":"PCG",
    "KKR & CO L P DEL":"KKR","KKR &amp; CO L P DEL":"KKR",
    "CI&T INC/UNITED STATES-A":"CINT","CI&amp;T INC/UNITED STATES-A":"CINT",
    "AMAZON COM INC":"AMZN","DISNEY WALT CO":"DIS",
    "JEFFERIES FINANCIAL GROUP IN":"JEF","JEFFERIES FINANCIAL GROUP INC":"JEF",
    "TENCENT MUSIC ENTMT GROUP":"TME","ELEVANCE HEALTH INC FORMERLY":"ELV",
    "ELEVANCE HEALTH INC":"ELV",
    "FERGUSON ENTERPRISES INC (FERG)":"FERG","FERGUSON ENTERPRISES INC":"FERG",
    "WILLIS TOWERS WATSON PLC LTD":"WTW","WILLIS TOWERS WATSON PLC":"WTW",
    "TOPBUILD COR":"BLD","EAGLE MATLS INC":"EXP",
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
    "CENTESSA PHARMACEUTICALS PLC":"CNTA","CIDARA THERAPEUTICS INC":"CDTX",
    "CSG SYS INTL INC":"CSGS","KALVISTA PHARMACEUTICALS INC":"KALV",
    "VENTYX BIOSCIENCES INC":"VTYX","TERNS PHARMACEUTICALS INC":"TERN",
    "FLUSHING FINL CORP":"FFIC","ASSERTIO HOLDINGS INC":"ASRT",
    "STANDARD BIOTOOLS INC":"LAB","SYNCHRONOSS TECHNOLOGIES INC":"SNCR",
    "BITFARMS LTD/CANADA":"BITF","FERROVIAL SE":"FER",
    "RESTAURANT BRANDS INTL INC":"QSR","WESCO INTL INC":"WCC",
    "UNION PAC CORP":"UNP","T-MOBILE US INC":"TMUS","META PLATFORMS INC":"META",
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
    "EAST WEST BANCORP INC":"EWBC","CROCS INC":"CROX","PDD HOLDINGS INC":"PDD",
    "LULULEMON ATHLETICA INC":"LULU","DAILY JOURNAL CORP":"DJCO",
    "ON24 INC":"ONTF","ONESTREAM INC":"OS","PEAKSTONE REALTY TRUST":"PKST",
    "LIBERTY MEDIA CORP":"LSXMA","LIBERTY BROADBAND CORP":"LBRDK",
    "ASTRIA THERAPEUTICS INC":"ATXS","AVADEL PHARMACEUTICALS PLC":"AVDL",
}

def load_json(p):
    if not p.exists():return None
    with open(p,"r",encoding="utf-8") as f:return json.load(f)
def save_json(p,d):
    with open(p,"w",encoding="utf-8") as f:json.dump(d,f,ensure_ascii=False,indent=1)
def is_eq(c):
    if not c or len(c)<9:return True
    return c[6:8].isdigit()
def valid(t):
    if not t or t[0].isdigit():return False
    for s in FOREIGN:
        if t.upper().endswith(s.upper()):return False
    if '-P' in t.upper() or (t.upper().endswith('W') and len(t)>4):return False
    return True

def collect():
    stocks={}
    for af in sorted(ARCHIVE_DIR.glob("*.json"))[-2:]:
        log.info(f"  {af.name}")
        d=load_json(af)
        if not d:continue
        for gd in d.get("portfolios",{}).values():
            for h in gd.get("holdings",[]):
                c=h.get("cusip","").strip();n=h.get("name","").strip()
                if not n:continue
                if c and not is_eq(c):continue
                n=n.replace("&amp;","&").replace("&lt;","<").replace("&gt;",">")
                n=re.sub(r"<!\[CDATA\[|]]>","",n).strip()
                stocks[n.upper()]={"cusip":c,"name":n}
    return stocks

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
        if e<62:
            w=62-e;log.info(f"  Finnhub 대기 {w:.0f}초...");time.sleep(w)
        _fc=0;_ft=time.time()

def fh_search(name):
    if not FH_KEY:return None
    c=re.sub(r'\s*\([^)]*\)','',name).strip()
    c=re.sub(r'\s+(INC|CORP|CO|LTD|PLC|LP|LLC|CORPORATION|FORMERLY)\.?$','',c,flags=re.I)
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
    stocks=collect()
    log.info(f"고유 종목: {len(stocks)}개")
    if not stocks:return
    cache=load_json(CACHE_PATH) or {}
    # 외국 티커 정리
    for k in list(cache.keys()):
        if cache[k] and not valid(cache[k]):del cache[k]

    # ━━ 1단계: 전체 티커 매핑 ━━
    tmap={}
    need=[]
    for nk,info in stocks.items():
        c=info["cusip"];n=info["name"]
        nc=re.sub(r'\s*\([^)]*\)','',nk).strip()
        nc2=re.sub(r'\s+FORMERLY$','',nc,flags=re.I).strip()
        t=MANUAL.get(nk) or MANUAL.get(nc) or MANUAL.get(nc2) or MANUAL.get(n) or cache.get(nk) or cache.get(c)
        if t and valid(t):
            tmap[nk]=t
        else:
            need.append((nk,info))
    log.info(f"매핑: {len(tmap)}개 완료, {len(need)}개 검색 필요")

    # Yahoo 검색
    yf_found=0
    for nk,info in need:
        t=yf_search(info["name"])
        if t:
            tmap[nk]=t;cache[nk]=t
            if info["cusip"]:cache[info["cusip"]]=t
            yf_found+=1
        time.sleep(0.15)
    log.info(f"  Yahoo 검색: {yf_found}개")

    # Finnhub 검색 (Yahoo 실패분)
    still_need=[x for x in need if x[0] not in tmap]
    if still_need and FH_KEY:
        fh_found=0
        for nk,info in still_need:
            t=fh_search(info["name"])
            if t:
                tmap[nk]=t;cache[nk]=t
                if info["cusip"]:cache[info["cusip"]]=t
                fh_found+=1
        log.info(f"  Finnhub 검색: {fh_found}개")
    save_json(CACHE_PATH,cache)

    # ━━ 2단계: Yahoo 가격 일괄 갱신 ━━
    uniq={};cusip_of={}
    for nk,t in tmap.items():
        c=stocks[nk]["cusip"]
        if t not in uniq:
            uniq[t]=nk;cusip_of[t]=c

    log.info(f"━━ Yahoo 가격 조회: {len(uniq)}개 ━━")
    prices={};yf_fail=[];ok=0
    for idx,(t,nk) in enumerate(uniq.items()):
        c=cusip_of[t];n=stocks.get(nk,{}).get("name",t)
        pd=yf_price(t)
        if pd:
            prices[c or nk]={"ticker":t,"name":n,**pd};ok+=1
        else:
            yf_fail.append((c,n,t))
        time.sleep(0.18)
        if(idx+1)%200==0:
            log.info(f"  {idx+1}/{len(uniq)} (✓{ok} ✗{len(yf_fail)})")
    log.info(f"Yahoo: ✓{ok}개, ✗{len(yf_fail)}개")

    # ━━ 3단계: Finnhub 보완 (Yahoo 실패분만) ━━
    final_fail=[]
    if yf_fail and FH_KEY:
        log.info(f"━━ Finnhub 보완: {len(yf_fail)}개 ━━")
        fh_ok=0
        for c,n,t in yf_fail:
            pd=fh_price(t)
            if pd:
                prices[c or n.upper()]={"ticker":t,"name":n,**pd};fh_ok+=1
            else:
                final_fail.append((c,n,t))
        log.info(f"Finnhub: ✓{fh_ok}개 복구")
    else:
        final_fail=yf_fail

    # 티커 없는 종목
    for nk,info in stocks.items():
        if nk not in tmap and info["cusip"] not in prices:
            final_fail.append((info["cusip"],info["name"],"티커없음"))

    total=len(prices)
    log.info(f"━━━ 최종: ✓{total}개 / {len(stocks)}개 ━━━")
    if final_fail:
        log.info(f"실패 ({len(final_fail)}개):")
        for c,n,t in final_fail[:50]:
            log.info(f"  ✗ {n} ({t})")

    save_json(PRICES_PATH,{"updated_at":datetime.utcnow().isoformat()+"Z","count":total,"prices":prices})
    log.info(f"저장 완료")

if __name__=="__main__":
    main()
