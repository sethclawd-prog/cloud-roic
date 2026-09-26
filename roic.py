#!/usr/bin/env python3
"""Cloud ROIC board: every hyperscaler, neocloud, data-centre landlord and AI-silicon vendor's SEC filings,
pulled from EDGAR's XBRL API, turned into trailing-twelve-month ROIC, capex intensity and growth, by layer.

Runs daily in GitHub Actions (see .github/workflows/refresh.yml); writes docs/data.json and docs/index.html.
Only the standard library. EDGAR asks for a descriptive User-Agent with a contact address (EDGAR_UA env).

    python3 roic.py                # fetch + build
    EDGAR_CACHE=/tmp/edgar python3 roic.py   # reuse cached companyfacts JSON when present
"""
import json, os, sys, time, urllib.request, datetime as dt
import market
from collections import defaultdict

UA = os.environ.get("EDGAR_UA", "cloud-roic (github.com/sethclawd-prog/cloud-roic) research@example.com")
CACHE = os.environ.get("EDGAR_CACHE")
HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "docs")

# layer → companies. Layers are the stack the returns are spread across; the order here is the order on the page.
COMPANIES = [
    ("Hyperscalers", [("MSFT", 789019, "Microsoft"), ("AMZN", 1018724, "Amazon"), ("GOOGL", 1652044, "Alphabet"), ("META", 1326801, "Meta"), ("ORCL", 1341439, "Oracle")]),
    ("Neoclouds", [("CRWV", 1769628, "CoreWeave"), ("NBIS", 1513845, "Nebius"), ("APLD", 1144879, "Applied Digital"), ("IREN", 1878848, "IREN"),
                   ("CORZ", 1839341, "Core Scientific"), ("WULF", 1083301, "TeraWulf"), ("CIFR", 1819989, "Cipher"), ("HUT", 1964789, "Hut 8"), ("DOCN", 1582961, "DigitalOcean")]),
    ("Data-centre landlords", [("EQIX", 1101239, "Equinix"), ("DLR", 1297996, "Digital Realty")]),
    ("AI silicon", [("NVDA", 1045810, "NVIDIA"), ("AVGO", 1730168, "Broadcom"), ("AMD", 2488, "AMD"), ("MRVL", 1835632, "Marvell"), ("ARM", 1973239, "Arm")]),
    ("Fabs & tools", [("TSM", 1046179, "TSMC"), ("INTC", 50863, "Intel"), ("ASML", 937966, "ASML"), ("AMAT", 6951, "Applied Materials"), ("LRCX", 707549, "Lam Research"), ("KLAC", 319201, "KLA")]),
    ("Memory & storage", [("MU", 723125, "Micron"), ("SNDK", 2023554, "Sandisk"), ("WDC", 106040, "Western Digital"), ("STX", 1137789, "Seagate")]),
    ("Networking & optics", [("ANET", 1596532, "Arista"), ("CSCO", 858877, "Cisco"), ("CIEN", 936395, "Ciena"), ("COHR", 820318, "Coherent"), ("LITE", 1633978, "Lumentum"), ("FN", 1408710, "Fabrinet"), ("CRDO", 1807794, "Credo"), ("ALAB", 1736297, "Astera Labs")]),
    ("Systems & power", [("DELL", 1571996, "Dell"), ("SMCI", 1375365, "Supermicro"), ("HPE", 1645590, "HPE"), ("VRT", 1674101, "Vertiv"), ("ETN", 1551182, "Eaton"), ("GEV", 1996810, "GE Vernova"), ("NVT", 1720635, "nVent")]),
]
# Foreign filers report in their own currency; ratios are currency-free, dollar totals use these fixed rates (stated on the page).
FX = {"USD": 1.0, "TWD": 0.031, "EUR": 1.09, "GBP": 1.28, "JPY": 0.0067, "KRW": 0.00073}

