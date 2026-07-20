#!/usr/bin/env python3
"""
fetch_stock_prices.py v5 — 외국 티커 제거 + 미국 전용 필터 강화
"""

import json, time, logging, re
from datetime import datetime
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.parse import quote_plus

ARCHIVE_DIR = Path("docs/us_vips_archive")
PRICES_PATH = Path("docs/stock_prices.json")
TICKER_CACHE_PATH = Path("docs/ticker_cache.json")

YF_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
FIGI_URL = "https://api.openfigi.com/v3/mapping"
FIGI_BATCH = 10

# 외국 거래소 접미사
FOREIGN_SUFFIXES = {'.SW','.MI','.MX','.L','.PA','.DE','.HK','.TO','.AX','.AS',
    '.MC','.BR','.SA','.CO','.IS','.TA','.VI','.ST','.OL','.HE','.WA','.PR',
    '.KL','.SI','.TW','.KS','.KQ','.NS','.BO','.JK','.BK','.NZ','.AT','.BA'}

# 자동 매핑 실패하는 대형주 수동 매핑 (종목명 → 티커)
MANUAL_TICKERS = {
    "COCA COLA CO": "KO",
    "KROGER CO": "KR",
    "S&P GLOBAL INC": "SPGI",
    "BLOCK H & R INC": "HRB",
    "TENCENT MUSIC ENTMT GROUP": "TME",
    "BK OF AMERICA CORP": "BAC",
    "JEFFERIES FINANCIAL GROUP IN": "JEF",
    "JEFFERIES FINANCIAL GROUP INC": "JEF",
    "COCA-COLA CO": "KO",
    "COCA COLA CO THE": "KO",
    "T-MOBILE US INC": "TMUS",
    "META PLATFORMS INC": "META",
    "CHARTER COMMUNICATIONS INC": "CHTR",
    "LIBERTY MEDIA CORP": "LSXMA",
    "LIBERTY BROADBAND CORP": "LBRDK",
    "BOOKING HOLDINGS INC": "BKNG",
    "UNITEDHEALTH GROUP INC": "UNH",
    "JOHNSON & JOHNSON": "JNJ",
    "PROCTER & GAMBLE CO": "PG",
    "ESTEE LAUDER COMPANIES INC": "EL",
    "CHARLES SCHWAB CORP": "SCHW",
}

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S")
log = logging.getLogger("stock-prices")

def load_json(path):
    if not path.exists(): return None
    with open(path,"r",encoding="utf-8") as f: return json.load(f)

def save_json(path, data):
    with open(path,"w",encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)


def is_valid_us_ticker(ticker):
    """미국 거래소 티커인지 검증."""
    if not ticker: return False
    t = ticker.upper()
    # 외국 거래소 접미사
    for sfx in FOREIGN_SUFFIXES:
        if t.endswith(sfx.upper()): return False
    # 숫자로 시작 (1GOOGL.MI 등)
    if t[0].isdigit(): return False
    # 우선주 (BML-PL 등) — BRK.A/BRK.B는 허용
    if '-P' in t or t.endswith('-PL') or t.endswith('-PH') or t.endswith('-PK'):
        return False
    return True


def collect_unique_stocks():
    stocks = {}
    archive_files = sorted(ARCHIVE_DIR.glob("*.json"))
    if not archive_files: return stocks
    for af in archive_files[-2:]:
        log.info(f"  종목 수집: {af.name}")
        data = load_json(af)
        if not data: continue
        for guru_data in data.get("portfolios",{}).values():
            for h in guru_data.get("holdings",[]):
                cusip = h.get("cusip","").strip()
                name = h.get("name","").strip()
                if cusip and name: stocks[cusip] = name
    return stocks


def figi_lookup(cusips):
    result = {}
    cusip_list = list(cusips)
    for i in range(0, len(cusip_list), FIGI_BATCH):
        batch = cusip_list[i:i+FIGI_BATCH]
        body = json.dumps([{"idType":"ID_CUSIP","idValue":c,"exchCode":"US"} for c in batch]).encode()
        req = Request(FIGI_URL, data=body, headers={
            "Content-Type":"application/json","Accept":"application/json",
        })
        try:
            with urlopen(req, timeout=30) as resp:
                data = json.loads(resp.read())
            for j, item in enumerate(data):
                if "data" in item and item["data"]:
                    ticker = item["data"][0].get("ticker","")
                    if ticker and is_valid_us_ticker(ticker):
                        result[batch[j]] = ticker
        except Exception as e:
            log.warning(f"  FIGI 배치 실패: {e}")
        if i+FIGI_BATCH < len(cusip_list):
            time.sleep(2.5)
    return result


