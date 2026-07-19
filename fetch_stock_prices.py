#!/usr/bin/env python3
"""
fetch_stock_prices.py v4 — 누락 최소화: 다단계 Yahoo 검색 + 최종 실패 목록 출력
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

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S")
log = logging.getLogger("stock-prices")

def load_json(path):
    if not path.exists(): return None
    with open(path, "r", encoding="utf-8") as f: return json.load(f)

def save_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)

def collect_unique_stocks():
    stocks = {}
    archive_files = sorted(ARCHIVE_DIR.glob("*.json"))
    if not archive_files: return stocks
    for af in archive_files[-2:]:
        log.info(f"  종목 수집: {af.name}")
        data = load_json(af)
        if not data: continue
        for guru_data in data.get("portfolios", {}).values():
            for h in guru_data.get("holdings", []):
                cusip = h.get("cusip", "").strip()
                name = h.get("name", "").strip()
                if cusip and name:
                    stocks[cusip] = name
    return stocks

def figi_lookup(cusips):
    result = {}
    cusip_list = list(cusips)
    for i in range(0, len(cusip_list), FIGI_BATCH):
        batch = cusip_list[i:i + FIGI_BATCH]
        body = json.dumps([{"idType": "ID_CUSIP", "idValue": c} for c in batch]).encode()
        req = Request(FIGI_URL, data=body, headers={
            "Content-Type": "application/json", "Accept": "application/json",
        })
        try:
            with urlopen(req, timeout=30) as resp:
                data = json.loads(resp.read())
            for j, item in enumerate(data):
                if "data" in item and item["data"]:
                    ticker = item["data"][0].get("ticker", "")
                    if ticker: result[batch[j]] = ticker
        except Exception as e:
            log.warning(f"  FIGI 배치 실패: {e}")
        if i + FIGI_BATCH < len(cusip_list):
            time.sleep(2.5)
    return result


def clean_name_variants(name):
    """종목명에서 다양한 검색어 변형을 생성."""
    variants = []
    n = name.strip()
    # 원본
    variants.append(n)
    # 접미사 제거
    cleaned = re.sub(r'\s+(INC|CORP|CO|LTD|PLC|LP|LLC|NV|SA|AG|SE|SWITZ|CORPORATION|HLDGS|HOLDINGS|GROUP)\.?$', '', n, flags=re.I)
    cleaned = re.sub(r'\s+(INC|CORP|CO|LTD|CORPORATION)\.?$', '', cleaned, flags=re.I).strip()
    if cleaned != n: variants.append(cleaned)
    # CLASS/CL 제거
    no_class = re.sub(r'\s+(CL|CLASS)\s*[A-Z]$', '', cleaned, flags=re.I).strip()
    if no_class != cleaned: variants.append(no_class)
    # MTN BE 등 제거
    no_mtn = re.sub(r'\s+MTN\s*BE$', '', no_class, flags=re.I).strip()
    if no_mtn != no_class: variants.append(no_mtn)
    # 첫 2단어만
    words = cleaned.split()
    if len(words) >= 2:
        variants.append(" ".join(words[:2]))
    # 첫 1단어
    if len(words) >= 1 and len(words[0]) >= 4:
        variants.append(words[0])
    return variants


def yf_search_ticker(name, try_all_variants=False):
    """Yahoo Finance 검색. try_all_variants=True이면 여러 변형으로 시도."""
    variants = clean_name_variants(name) if try_all_variants else [name]

    for query_name in variants:
        query = quote_plus(query_name)
        url = f"https://query1.finance.yahoo.com/v1/finance/search?q={query}&quotesCount=5&newsCount=0&listsCount=0"
        req = Request(url, headers={"User-Agent": YF_UA})
        try:
            with urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read())
            quotes = data.get("quotes", [])
            # 미국 EQUITY 우선
            us_exchanges = {"NYQ", "NMS", "NGM", "NYS", "NAS", "PCX", "ASE", "BTS", "OPR"}
            for q in quotes:
                if q.get("quoteType") == "EQUITY" and q.get("exchange", "") in us_exchanges:
                    return q.get("symbol", "")
            for q in quotes:
                if q.get("quoteType") == "EQUITY":
                    return q.get("symbol", "")
            if quotes and quotes[0].get("symbol"):
                return quotes[0]["symbol"]
        except Exception:
            pass
        time.sleep(0.3)

    return None


def yf_get_price(ticker):
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}?range=1y&interval=1wk&includePrePost=false"
    req = Request(url, headers={"User-Agent": YF_UA})
    try:
        with urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read())
        result = data.get("chart", {}).get("result", [])
        if not result: return None
        meta = result[0].get("meta", {})
        current = meta.get("regularMarketPrice", 0)
        if not current: return None
        closes = result[0].get("indicators", {}).get("quote", [{}])[0].get("close", [])
        closes = [c for c in closes if c is not None]
        if not closes: return None
        return {
            "current_price": round(current, 2),
            "week52_low": round(min(closes), 2),
            "week52_high": round(max(closes), 2),
        }
    except Exception:
        return None


def main():
    stocks = collect_unique_stocks()
    log.info(f"고유 종목: {len(stocks)}개")
    if not stocks: return

    ticker_cache = load_json(TICKER_CACHE_PATH) or {}
    uncached = {c: n for c, n in stocks.items() if not ticker_cache.get(c)}
    log.info(f"캐시된 티커: {len(ticker_cache) - len(uncached)}개, 미캐시: {len(uncached)}개")

    # ── 1단계: OpenFIGI ──
    if uncached:
        log.info(f"OpenFIGI 조회 중... ({len(uncached)}개)")
        new_tickers = figi_lookup(uncached.keys())
        ticker_cache.update(new_tickers)
        log.info(f"  → FIGI: {len(new_tickers)}개 성공")

        # ── 2단계: FIGI 실패 → Yahoo 이름 검색 (다단계 변형) ──
        still_missing = {c: n for c, n in uncached.items() if not ticker_cache.get(c)}
        if still_missing:
            log.info(f"  Yahoo 이름 검색: {len(still_missing)}개")
            yf_found = 0
            for idx, (cusip, name) in enumerate(still_missing.items()):
                ticker = yf_search_ticker(name, try_all_variants=True)
                if ticker:
                    ticker_cache[cusip] = ticker
                    yf_found += 1
                time.sleep(0.2)
                if (idx + 1) % 50 == 0:
                    log.info(f"    진행: {idx+1}/{len(still_missing)} (✓{yf_found})")
            log.info(f"  → Yahoo: {yf_found}개 추가 매핑")

        save_json(TICKER_CACHE_PATH, ticker_cache)

    # ── 2.5단계: 이전 실행에서 가격 실패했던 티커 캐시 삭제 (재검색 유도) ──
    old_prices = load_json(PRICES_PATH) or {}
    old_price_cusips = set((old_prices.get("prices") or {}).keys())
    stale_count = 0
    for cusip in list(ticker_cache.keys()):
        if cusip in stocks and cusip not in old_price_cusips and ticker_cache.get(cusip):
            # 이 종목은 캐시에 티커가 있지만 이전에 가격 조회 실패 → 삭제해서 재시도
            del ticker_cache[cusip]
            stale_count += 1
    if stale_count:
        log.info(f"이전 실패 캐시 {stale_count}개 삭제 → 재검색 대상")
        # 재검색
        retry_missing = {c: n for c, n in stocks.items() if not ticker_cache.get(c)}
        if retry_missing:
            log.info(f"  Yahoo 재검색: {len(retry_missing)}개")
            rf = 0
            for cusip, name in retry_missing.items():
                ticker = yf_search_ticker(name, try_all_variants=True)
                if ticker:
                    ticker_cache[cusip] = ticker
                    rf += 1
                time.sleep(0.3)
            log.info(f"  → {rf}개 매핑 성공")
            save_json(TICKER_CACHE_PATH, ticker_cache)

    # ── 3단계: 가격 조회 ──
    unique_tickers = {}
    for cusip, name in stocks.items():
        ticker = ticker_cache.get(cusip)
        if ticker:
            unique_tickers[ticker] = cusip

    log.info(f"가격 조회: {len(unique_tickers)}개 티커")
    prices = {}
    failed_phase1 = []  # (cusip, name, old_ticker)
    success = 0

    for idx, (ticker, cusip) in enumerate(unique_tickers.items()):
        name = stocks.get(cusip, ticker)
        price_data = yf_get_price(ticker)
        if price_data:
            prices[cusip] = {"ticker": ticker, "name": name, **price_data}
            success += 1
        else:
            failed_phase1.append((cusip, name, ticker))
        time.sleep(0.3)
        if (idx + 1) % 100 == 0:
            log.info(f"  진행: {idx+1}/{len(unique_tickers)} (✓{success} ✗{len(failed_phase1)})")

    log.info(f"1차: ✓{success}개, ✗{len(failed_phase1)}개 실패")

    # ── 4단계: 실패 → Yahoo 이름검색으로 티커 교정 후 재시도 ──
    still_failed = []
    if failed_phase1:
        log.info(f"실패 종목 재검색... ({len(failed_phase1)}개)")
        rescued = 0
        for idx, (cusip, name, old_ticker) in enumerate(failed_phase1):
            new_ticker = yf_search_ticker(name, try_all_variants=True)
            time.sleep(0.3)
            if new_ticker:
                price_data = yf_get_price(new_ticker)
                time.sleep(0.3)
                if price_data:
                    ticker_cache[cusip] = new_ticker
                    prices[cusip] = {"ticker": new_ticker, "name": name, **price_data}
                    rescued += 1
                    continue
            still_failed.append((cusip, name, old_ticker))
            if (idx + 1) % 50 == 0:
                log.info(f"    진행: {idx+1}/{len(failed_phase1)} (복구 {rescued})")

        if rescued:
            save_json(TICKER_CACHE_PATH, ticker_cache)
        log.info(f"  → {rescued}개 복구")

    # ── 5단계: 티커 없는 종목도 Yahoo 검색으로 마지막 시도 ──
    no_ticker = {c: n for c, n in stocks.items() if not ticker_cache.get(c) and c not in prices}
    if no_ticker:
        log.info(f"티커 미매핑 종목 최종 시도: {len(no_ticker)}개")
        last_found = 0
        for cusip, name in no_ticker.items():
            ticker = yf_search_ticker(name, try_all_variants=True)
            time.sleep(0.3)
            if ticker:
                price_data = yf_get_price(ticker)
                time.sleep(0.3)
                if price_data:
                    ticker_cache[cusip] = ticker
                    prices[cusip] = {"ticker": ticker, "name": name, **price_data}
                    last_found += 1
                    continue
            still_failed.append((cusip, name, ""))
        if last_found:
            save_json(TICKER_CACHE_PATH, ticker_cache)
            log.info(f"  → {last_found}개 추가 복구")

    # ── 최종 결과 ──
    total_failed = len(stocks) - len(prices)
    log.info(f"━━━ 최종: ✓{len(prices)}개 성공, ✗{total_failed}개 실패 ━━━")

    if still_failed:
        log.info(f"실패 종목 목록 ({len(still_failed)}개):")
        for cusip, name, ticker in still_failed[:50]:
            log.info(f"  ✗ {name} (CUSIP:{cusip}, ticker:{ticker or 'N/A'})")
        if len(still_failed) > 50:
            log.info(f"  ... 외 {len(still_failed)-50}개")

    output = {
        "updated_at": datetime.utcnow().isoformat() + "Z",
        "count": len(prices),
        "prices": prices,
    }
    save_json(PRICES_PATH, output)
    log.info(f"저장: {PRICES_PATH} ({len(prices)}개 종목)")


if __name__ == "__main__":
    main()