# Concept → ordered fallbacks. "flow" concepts are durations (income statement / cash flow); "stock" are instants (balance sheet).
FLOW = {
    "revenue": ["RevenueFromContractWithCustomerExcludingAssessedTax", "Revenues", "SalesRevenueNet", "RevenueFromContractWithCustomerIncludingAssessedTax", "Revenue"],
    "opinc": ["OperatingIncomeLoss", "ProfitLossFromOperatingActivities"],
    "pretax": ["IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest", "IncomeLossFromContinuingOperationsBeforeIncomeTaxesMinorityInterestAndIncomeLossFromEquityMethodInvestments", "IncomeLossFromContinuingOperationsBeforeIncomeTaxesDomestic", "ProfitLossBeforeTax"],
    "tax": ["IncomeTaxExpenseBenefit", "IncomeTaxExpenseContinuingOperations"],
    "netinc": ["NetIncomeLoss", "ProfitLoss"],
    "capex": ["PaymentsToAcquirePropertyPlantAndEquipment", "PaymentsToAcquireProductiveAssets", "PaymentsToAcquireOtherPropertyPlantAndEquipment", "PaymentsToAcquireMachineryAndEquipment", "PaymentsForCapitalImprovements", "PaymentsToDevelopRealEstateAssets", "PaymentsToAcquireRealEstate", "PaymentsToAcquireMiningAssets", "PurchaseOfPropertyPlantAndEquipmentClassifiedAsInvestingActivities"],
    "da": ["DepreciationDepletionAndAmortization", "DepreciationAndAmortization", "DepreciationAmortizationAndAccretionNet", "DepreciationAmortizationAndOther", "Depreciation", "DepreciationAndAmortizationExcludingAmortizationOfDeferredFinancingCosts", "DepreciationAndAmortisationExpense"],
    "cfo": ["NetCashProvidedByUsedInOperatingActivities", "CashFlowsFromUsedInOperatingActivities"],
}
STOCK = {
    "assets": ["Assets"],
    "curliab": ["LiabilitiesCurrent", "CurrentLiabilities"],
    "equity": ["StockholdersEquity", "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest", "EquityAttributableToOwnersOfParent", "Equity"],
    "ltd": ["LongTermDebtNoncurrent", "LongTermNotesAndLoans", "LongTermNotesPayable", "LongTermDebtAndCapitalLeaseObligations", "LongTermDebt", "LongTermDebtAndFinanceLeasesNoncurrent", "SeniorLongTermNotes", "SeniorNotes", "DebtInstrumentCarryingAmount", "SecuredDebt", "UnsecuredDebt", "NotesPayable", "NoncurrentPortionOfNoncurrentBondsIssued", "LongtermBorrowings"],
    "ltd_cur": ["LongTermDebtCurrent", "LongTermDebtAndCapitalLeaseObligationsCurrent", "NotesPayableCurrent", "SeniorNotesCurrent", "DebtCurrent", "ShortTermBorrowings", "CurrentPortionOfLongtermBorrowings", "ShorttermBorrowings"],
    "oplease": ["OperatingLeaseLiabilityNoncurrent", "OperatingLeaseLiability", "NoncurrentLeaseLiabilities"],
    "finlease": ["FinanceLeaseLiabilityNoncurrent", "FinanceLeaseLiability"],
    "cash": ["CashAndCashEquivalentsAtCarryingValue", "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents", "CashAndCashEquivalents"],
    "sti": ["ShortTermInvestments", "MarketableSecuritiesCurrent", "AvailableForSaleSecuritiesDebtSecuritiesCurrent"],
    "ppe": ["PropertyPlantAndEquipmentNet", "RealEstateInvestmentPropertyNet", "PropertyPlantAndEquipment"],
}
FORMS = {"10-K", "10-Q", "10-K/A", "10-Q/A", "10-KT", "20-F", "20-F/A"}

def fetch(url, cache_name=None):
    if CACHE and cache_name:
        p = os.path.join(CACHE, cache_name)
        if os.path.exists(p): return json.load(open(p))
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Encoding": "gzip, deflate"})
    for attempt in range(4):
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                raw = r.read()
                if r.headers.get("Content-Encoding") == "gzip":
                    import gzip; raw = gzip.decompress(raw)
                data = json.loads(raw)
            break
        except Exception as e:
            if attempt == 3: raise
            time.sleep(2 + attempt * 3)
    time.sleep(0.15)   # EDGAR's fair-use ceiling is 10 requests a second
    if CACHE and cache_name:
        os.makedirs(CACHE, exist_ok=True); json.dump(data, open(os.path.join(CACHE, cache_name), "w"))
    return data

def days(a, b): return (dt.date.fromisoformat(b) - dt.date.fromisoformat(a)).days