def yf_search_ticker(name, try_all_variants=False):
    variants = _clean_name_variants(name) if try_all_variants else [name]
    for query_name in variants:
        query = quote_plus(query_name)
        url = f"https://query1.finance.yahoo.com/v1/finance/search?q={query}&quotesCount=10&newsCount=0&listsCount=0"
        req = Request(url, headers={"User-Agent":YF_UA})
        try:
            with urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read())
            quotes = data.get("quotes",[])
            # 미국 EQUITY만, 유효한 티커만
            us_ex = {"NYQ","NMS","NGM","NAS","PCX","ASE","BTS","NYS","OPR","NCM"}
            for q in quotes:
                sym = q.get("symbol","")
                if q.get("quoteType")=="EQUITY" and q.get("exchange","") in us_ex and is_valid_us_ticker(sym):
                    return sym
            # 미국 거래소 EQUITY (exchange 필터 완화)
            for q in quotes:
                sym = q.get("symbol","")
                if q.get("quoteType")=="EQUITY" and is_valid_us_ticker(sym) and "." not in sym:
                    return sym
        except Exception:
            pass
        time.sleep(0.3)
    return None


def _clean_name_variants(name):
    variants = []
    n = name.strip()
    variants.append(n)
    cleaned = re.sub(r'\s+(INC|CORP|CO|LTD|PLC|LP|LLC|NV|SA|AG|SE|SWITZ|CORPORATION|HLDGS|HOLDINGS|GROUP)\.?$','',n,flags=re.I)
    cleaned = re.sub(r'\s+(INC|CORP|CO|LTD|CORPORATION)\.?$','',cleaned,flags=re.I).strip()
    if cleaned != n: variants.append(cleaned)
    no_class = re.sub(r'\s+(CL|CLASS)\s*[A-Z]$','',cleaned,flags=re.I).strip()
    if no_class != cleaned: variants.append(no_class)
    no_mtn = re.sub(r'\s+MTN\s*BE$','',no_class,flags=re.I).strip()
    if no_mtn != no_class: variants.append(no_mtn)
    words = cleaned.split()
    if len(words) >= 2: variants.append(" ".join(words[:2]))
    if len(words) >= 1 and len(words[0]) >= 4: variants.append(words[0])
    return variants


def yf_get_price(ticker):
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}?range=1y&interval=1wk&includePrePost=false"
    req = Request(url, headers={"User-Agent":YF_UA})
    try:
        with urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read())
        result = data.get("chart",{}).get("result",[])
        if not result: return None
        meta = result[0].get("meta",{})
        current = meta.get("regularMarketPrice",0)
        if not current: return None
        closes = result[0].get("indicators",{}).get("quote",[{}])[0].get("close",[])
        closes = [c for c in closes if c is not None]
        if not closes: return None
        return {
            "current_price": round(current,2),
            "week52_low": round(min(closes),2),
            "week52_high": round(max(closes),2),
        }
    except Exception:
        return None


