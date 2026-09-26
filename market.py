"""Market side of the board: 1-year price history from Yahoo's public chart endpoint, shares outstanding from the
filing's cover page (dei), so every company gets market cap, enterprise value and price return next to its filings.
Failures fall back to the last saved docs/market.json so a blocked request never blanks the page."""
import json, os, time, urllib.request, datetime as dt

UA = "Mozilla/5.0"   # the bare token passes; a full browser string draws 429s
ADR_RATIO = {"TSM": 5}   # ordinary shares per listed ADS; every other foreign name here lists 1:1

def prices(ticker):
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}?range=1y&interval=1d"
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    for attempt in range(4):
        try:
            with urllib.request.urlopen(req, timeout=30) as r: d = json.load(r)["chart"]["result"][0]
            break
        except urllib.error.HTTPError as e:
            if e.code == 429 and attempt < 3: time.sleep(5 * (attempt + 1)); continue
            raise
    closes = [(t, c) for t, c in zip(d["timestamp"], d["indicators"]["quote"][0]["close"]) if c]
    if len(closes) < 60: raise ValueError("too few closes")
    last_t, last = closes[-1]; first = closes[0][1]
    q = next((c for t, c in reversed(closes) if t <= last_t - 91 * 86400), None)
    return {"price": last, "date": dt.datetime.fromtimestamp(last_t, dt.timezone.utc).date().isoformat(), "ret_1y": last / first - 1,
            "ret_3m": last / q - 1 if q else None, "high_1y": max(c for _, c in closes), "low_1y": min(c for _, c in closes)}

def shares_outstanding(cf):
    """Cover-page count when the API carries it (share classes at the latest date summed: Alphabet, Meta, Dell report per class);
    otherwise the balance-sheet count, otherwise the latest quarter's diluted weighted average."""
    def latest_sum(rows):
        rows = [r for r in rows if r.get("form", "").startswith(("10", "20"))] or rows
        latest = max(r["end"] for r in rows)
        return float(sum({r["val"] for r in rows if r["end"] == latest})), latest
    dei = cf["facts"].get("dei", {}); gaap = cf["facts"].get("us-gaap", {})
    for src, tag in ((dei, "EntityCommonStockSharesOutstanding"), (gaap, "CommonStockSharesOutstanding")):
        try: return latest_sum(src[tag]["units"]["shares"])[0]
        except (KeyError, ValueError): pass
    try:
        rows = [r for r in gaap["WeightedAverageNumberOfDilutedSharesOutstanding"]["units"]["shares"] if r.get("start") and 80 <= (dt.date.fromisoformat(r["end"]) - dt.date.fromisoformat(r["start"])).days <= 100]
        return float(max(rows, key=lambda r: r["end"])["val"])
    except (KeyError, ValueError): return None

def market_for(companies, facts_by_ticker, out_path):
    prev = {}
    if os.path.exists(out_path):
        try: prev = json.load(open(out_path))
        except Exception: prev = {}
    out = {}
    for c in companies:
        t = c["ticker"]
        try:
            p = prices(t); time.sleep(1.0)
        except Exception as e:
            if t in prev: out[t] = dict(prev[t], stale=True); continue
            out[t] = {"error": str(e)[:80]}; continue
        sh = shares_outstanding(facts_by_ticker[t])
        mcap = p["price"] * sh / ADR_RATIO.get(t, 1) if sh else None
        out[t] = dict(p, shares=sh, mcap=mcap, stale=False)
    json.dump(out, open(out_path, "w"), indent=1)
    return out