SEEN_UNITS = set()
FACTS = {}
def series(facts, names, kind):
    """Union of every listed concept, keyed by period. Filers switch tags over the years, so the concept used most
    recently wins a period it shares with another; older periods come from whichever tag carried them."""
    per_tag = []
    for n in names:
        c = facts.get(n)
        if not c: continue
        unit = "USD" if "USD" in c["units"] else next((u for u in c["units"] if u in FX), None)
        if not unit: continue
        SEEN_UNITS.add(unit)
        units = c["units"][unit]
        rows = [r for r in units if r.get("form") in FORMS and r.get("val") is not None]
        if not rows: continue
        rows.sort(key=lambda r: (r["end"], r.get("filed", "")))
        out = {}
        for r in rows:
            if kind == "flow":
                if not r.get("start"): continue
                out[(r["start"], r["end"])] = float(r["val"]) * FX[unit]
            else:
                out[r["end"]] = float(r["val"]) * FX[unit]
        if out: per_tag.append((max(rows, key=lambda r: r["end"])["end"], n, out))
    if not per_tag: return None, {}
    per_tag.sort(key=lambda t: t[0], reverse=True)   # most recently used tag first
    merged = {}
    for _, n, out in per_tag:
        for k, v in out.items(): merged.setdefault(k, v)
    return "+".join(n for _, n, _ in per_tag), merged

def quarters(flow):
    """Discrete quarters from a duration series: reported ~3-month periods, plus the missing quarter inside every
    reported ~12-month period derived by subtraction (filers report Q4 only inside the annual figure)."""
    q = {end: v for (s, end), v in flow.items() if 80 <= days(s, end) <= 100}
    annual = {(s, e): v for (s, e), v in flow.items() if 350 <= days(s, e) <= 380}
    # also 6- and 9-month year-to-date figures let us derive quarters when a single quarter is not tagged
    ytd = {(s, e): v for (s, e), v in flow.items() if 170 <= days(s, e) <= 190 or 260 <= days(s, e) <= 280}
    def inner(s, e, v):
        # quarters that end inside (s, e], nearest to the three earlier quarter boundaries
        parts = [(end, val) for end, val in q.items() if s < end <= e]
        return parts
    changed = True
    while changed:
        changed = False
        for (s, e), v in list(ytd.items()) + list(annual.items()):
            parts = inner(s, e, v)
            n_expected = round(days(s, e) / 91)
            if len(parts) == n_expected - 1:
                covered = sum(val for _, val in parts)
                # the missing quarter is the one whose end is not in parts: either e itself or an earlier boundary
                ends = {end for end, _ in parts}
                if e not in ends:
                    q[e] = v - covered; changed = True
                else:
                    # missing an interior quarter: place it at the boundary ~91 days after the previous known end
                    known = sorted(ends)
                    cands = [s] + known
                    for a, b in zip(cands, cands[1:] + [e]):
                        if days(a, b) > 120:
                            mid = (dt.date.fromisoformat(a) + dt.timedelta(days=91)).isoformat()
                            q[mid] = v - covered; changed = True; break
    return dict(sorted(q.items()))

def ttm(q, at=None, annual=None):
    ends = sorted(q)
    if at: ends = [e for e in ends if e <= at]
    if len(ends) >= 4 and days(ends[-4], ends[-1]) <= 300 and (not at or days(ends[-1], at) <= 100): return sum(q[e] for e in ends[-4:])
    if annual:   # annual-only filers (20-F): the last fiscal year ending at or before `at`
        fy = sorted((e, v) for (s0, e), v in annual.items() if not at or e <= at)
        if fy and (not at or days(fy[-1][0], at) <= 400): return fy[-1][1]
    return None

def latest_stock(stock, at=None):
    ends = sorted(stock)
    if at: ends = [e for e in ends if e <= at]
    return (ends[-1], stock[ends[-1]]) if ends else (None, None)

def nearest_stock(stock, target, tol=45):
    best = None
    for e in stock:
        d = abs(days(e, target))
        if d <= tol and (best is None or d < best[0]): best = (d, e)
    return stock[best[1]] if best else None

