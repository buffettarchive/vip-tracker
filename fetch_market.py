"""
fetch_market.py — 시장 지표 수집 → docs/market.json
──────────────────────────────────────────────────────
KOSPI, KOSDAQ, S&P 500, USD/KRW, KOSPI 200 야간선물
Yahoo Finance API 사용 (무료, 인증 불필요)
GitHub Actions cron에서 5분마다 실행.
"""

import os, sys, json, time, base64
import datetime as dt
import requests

GH_TOKEN = os.environ["GH_TOKEN"]

GH_OWNER = "buffettarchive"
GH_REPO  = "vip-tracker"
GH_PATH  = "docs/market.json"
GH_BRANCH = "main"
GH_API   = "https://api.github.com"

s = requests.Session()
s.headers.update({"User-Agent": "Mozilla/5.0"})

GH_HEADERS = {
    "Authorization": f"Bearer {GH_TOKEN}",
    "Accept": "application/vnd.github+json",
    "X-GitHub-Api-Version": "2022-11-28",
}

TICKERS = {
    "KOSPI":    "^KS11",
    "KOSDAQ":   "^KQ11",
    "S&P 500":  "^GSPC",
    "USD/KRW":  "KRW=X",
    "야간선물":  "KM=F",
}


def fetch_quote(symbol):
    """Yahoo Finance에서 현재가, 전일종가, 변동률 가져오기."""
    try:
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
        params = {"interval": "1d", "range": "2d"}
        r = s.get(url, params=params, timeout=10)
        data = r.json()
        result = data["chart"]["result"][0]
        meta = result["meta"]
        price = meta.get("regularMarketPrice", 0)
        prev = meta.get("chartPreviousClose") or meta.get("previousClose", 0)
        change = price - prev if prev else 0
        change_pct = (change / prev * 100) if prev else 0
        return {
            "price": round(price, 2),
            "prev_close": round(prev, 2),
            "change": round(change, 2),
            "change_pct": round(change_pct, 2),
        }
    except Exception as e:
        print(f"[warn] {symbol}: {e}", file=sys.stderr)
        return None


def fetch_history(symbol, interval="1d", rng="1y"):
    """Yahoo Finance에서 OHLC를 가져와 캔들차트용 배열로 반환.
    interval: '1d'(일봉), '1mo'(월봉) 등. rng: '1y', 'max' 등."""
    try:
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
        params = {"interval": interval, "range": rng}
        r = s.get(url, params=params, timeout=10)
        data = r.json()
        result = data["chart"]["result"][0]
        ts = result.get("timestamp") or []
        q = result["indicators"]["quote"][0]
        opens = q.get("open", [])
        highs = q.get("high", [])
        lows = q.get("low", [])
        closes = q.get("close", [])
        candles = []
        for i, t in enumerate(ts):
            o, h, l, c = opens[i], highs[i], lows[i], closes[i]
            # null 값(휴장 등)은 건너뜀
            if None in (o, h, l, c):
                continue
            # Lightweight Charts는 time을 YYYY-MM-DD 문자열로 받음
            day = dt.datetime.fromtimestamp(t, dt.timezone.utc).strftime("%Y-%m-%d")
            candles.append({
                "time": day,
                "open": round(o, 2),
                "high": round(h, 2),
                "low": round(l, 2),
                "close": round(c, 2),
            })
        return candles
    except Exception as e:
        print(f"[warn] history {symbol} {interval}/{rng}: {e}", file=sys.stderr)
        return None


def aggregate_candles(daily, period="weekly"):
    """일봉 데이터를 주봉/월봉으로 집계."""
    if not daily:
        return []
    from collections import OrderedDict
    buckets = OrderedDict()
    for c in daily:
        d = c["time"]  # "YYYY-MM-DD"
        if period == "weekly":
            date = dt.date.fromisoformat(d)
            monday = date - dt.timedelta(days=date.weekday())
            key = monday.isoformat()
        else:  # monthly
            key = d[:7] + "-01"
        if key not in buckets:
            buckets[key] = {"time": key, "open": c["open"], "high": c["high"], "low": c["low"], "close": c["close"]}
        else:
            b = buckets[key]
            b["high"] = max(b["high"], c["high"])
            b["low"] = min(b["low"], c["low"])
            b["close"] = c["close"]
    return list(buckets.values())


def gh_get_file():
    url = f"{GH_API}/repos/{GH_OWNER}/{GH_REPO}/contents/{GH_PATH}?ref={GH_BRANCH}"
    r = s.get(url, headers=GH_HEADERS, timeout=15)
    if r.status_code == 200:
        return r.json()["sha"]
    return None


def gh_put_file(data, sha):
    url = f"{GH_API}/repos/{GH_OWNER}/{GH_REPO}/contents/{GH_PATH}"
    blob = json.dumps(data, ensure_ascii=False, indent=2)
    body = {
        "message": f"market: {dt.datetime.now(dt.UTC).strftime('%Y-%m-%dT%H:%M:%SZ')}",
        "content": base64.b64encode(blob.encode("utf-8")).decode("ascii"),
        "branch": GH_BRANCH,
    }
    if sha:
        body["sha"] = sha
    r = s.put(url, headers=GH_HEADERS, json=body, timeout=15)
    if r.status_code in (200, 201):
        print("[ok] market.json push 완료")
    else:
        print(f"[err] push 실패: {r.status_code}", file=sys.stderr)


def main():
    sha = gh_get_file()
    quotes = {}
    history = {}
    for name, symbol in TICKERS.items():
        q = fetch_quote(symbol)
        if q:
            quotes[name] = q
            print(f"  {name}: {q['price']} ({q['change_pct']:+.2f}%)")
        # 일봉만 Yahoo에서 가져오고, 주봉/월봉은 직접 집계
        daily = fetch_history(symbol, interval="1d", rng="2y")
        if daily:
            weekly = aggregate_candles(daily, "weekly")
            monthly = aggregate_candles(daily, "monthly")
            history[name] = {
                "daily": daily,
                "weekly": weekly,
                "monthly": monthly,
            }
            print(f"    history {name}: 일봉 {len(daily)} / 주봉 {len(weekly)} / 월봉 {len(monthly)}")
        time.sleep(0.3)

    if not quotes:
        print("[info] 데이터 없음")
        return

    payload = {
        "updated_at": dt.datetime.now(dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "quotes": quotes,
        "history": history,
    }
    gh_put_file(payload, sha)


if __name__ == "__main__":
    main()
