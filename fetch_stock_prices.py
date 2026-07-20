#!/usr/bin/env python3
"""
fetch_stock_prices.py v7 — yfinance 배치 다운로드 방식

1. 아카이브에서 종목명+CUSIP 수집
2. 티커 매핑: 캐시 → 수동매핑 → Yahoo 검색
3. yfinance.download()로 전체 배치 다운로드 (한번에 수백개)
4. stock_prices.json 저장
"""

import json, time, logging, re, sys
from datetime import datetime
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.parse import quote_plus

ARCHIVE_DIR = Path("docs/us_vips_archive")
PRICES_PATH = Path("docs/stock_prices.json")
TICKER_CACHE_PATH = Path("docs/ticker_cache.json")

YF_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S")
log = logging.getLogger("stock-prices")

MANUAL = {
    "COCA COLA CO":"KO","COCA-COLA CO":"KO","KROGER CO":"KR",
    "BK OF AMERICA CORP":"BAC","BANK AMERICA CORP":"BAC",
    "S&P GLOBAL INC":"SPGI","BLOCK H & R INC":"HRB",
    "PG&E CORP":"PCG","PG&amp;E CORP":"PCG",
    "KKR & CO L P DEL":"KKR","KKR &amp; CO L P DEL":"KKR",
    "CI&T INC/UNITED STATES-A":"CINT","CI&amp;T INC/UNITED STATES-A":"CINT",
    "AMAZON COM INC":"AMZN","DISNEY WALT CO":"DIS","WALT DISNEY CO":"DIS",
    "JEFFERIES FINANCIAL GROUP IN":"JEF","JEFFERIES FINANCIAL GROUP INC":"JEF",
    "TENCENT MUSIC ENTMT GROUP":"TME","ELEVANCE HEALTH INC FORMERLY":"ELV",
    "FERGUSON ENTERPRISES INC (FERG)":"FERG","FERGUSON ENTERPRISES INC":"FERG",
    "WILLIS TOWERS WATSON PLC LTD":"WTW","WILLIS TOWERS WATSON PLC":"WTW",
    "TOPBUILD COR":"BLD","EAGLE MATLS INC":"EXP",
    "SUN CTRY AIRLS HLDGS INC":"SNCY","MIDWESTONE FINL GROUP INC NE":"MOFG",
    "ERMENEGILDO ZEGNA N V":"ZGN","CENTRAIS ELET BRAS SA":"EBR",
    "GRUPO AEROMEXICO SAB DE CV":"AEROMEX.MX",
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
}

FOREIGN_SUFFIXES = {'.SW','.MI','.MX','.L','.PA','.DE','.HK','.TO','.AX','.AS','.F'}


def load_json(path):
    if not path.exists(): return None
    with open(path,"r",encoding="utf-8") as f: return json.load(f)

def save_json(path, data):
    with open(path,"w",encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)


def is_equity_cusip(cusip):
    if not cusip or len(cusip) < 9: return True
    return cusip[6:8].isdigit()

def is_valid_us(t):
    if not t: return False
    if t[0].isdigit(): return False
    if t.upper().endswith('W') and len(t) > 4: return False
    for sfx in FOREIGN_SUFFIXES:
        if t.upper().endswith(sfx.upper()): return False
    if '-P' in t.upper(): return False
    return True


def collect_stocks():
    stocks = {}
    for af in sorted(ARCHIVE_DIR.glob("*.json"))[-2:]:
        log.info(f"  종목 수집: {af.name}")
        data = load_json(af)
        if not data: continue
        for gd in data.get("portfolios",{}).values():
            for h in gd.get("holdings",[]):
                cusip = h.get("cusip","").strip()
                name = h.get("name","").strip()
                if not name: continue
                if cusip and not is_equity_cusip(cusip): continue
                name = name.replace("&amp;","&").replace("&lt;","<").replace("&gt;",">")
                name = re.sub(r"<!\[CDATA\[|]]>","",name).strip()
                stocks[name.upper()] = {"cusip":cusip, "name":name}
    return stocks


def yf_search(name):
    variants = [name]
    n = re.sub(r'\s*\([^)]*\)','',name).strip()
    n = re.sub(r'\s+FORMERLY$','',n,flags=re.I).strip()
    if n != name: variants.append(n)
    c = re.sub(r'\s+(INC|CORP|CO|LTD|PLC|LP|LLC|NV|SA|AG|SE|SWITZ|CORPORATION|HLDGS|HOLDINGS|GROUP)\.?$','',n,flags=re.I)
    c = re.sub(r'\s+(INC|CORP|CO|LTD)\.?$','',c,flags=re.I).strip()
    if c != n: variants.append(c)
    if '&' in c: variants.append(c.replace('&','AND'))
    words = c.split()
    if len(words) >= 3: variants.append(" ".join(words[:2]))

    for q in variants:
        url = f"https://query1.finance.yahoo.com/v1/finance/search?q={quote_plus(q)}&quotesCount=5&newsCount=0&listsCount=0"
        try:
            req = Request(url, headers={"User-Agent":YF_UA})
            with urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read())
            us_ex = {"NYQ","NMS","NGM","NAS","PCX","ASE","BTS","NYS","OPR","NCM"}
            for qt in data.get("quotes",[]):
                sym = qt.get("symbol","")
                if qt.get("quoteType")=="EQUITY" and qt.get("exchange","") in us_ex and is_valid_us(sym):
                    return sym
            for qt in data.get("quotes",[]):
                sym = qt.get("symbol","")
                if qt.get("quoteType")=="EQUITY" and is_valid_us(sym) and "." not in sym:
                    return sym
        except Exception:
            pass
        time.sleep(0.3)
    return None


