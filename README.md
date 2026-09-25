# Cloud ROIC

Return on invested capital across the AI stack, computed every morning from SEC filings: hyperscalers (Microsoft, Amazon, Alphabet, Meta, Oracle), neoclouds (CoreWeave, Nebius, Applied Digital, IREN, Core Scientific, TeraWulf, Cipher, Hut 8, DigitalOcean), data-centre landlords (Equinix, Digital Realty) and AI silicon (NVIDIA, Broadcom).

**Live page:** https://sethclawd-prog.github.io/cloud-roic/

Inspired by Satya Nadella describing a coding agent that pulls every cloud provider's SEC filings into a dashboard that is fresh every day, with real-time ROIC by layer.

## How it works

- `roic.py` (standard library only) reads each company's facts from EDGAR's XBRL API (`data.sec.gov/api/xbrl/companyfacts`) and its filing index (`data.sec.gov/submissions`).
- Filers tag single quarters for Q1–Q3 and only the full year for Q4, so Q4 is derived by subtraction; trailing twelve months is the last four discrete quarters. Filers also switch tags over the years, so every concept has an ordered list of fallbacks and the most recently used tag wins.
- ROIC = NOPAT ÷ average invested capital. NOPAT = TTM operating income × (1 − effective tax rate, clamped 0–35%, 21% when pre-tax income is not positive). Invested capital = equity + debt (current and non-current) + lease liabilities − cash − short-term investments, averaged over the year.
- Layer ROIC is capital-weighted (summed NOPAT over summed invested capital).
- `template.html` renders `docs/data.json` as inline SVG charts with hover, a filterable time range, and a table where every row links back to the filing. No external scripts.
- `.github/workflows/refresh.yml` runs it daily and commits `docs/`, which GitHub Pages serves.

## Run it yourself

```sh
EDGAR_UA="your-project your@email" python3 roic.py    # EDGAR requires a contact in the User-Agent
open docs/index.html
```

Set `EDGAR_CACHE=/some/dir` to reuse downloaded facts between runs.

## Not in here yet

Segment-level returns (AWS, Azure, Google Cloud on their own). EDGAR's company-facts API drops the segment dimension; getting those means parsing each 10-Q's XBRL instance document. Nebius files annually (20-F), so its figures are the last fiscal year.