def main():
    stocks = collect_unique_stocks()
    log.info(f"고유 종목: {len(stocks)}개")
    if not stocks: return

    ticker_cache = load_json(TICKER_CACHE_PATH) or {}

    # ── 0단계: 잘못된 외국 티커 캐시 정리 ──
    bad_tickers = 0
    for cusip in list(ticker_cache.keys()):
        t = ticker_cache[cusip]
        if t and not is_valid_us_ticker(t):
            del ticker_cache[cusip]
            bad_tickers += 1
    if bad_tickers:
        log.info(f"외국/잘못된 티커 {bad_tickers}개 캐시에서 제거")

    # 이전 실행에서 가격 실패했던 종목도 캐시 삭제
    old_prices = load_json(PRICES_PATH) or {}
    old_cusips = set((old_prices.get("prices") or {}).keys())
    stale = 0
    for cusip in list(ticker_cache.keys()):
        if cusip in stocks and cusip not in old_cusips and ticker_cache.get(cusip):
            del ticker_cache[cusip]
            stale += 1
    if stale:
        log.info(f"이전 가격실패 {stale}개 캐시에서 제거")

    # 수동 매핑 먼저 적용
    manual_applied = 0
    for cusip, name in stocks.items():
        if not ticker_cache.get(cusip):
            upper = name.upper().strip()
            if upper in MANUAL_TICKERS:
                ticker_cache[cusip] = MANUAL_TICKERS[upper]
                manual_applied += 1
    if manual_applied:
        log.info(f"수동 매핑: {manual_applied}개 적용")
        save_json(TICKER_CACHE_PATH, ticker_cache)

    uncached = {c: n for c, n in stocks.items() if not ticker_cache.get(c)}
    log.info(f"유효 캐시: {len(stocks)-len(uncached)}개, 미캐시: {len(uncached)}개")

    # ── 1단계: OpenFIGI (exchCode=US 필터) ──
    if uncached:
        log.info(f"OpenFIGI 조회... ({len(uncached)}개)")
        new_tickers = figi_lookup(uncached.keys())
        ticker_cache.update(new_tickers)
        log.info(f"  → FIGI: {len(new_tickers)}개 성공")

        # ── 2단계: Yahoo 이름 검색 (다단계 변형) ──
        still_missing = {c:n for c,n in uncached.items() if not ticker_cache.get(c)}
        if still_missing:
            log.info(f"  Yahoo 검색: {len(still_missing)}개")
            yf_found = 0
            for idx,(cusip,name) in enumerate(still_missing.items()):
                ticker = yf_search_ticker(name, try_all_variants=True)
                if ticker:
                    ticker_cache[cusip] = ticker
                    yf_found += 1
                time.sleep(0.2)
                if (idx+1) % 50 == 0:
                    log.info(f"    진행: {idx+1}/{len(still_missing)} (✓{yf_found})")
            log.info(f"  → Yahoo: {yf_found}개 매핑")

        save_json(TICKER_CACHE_PATH, ticker_cache)

    # ── 3단계: 가격 조회 ──
    unique_tickers = {}
    for cusip in stocks:
        ticker = ticker_cache.get(cusip)
        if ticker: unique_tickers[ticker] = cusip

    log.info(f"가격 조회: {len(unique_tickers)}개 티커")
    prices = {}
    failed_items = []
    success = 0

    for idx,(ticker,cusip) in enumerate(unique_tickers.items()):
        name = stocks.get(cusip, ticker)
        price_data = yf_get_price(ticker)
        if price_data:
            prices[cusip] = {"ticker":ticker, "name":name, **price_data}
            success += 1
        else:
            failed_items.append((cusip, name, ticker))
        time.sleep(0.3)
        if (idx+1) % 100 == 0:
            log.info(f"  진행: {idx+1}/{len(unique_tickers)} (✓{success} ✗{len(failed_items)})")

    log.info(f"1차: ✓{success}개, ✗{len(failed_items)}개")

    # ── 4단계: 실패 → Yahoo 재검색 + 재시도 ──
    still_failed = []
    if failed_items:
        log.info(f"실패 종목 재검색... ({len(failed_items)}개)")
        rescued = 0
        for idx,(cusip,name,old_ticker) in enumerate(failed_items):
            new_ticker = yf_search_ticker(name, try_all_variants=True)
            time.sleep(0.3)
            if new_ticker and new_ticker != old_ticker:
                price_data = yf_get_price(new_ticker)
                time.sleep(0.3)
                if price_data:
                    ticker_cache[cusip] = new_ticker
                    prices[cusip] = {"ticker":new_ticker, "name":name, **price_data}
                    rescued += 1
                    continue
            still_failed.append((cusip,name,old_ticker))
            if (idx+1) % 50 == 0:
                log.info(f"    진행: {idx+1}/{len(failed_items)} (복구 {rescued})")
        if rescued: save_json(TICKER_CACHE_PATH, ticker_cache)
        log.info(f"  → {rescued}개 복구")

    # ── 5단계: 티커 아예 없는 종목 최종 시도 ──
    no_ticker = {c:n for c,n in stocks.items() if not ticker_cache.get(c) and c not in prices}
    if no_ticker:
        log.info(f"티커 미매핑 최종 시도: {len(no_ticker)}개")
        last_found = 0
        for cusip,name in no_ticker.items():
            ticker = yf_search_ticker(name, try_all_variants=True)
            time.sleep(0.3)
            if ticker:
                price_data = yf_get_price(ticker)
                time.sleep(0.3)
                if price_data:
                    ticker_cache[cusip] = ticker
                    prices[cusip] = {"ticker":ticker, "name":name, **price_data}
                    last_found += 1
                    continue
            still_failed.append((cusip,name,""))
        if last_found:
            save_json(TICKER_CACHE_PATH, ticker_cache)
            log.info(f"  → {last_found}개 추가 복구")

    # ── 최종 결과 ──
    total = len(prices)
    fails = len(stocks) - total
    log.info(f"━━━ 최종: ✓{total}개 성공, ✗{fails}개 실패 ━━━")
    if still_failed:
        log.info(f"실패 목록 ({len(still_failed)}개):")
        for cusip,name,ticker in still_failed[:80]:
            log.info(f"  ✗ {name} (CUSIP:{cusip} ticker:{ticker or 'N/A'})")
        if len(still_failed) > 80:
            log.info(f"  ... 외 {len(still_failed)-80}개")

    output = {"updated_at":datetime.utcnow().isoformat()+"Z","count":total,"prices":prices}
    save_json(PRICES_PATH, output)
    log.info(f"저장: {PRICES_PATH} ({total}개)")


if __name__ == "__main__":
    main()