def company(ticker, cik, name, layer):
    cf = fetch(f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json", f"{cik}.json")
    sub = fetch(f"https://data.sec.gov/submissions/CIK{cik:010d}.json", f"sub-{cik}.json")
    facts = dict(cf["facts"].get("ifrs-full", {})); facts.update(cf["facts"].get("us-gaap", {}))
    SEEN_UNITS.clear()
    used = {}
    flows, annuals = {}, {}
    for k, names in FLOW.items():
        tag, s = series(facts, names, "flow"); used[k] = tag; flows[k] = quarters(s) if s else {}
        annuals[k] = {ke: v for ke, v in s.items() if 350 <= days(ke[0], ke[1]) <= 380}
    stocks = {}
    for k, names in STOCK.items():
        tag, s = series(facts, names, "stock"); used[k] = tag; stocks[k] = s
    # latest quarter end that has revenue
    ends = sorted(flows["revenue"]) or sorted(e for (_, e) in annuals["revenue"])
    if not ends: return None
    asof = ends[-1]
    def T(k, at=None): return ttm(flows[k], at or asof, annuals[k])
    def S(k, at=None):
        e, v = latest_stock(stocks[k], at or asof); return v
    def invested(at):
        eq = nearest_stock(stocks["equity"], at);
        if eq is None: return None
        debt = sum(nearest_stock(stocks[k], at) or 0 for k in ("ltd", "ltd_cur", "oplease", "finlease"))
        cash = (nearest_stock(stocks["cash"], at) or 0) + (nearest_stock(stocks["sti"], at) or 0)
        return eq + debt - cash
    def nopat_at(at):
        pt = T("pretax", at); tx = T("tax", at); ebit = T("opinc", at)
        if ebit is None and pt is not None: ebit = pt; used["opinc_fallback"] = "pre-tax income"
        if ebit is None: return None, None
        rate = 0.21
        if pt and pt > 0 and tx is not None: rate = min(0.35, max(0.0, tx / pt))
        return ebit * (1 - rate), rate
    # quarterly history for charts: at every quarter end where TTM is computable
    hist = []
    for e in ends:
        n, rate = nopat_at(e); ic_now = invested(e)
        prev = (dt.date.fromisoformat(e) - dt.timedelta(days=365)).isoformat(); ic_prev = invested(prev)
        ic_avg = (ic_now + ic_prev) / 2 if ic_now is not None and ic_prev is not None else ic_now
        rev = T("revenue", e); capex = T("capex", e); da = T("da", e); op = T("opinc", e)
        if op is None: op = T("pretax", e)
        roic = n / ic_avg if n is not None and ic_avg and ic_avg > 0 else None
        debt = sum(nearest_stock(stocks[k], e) or 0 for k in ("ltd", "ltd_cur", "oplease", "finlease")); cash = (nearest_stock(stocks["cash"], e) or 0) + (nearest_stock(stocks["sti"], e) or 0)
        hist.append({"end": e, "revenue_ttm": rev, "opinc_ttm": op, "nopat_ttm": n, "invested": ic_now, "roic": roic, "debt": debt, "cash": cash,
                     "op_margin": op / rev if op is not None and rev else None,
                     "capex_ttm": capex, "da_ttm": da, "capex_intensity": capex / rev if capex and rev else None,
                     "revenue_q": flows["revenue"].get(e), "capex_q": flows["capex"].get(e)})
    hist = [h for h in hist if h["revenue_ttm"] is not None][-24:]
    latest = hist[-1] if hist else None
    prev_year = next((h for h in reversed(hist) if 350 <= days(h["end"], asof) <= 380), None)
    rec = sub["filings"]["recent"]
    filings = [{"form": rec["form"][i], "date": rec["filingDate"][i], "period": rec["reportDate"][i],
                "url": f"https://www.sec.gov/Archives/edgar/data/{cik}/{rec['accessionNumber'][i].replace('-', '')}/{rec['primaryDocument'][i]}"}
               for i in range(len(rec["form"])) if rec["form"][i] in FORMS][:3]
    FACTS[ticker] = cf
    return {
        "ticker": ticker, "cik": cik, "name": name, "layer": layer, "entity": cf.get("entityName"), "asof": asof,
        "fiscal_year_end": sub.get("fiscalYearEnd"), "edgar": f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={cik:010d}&type=10&dateb=&owner=include&count=40",
        "filings": filings, "tags": used,
        "latest": latest, "tax_rate": nopat_at(asof)[1],
        "revenue_growth": (latest["revenue_ttm"] / prev_year["revenue_ttm"] - 1) if latest and prev_year and prev_year["revenue_ttm"] else None,
        "capex_growth": (latest["capex_ttm"] / prev_year["capex_ttm"] - 1) if latest and prev_year and prev_year["capex_ttm"] else None,
        "op_margin": (latest["opinc_ttm"] / latest["revenue_ttm"]) if latest and latest["opinc_ttm"] is not None and latest["revenue_ttm"] else None,
        "capex_to_da": (latest["capex_ttm"] / latest["da_ttm"]) if latest and latest["capex_ttm"] and latest["da_ttm"] else None,
        "ppe": S("ppe"), "cfo_ttm": T("cfo"), "currency": next(iter(SEEN_UNITS - {"USD"}), "USD"),
        "nopat_growth": (latest["nopat_ttm"] / prev_year["nopat_ttm"] - 1) if latest and prev_year and latest["nopat_ttm"] and prev_year["nopat_ttm"] and prev_year["nopat_ttm"] > 0 else None,
        "op_margin_change": (latest["op_margin"] - prev_year["op_margin"]) if latest and prev_year and latest.get("op_margin") is not None and prev_year.get("op_margin") is not None else None,
        "stale": days(asof, dt.date.today().isoformat()) > 135,
        "history": hist,
    }

def write_insights(layers, rows):
    """Plain sentences derived from the numbers, rewritten on every refresh. No model, no adjectives the data cannot back."""
    def P(v, d=0):
        return "n/a" if v is None else (f"{v*100:+.{d}f}%" if v < 0 else f"{v*100:.{d}f}%")
    B = lambda v: "n/a" if v is None else (f"${v/1e12:.2f}T" if abs(v) >= 1e12 else f"${v/1e9:.0f}B")
    L = {l["layer"]: l for l in layers}; out = []
    ranked = sorted([l for l in layers if l["roic"] is not None], key=lambda l: -l["roic"])
    out.append("Returns by layer, best to worst: " + "; ".join(f"{l['layer']} {P(l['roic'])}" for l in ranked) + ".")
    h, n = L.get("Hyperscalers"), L.get("Neoclouds")
    if h and h["capex_to_da"]: out.append(f"Hyperscalers spent {B(h['capex_ttm'])} on capex in the trailing year ({P(h['capex_growth'])} year on year) against {B(h['revenue_ttm'])} of revenue, and still earn {P(h['roic'])} on invested capital. Capex runs {h['capex_to_da']:.1f}× depreciation, so the depreciation bill is still catching up with the spend.")
    if n and n["revenue_ttm"]: out.append(f"Neoclouds spent {B(n['capex_ttm'])}, {n['capex_ttm']/n['revenue_ttm']*100:.0f}% of their revenue, and earn {P(n['roic'])}: the layer is buying capacity ahead of returns.")
    cos = [r for r in rows if r["latest"]]
    SUP = ("AI silicon", "Fabs & tools", "Memory & storage", "Networking & optics", "Systems & power")
    sup = [r for r in cos if r["layer"] in SUP]
    top_growth = sorted([r for r in sup if r["revenue_growth"] is not None], key=lambda r: -r["revenue_growth"])[:5]
    if top_growth: out.append("Fastest-growing suppliers by trailing revenue: " + ", ".join(f"{r['name']} {P(r['revenue_growth'])}" for r in top_growth) + ".")
    margin_up = sorted([r for r in sup if r.get("op_margin_change") is not None], key=lambda r: -r["op_margin_change"])[:4]
    margin_dn = sorted([r for r in sup if r.get("op_margin_change") is not None], key=lambda r: r["op_margin_change"])[:3]
    if margin_up: out.append("Operating margin moved most. Up: " + ", ".join(f"{r['name']} {r['op_margin_change']*100:+.1f} pts to {P(r['op_margin'])}" for r in margin_up) + ". Down: " + ", ".join(f"{r['name']} {r['op_margin_change']*100:+.1f} pts to {P(r['op_margin'])}" for r in margin_dn) + ".")
    supl = [l for l in layers if l["layer"] in SUP]
    out.append("Where the supply chain earns it: " + "; ".join(f"{l['layer']} {P(l['roic'])} ROIC on {P(l['op_margin'])} margins, revenue {P(l['revenue_growth'])} y/y" for l in supl) + ".")
    levered = sorted([r for r in cos if r["layer"] == "Neoclouds" and r["latest"]["revenue_ttm"]], key=lambda r: -(r["latest"]["debt"] or 0) / r["latest"]["revenue_ttm"])[:4]
    if levered: out.append("Neocloud leverage, debt and leases over trailing revenue: " + ", ".join(f"{r['name']} {(r['latest']['debt'] or 0)/r['latest']['revenue_ttm']:.1f}×" for r in levered) + ".")
    intense = sorted([r for r in cos if r["latest"]["capex_intensity"] is not None], key=lambda r: -r["latest"]["capex_intensity"])[:5]
    out.append("Highest capex intensity: " + ", ".join(f"{r['name']} {r['latest']['capex_intensity']*100:.0f}% of revenue" for r in intense) + ".")
    priced = [r for r in cos if r.get("market", {}).get("ret_1y") is not None]
    def solid(r):   # profit growth off a real base: last year's NOPAT was at least 5% of revenue
        h = next((h for h in reversed(r["history"]) if 350 <= days(h["end"], r["asof"]) <= 380), None)
        return h and h["nopat_ttm"] and h["revenue_ttm"] and h["nopat_ttm"] / h["revenue_ttm"] >= 0.05
    lag = sorted([r for r in priced if r.get("nopat_growth") is not None and r["nopat_growth"] >= 0.15 and r["market"]["ret_1y"] < r["nopat_growth"] / 2 and solid(r)], key=lambda r: (1 + r["market"]["ret_1y"]) / (1 + r["nopat_growth"]))[:8]
    if lag: out.append("Price has not followed profit: NOPAT up but the shares lag by more than half of it over a year: " + ", ".join(f"{r['name']} (NOPAT {P(r['nopat_growth'])}, shares {P(r['market']['ret_1y'])}, EV/NOPAT {r['ev_nopat']:.0f}×)" if r.get("ev_nopat") else f"{r['name']} (NOPAT {P(r['nopat_growth'])}, shares {P(r['market']['ret_1y'])})" for r in lag) + ".")
    ahead = sorted([r for r in priced if r.get("ev_nopat") and r["market"]["ret_1y"] > 0.6 and (r.get("nopat_growth") is None or r["market"]["ret_1y"] > 2 * max(0, r["nopat_growth"]))], key=lambda r: -r["market"]["ret_1y"])[:8]
    if ahead: out.append("Price well ahead of profit: shares up more than twice NOPAT growth: " + ", ".join(f"{r['name']} (shares {P(r['market']['ret_1y'])}, NOPAT {P(r['nopat_growth'])}, EV/NOPAT {r['ev_nopat']:.0f}×)" for r in ahead) + ".")
    cheap = sorted([r for r in priced if r.get("ev_nopat") and r["latest"]["roic"] and r["latest"]["roic"] > 0.2 and r["ev_nopat"] < 20], key=lambda r: r["ev_nopat"])[:6]
    if cheap: out.append("High return, low multiple: ROIC above 20% at under 20× EV/NOPAT: " + ", ".join(f"{r['name']} ({P(r['latest']['roic'])} ROIC, {r['ev_nopat']:.0f}×)" for r in cheap) + ".")
    rich = sorted([r for r in priced if r.get("ev_nopat") and r["ev_nopat"] > 60], key=lambda r: -r["ev_nopat"])[:6]
    if rich: out.append("Priced for a lot: EV above 60× NOPAT: " + ", ".join(f"{r['name']} ({r['ev_nopat']:.0f}×, NOPAT {P(r['nopat_growth'])} y/y)" for r in rich) + ".")
    stale = [f"{r['name']} ({r['asof']})" for r in cos if r.get("stale")]
    if stale: out.append("Figures more than a quarter old, usually annual-only foreign filers: " + ", ".join(stale) + ".")
    return out

def build():
    rows, problems = [], []
    for layer, cos in COMPANIES:
        for ticker, cik, name in cos:
            try:
                r = company(ticker, cik, name, layer)
                if r: rows.append(r)
                else: problems.append(f"{ticker}: no revenue series")
            except Exception as e:
                problems.append(f"{ticker}: {type(e).__name__}: {e}")
    os.makedirs(OUT, exist_ok=True)
    mk = market.market_for(rows, FACTS, os.path.join(OUT, "market.json"))
    for r in rows:
        m = mk.get(r["ticker"], {}); L = r["latest"]
        r["market"] = m
        if m.get("mcap") and L:
            ev = m["mcap"] + (L["debt"] or 0) - (L["cash"] or 0)
            r["ev"] = ev
            r["ev_nopat"] = ev / L["nopat_ttm"] if L["nopat_ttm"] and L["nopat_ttm"] > 0 else None
            r["ev_revenue"] = ev / L["revenue_ttm"] if L["revenue_ttm"] else None
            r["price_gap"] = (m["ret_1y"] - r["nopat_growth"]) if r.get("nopat_growth") is not None and m.get("ret_1y") is not None else None
    layers = []
    for layer, _ in COMPANIES:
        members = [r for r in rows if r["layer"] == layer and r["latest"]]
        nopat = sum(r["latest"]["nopat_ttm"] or 0 for r in members if r["latest"]["roic"] is not None)
        ic = sum((r["latest"]["invested"] or 0) for r in members if r["latest"]["roic"] is not None)
        def year_ago(r, key):
            h = next((h for h in reversed(r["history"]) if 350 <= days(h["end"], r["asof"]) <= 380), None); return (h or {}).get(key)
        cap_now = sum(r["latest"]["capex_ttm"] or 0 for r in members if year_ago(r, "capex_ttm")); cap_prev = sum(year_ago(r, "capex_ttm") or 0 for r in members if year_ago(r, "capex_ttm"))
        rev_now = sum(r["latest"]["revenue_ttm"] or 0 for r in members if year_ago(r, "revenue_ttm")); rev_prev = sum(year_ago(r, "revenue_ttm") or 0 for r in members if year_ago(r, "revenue_ttm"))
        op_now = sum(r["latest"]["opinc_ttm"] or 0 for r in members); da = sum(r["latest"]["da_ttm"] or 0 for r in members if r["latest"]["da_ttm"])
        rev_all = sum(r["latest"]["revenue_ttm"] or 0 for r in members)
        layers.append({"layer": layer, "companies": [r["ticker"] for r in members],
                       "revenue_ttm": rev_all, "capex_ttm": sum(r["latest"]["capex_ttm"] or 0 for r in members),
                       "capex_growth": cap_now / cap_prev - 1 if cap_prev else None, "revenue_growth": rev_now / rev_prev - 1 if rev_prev else None,
                       "op_margin": op_now / rev_all if rev_all else None,
                       "capex_to_da": sum(r["latest"]["capex_ttm"] or 0 for r in members if r["latest"]["da_ttm"]) / da if da else None,
                       "nopat_ttm": nopat, "invested": ic, "roic": nopat / ic if ic > 0 else None})
    insights = write_insights(layers, rows)
    data = {"generated": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"), "layers": layers, "companies": rows, "problems": problems, "insights": insights, "fx": FX,
            "method": {"roic": "NOPAT ÷ average invested capital. NOPAT = trailing-four-quarter operating income × (1 − effective tax rate, clamped 0–35%, 21% when pre-tax income is not positive). Invested capital = shareholders' equity + long-term debt (current and non-current) + lease liabilities − cash − short-term investments, averaged between the latest quarter end and the one a year earlier.",
                       "quarters": "Filers tag single quarters for Q1–Q3 and only the full year for Q4; the fourth quarter is derived by subtraction. Trailing twelve months = the last four discrete quarters.",
                       "source": "SEC EDGAR XBRL company-facts API (data.sec.gov), US GAAP tags; every figure links back to the filing."}}
    os.makedirs(OUT, exist_ok=True)
    json.dump(data, open(os.path.join(OUT, "data.json"), "w"), indent=1)
    tpl = open(os.path.join(HERE, "template.html")).read()
    open(os.path.join(OUT, "index.html"), "w").write(tpl.replace("__DATA__", json.dumps(data)))
    return data

if __name__ == "__main__":
    d = build()
    for l in d["layers"]:
        print(f"{l['layer']:24s} ROIC {l['roic'] and round(l['roic']*100,1)}%  revenue ${l['revenue_ttm']/1e9:,.0f}B  capex ${l['capex_ttm']/1e9:,.0f}B")
    for c in d["companies"]:
        L = c["latest"]; f = lambda x, m=1: "n/a" if x is None else f"{x*m:,.1f}"
        print(f"  {c['ticker']:5s} {c['asof']}  ROIC {f(L['roic'],100)}%  rev ${f(L['revenue_ttm'] and L['revenue_ttm']/1e9)}B  capex ${f(L['capex_ttm'] and L['capex_ttm']/1e9)}B  capex/rev {f(L['capex_intensity'],100)}%  IC ${f(L['invested'] and L['invested']/1e9)}B  growth {f(c['revenue_growth'],100)}%")
    if d["problems"]: print("problems:", *d["problems"], sep="\n  ")
