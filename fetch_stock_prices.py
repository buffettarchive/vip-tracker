#!/usr/bin/env python3
"""
fetch_stock_prices.py — 구루 포트폴리오 보유 종목의 현재가 + 52주 고저 수집

흐름:
  1. us_vips_archive/ 최신 파일에서 보유 종목 CUSIP 수집
  2. OpenFIGI API로 CUSIP → 티커 매핑 (캐시)
  3. FIGI 실패분은 Yahoo Finance 이름 검색으로 fallback
  4. Yahoo Finance로 현재가 / 52W High / 52W Low 조회
  5. docs/stock_prices.json으로 저장
"""

import json, time, logging, re
from datetime import datetime
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import HTTPError
from urllib.parse import quote_plus

ARCHIVE_DIR = Path("docs/us_vips_archive")
PRICES_PATH = Path("docs/stock_prices.json")
TICKER_CACHE_PATH = Path("docs/ticker_cache.json")

YF_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
FIGI_URL = "https://api.openfigi.com/v3/mapping"
FIGI_BATCH = 10

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S")
log = logging.getLogger("stock-prices")


def load_json(path):
    if not path.exists():
        return None
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)


def collect_unique_stocks():
    """아카이브 최신 파일에서 고유 종목 수집. {cusip: name}"""
    stocks = {}
    archive_files = sorted(ARCHIVE_DIR.glob("*.json"))
    if not archive_files:
        log.error("아카이브 파일 없음")
        return stocks
    for af in archive_files[-2:]:
        log.info(f"  종목 수집: {af.name}")
        data = load_json(af)
        if not data:
            continue
        for guru_data in data.get("portfolios", {}).values():
            for h in guru_data.get("holdings", []):
                cusip = h.get("cusip", "").strip()
                name = h.get("name", "").strip()
                if cusip and name:
                    stocks[cusip] = name
    return stocks


def figi_lookup(cusips):
    """OpenFIGI API로 CUSIP → 티커 매핑."""
    result = {}
    cusip_list = list(cusips)
    for i in range(0, len(cusip_list), FIGI_BATCH):
        batch = cusip_list[i:i + FIGI_BATCH]
        body = json.dumps([{"idType": "ID_CUSIP", "idValue": c} for c in batch]).encode()
        req = Request(FIGI_URL, data=body, headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
        })
        try:
            with urlopen(req, timeout=30) as resp:
                data = json.loads(resp.read())
            for j, item in enumerate(data):
                cusip = batch[j]
                if "data" in item and len(item["data"]) > 0:
                    ticker = item["data"][0].get("ticker", "")
                    if ticker:
                        result[cusip] = ticker
        except Exception as e:
            log.warning(f"  FIGI 배치 실패: {e}")
        if i + FIGI_BATCH < len(cusip_list):
            time.sleep(2.5)
    return result


def yf_search_ticker(name):
    """Yahoo Finance 검색 API로 종목명 → 티커 매핑."""
    clean = re.sub(r'\s+(INC|CORP|CO|LTD|PLC|LP|LLC|NV|SA|AG|SE)\.?$', '', name, flags=re.I).strip()
    query = quote_plus(clean)
    url = f"https://query1.finance.yahoo.com/v1/finance/search?q={query}&quotesCount=3&newsCount=0&listsCount=0"
    req = Request(url, headers={"User-Agent": YF_UA})
    try:
        with urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
        quotes = data.get("quotes", [])
        for q in quotes:
            # equity만 (ETF, 펀드 제외)
            qtype = q.get("quoteType", "")
            if qtype == "EQUITY":
                return q.get("symbol", "")
        # equity 없으면 첫 번째 결과
        if quotes:
            return quotes[0].get("symbol", "")
    except Exception:
        pass
    return None


def yf_get_price(ticker):
    """Yahoo Finance v8 chart API로 현재가 + 52주 고저 조회."""
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}?range=1y&interval=1wk&includePrePost=false"
    req = Request(url, headers={"User-Agent": YF_UA})
    try:
        with urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read())
        result = data.get("chart", {}).get("result", [])
        if not result:
            return None
        meta = result[0].get("meta", {})
        current = meta.get("regularMarketPrice", 0)
        closes = result[0].get("indicators", {}).get("quote", [{}])[0].get("close", [])
        closes = [c for c in closes if c is not None]
        if not closes:
            return None
        return {
            "current_price": round(current, 2),
            "week52_low": round(min(closes), 2),
            "week52_high": round(max(closes), 2),
        }
    except Exception:
        return None


def main():
    # 1. 고유 종목 수집
    stocks = collect_unique_stocks()
    log.info(f"고유 종목: {len(stocks)}개")
    if not stocks:
        log.error("수집된 종목 없음. 아카이브 파일을 확인하세요.")
        return

    # 2. 티커 캐시 로드
    ticker_cache = load_json(TICKER_CACHE_PATH) or {}
    uncached = {c: n for c, n in stocks.items() if not ticker_cache.get(c)}
    log.info(f"캐시된 티커: {len(ticker_cache)}개, 미캐시: {len(uncached)}개")

    # 3. 미캐시 CUSIP → OpenFIGI 매핑
    if uncached:
        log.info(f"OpenFIGI 조회 중... ({len(uncached)}개)")
        new_tickers = figi_lookup(uncached.keys())
        ticker_cache.update(new_tickers)
        log.info(f"  → FIGI: {len(new_tickers)}개 매핑 성공")

        # 4. FIGI 실패분 → Yahoo Finance 이름 검색 fallback
        still_missing = {c: n for c, n in uncached.items() if c not in ticker_cache}
        if still_missing:
            log.info(f"  Yahoo 이름 검색 fallback: {len(still_missing)}개")
            yf_found = 0
            for idx, (cusip, name) in enumerate(still_missing.items()):
                ticker = yf_search_ticker(name)
                if ticker:
                    ticker_cache[cusip] = ticker
                    yf_found += 1
                time.sleep(0.4)
                if (idx + 1) % 50 == 0:
                    log.info(f"    검색 진행: {idx+1}/{len(still_missing)} (✓{yf_found})")
            log.info(f"  → Yahoo 검색: {yf_found}개 추가 매핑")

        save_json(TICKER_CACHE_PATH, ticker_cache)
        log.info(f"  총 캐시: {len(ticker_cache)}개")

    # 5. 현재가 조회
    unique_tickers = {}
    for cusip, name in stocks.items():
        ticker = ticker_cache.get(cusip)
        if ticker:
            unique_tickers[ticker] = cusip

    log.info(f"가격 조회 대상: {len(unique_tickers)}개 티커")
    prices = {}
    success = 0
    failed = 0

    for idx, (ticker, cusip) in enumerate(unique_tickers.items()):
        name = stocks.get(cusip, ticker)
        price_data = yf_get_price(ticker)
        if price_data:
            prices[cusip] = {"ticker": ticker, "name": name, **price_data}
            success += 1
        else:
            failed += 1

        time.sleep(0.3)

        if (idx + 1) % 50 == 0:
            log.info(f"  진행: {idx + 1}/{len(unique_tickers)} (✓{success} ✗{failed})")

    log.info(f"가격 조회 완료: ✓{success}개 성공, ✗{failed}개 실패")

    # 6. 저장
    output = {
        "updated_at": datetime.utcnow().isoformat() + "Z",
        "count": len(prices),
        "prices": prices,
    }
    save_json(PRICES_PATH, output)
    log.info(f"저장: {PRICES_PATH} ({len(prices)}개 종목)")


if __name__ == "__main__":
    main()