def main():
    try:
        import yfinance as yf
    except ImportError:
        log.error("yfinance 미설치. pip install yfinance 실행 필요")
        return

    stocks = collect_stocks()
    log.info(f"고유 종목: {len(stocks)}개")
    if not stocks: return

    # ── 1단계: 티커 매핑 ──
    cache = load_json(TICKER_CACHE_PATH) or {}
    ticker_map = {}  # name_key → ticker
    unmapped = []

    for name_key, info in stocks.items():
        cusip = info["cusip"]
        name = info["name"]
        # 수동 → 캐시 → CUSIP캐시
        t = MANUAL.get(name_key) or MANUAL.get(name) or cache.get(name_key) or cache.get(cusip)
        if t and is_valid_us(t):
            ticker_map[name_key] = t
        else:
            unmapped.append((name_key, info))

    log.info(f"매핑 완료: {len(ticker_map)}개, 미매핑: {len(unmapped)}개")

    # 미매핑 → Yahoo 검색
    if unmapped:
        log.info(f"Yahoo 검색 중... ({len(unmapped)}개)")
        found = 0
        for idx, (name_key, info) in enumerate(unmapped):
            t = yf_search(info["name"])
            if t:
                ticker_map[name_key] = t
                cache[name_key] = t
                if info["cusip"]: cache[info["cusip"]] = t
                found += 1
            time.sleep(0.2)
            if (idx+1) % 50 == 0:
                log.info(f"  진행: {idx+1}/{len(unmapped)} (✓{found})")
        log.info(f"  → {found}개 매핑 성공")
        save_json(TICKER_CACHE_PATH, cache)

    # ── 2단계: yfinance 배치 다운로드 ──
    all_tickers = list(set(ticker_map.values()))
    log.info(f"가격 다운로드: {len(all_tickers)}개 티커 (yfinance 배치)")

    # 외국 티커 제거 (배치 오류 방지)
    us_tickers = [t for t in all_tickers if "." not in t and is_valid_us(t)]
    foreign = len(all_tickers) - len(us_tickers)
    if foreign:
        log.info(f"  외국/무효 티커 {foreign}개 제외")
    all_tickers = us_tickers

    BATCH = 200
    price_data = {}

    for i in range(0, len(all_tickers), BATCH):
        batch = all_tickers[i:i+BATCH]
        log.info(f"  배치 {i//BATCH+1}/{(len(all_tickers)-1)//BATCH+1}: {len(batch)}개")
        try:
            df = yf.download(
                batch, period="1y", interval="1wk",
                group_by="ticker", progress=False,
                auto_adjust=True, threads=True
            )
            if df.empty:
                log.warning(f"  배치 빈 결과")
                continue

            for ticker in batch:
                try:
                    if len(batch) == 1:
                        closes = df["Close"].dropna()
                    else:
                        if ticker not in df.columns.get_level_values(0):
                            continue
                        closes = df[ticker]["Close"].dropna()
                    if len(closes) == 0:
                        continue
                    price_data[ticker] = {
                        "current_price": round(float(closes.iloc[-1]), 2),
                        "week52_low": round(float(closes.min()), 2),
                        "week52_high": round(float(closes.max()), 2),
                    }
                except Exception:
                    continue
        except Exception as e:
            log.warning(f"  배치 실패: {e}")
            # 배치 실패 시 개별 다운로드 fallback
            for ticker in batch:
                try:
                    df2 = yf.download(ticker, period="1y", interval="1wk",
                                     progress=False, auto_adjust=True)
                    if not df2.empty and "Close" in df2.columns:
                        closes = df2["Close"].dropna()
                        if len(closes) > 0:
                            price_data[ticker] = {
                                "current_price": round(float(closes.iloc[-1]), 2),
                                "week52_low": round(float(closes.min()), 2),
                                "week52_high": round(float(closes.max()), 2),
                            }
                except Exception:
                    continue
                time.sleep(0.2)
        time.sleep(2)

    log.info(f"가격 수집: {len(price_data)}개 성공 / {len(all_tickers)}개 중")

    # ── 3단계: 결과 조합 ──
    prices = {}
    success = 0
    failed = []

    for name_key, info in stocks.items():
        cusip = info["cusip"]
        name = info["name"]
        ticker = ticker_map.get(name_key)

        if ticker and ticker in price_data:
            prices[cusip or name_key] = {
                "ticker": ticker,
                "name": name,
                **price_data[ticker]
            }
            success += 1
        else:
            failed.append((cusip, name, ticker or "N/A"))

    log.info(f"━━━ 최종: ✓{success}개 성공, ✗{len(failed)}개 실패 ━━━")

    if failed:
        log.info(f"실패 목록 ({len(failed)}개):")
        for cusip, name, ticker in failed[:60]:
            log.info(f"  ✗ {name} (ticker:{ticker})")
        if len(failed) > 60:
            log.info(f"  ... 외 {len(failed)-60}개")

    output = {"updated_at": datetime.utcnow().isoformat()+"Z", "count": success, "prices": prices}
    save_json(PRICES_PATH, output)
    log.info(f"저장: {PRICES_PATH} ({success}개)")


if __name__ == "__main__":
    main()
