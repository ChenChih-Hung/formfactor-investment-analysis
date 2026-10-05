# FormFactor (NASDAQ: FORM) Investment Analysis

An end-to-end equity research project on **FormFactor**, a U.S. leader in semiconductor wafer probe cards, built as a hands-on exercise in financial data engineering and analysis: pulling raw filings from the SEC, cleaning them, modeling them in SQL, and turning the numbers into an investment view.

**Author:** Chen-Chih (Cosby) Hung — MS in Business Analytics, University of Illinois Urbana-Champaign

📄 **Research note (PDF, October 2026):** [FormFactor_Research_Note.pdf](report/FormFactor_Research_Note.pdf)

## Current view (October 2026): Cautious

**The turnaround is real. The price assumes it is permanent.**

- **2026 changed the margin picture.** Q2 2026 revenue grew 31.9% year over year to a record $258M; non-GAAP gross margin rose from 38.5% (Q2 2025) to 53.3%, and GAAP operating margin reached 22%.
- **Part of it will not repeat.** Management puts normalized gross margin near 51%; Q3 guidance of 54% includes about 3 points of tariff refunds.
- **Investment is rising again.** 2026 capex is guided to $140–170M for a new Texas facility, after a record $104M in 2025.
- **The valuation assumes the best case.** At $149.15 (Oct 2, 2026) the shares trade at 43x forward earnings, above the $139 average analyst target. In illustrative 2027 scenarios only the bull case (revenue ≈ $1.4B at a 30% operating margin) supports the current price.

<p align="center"><img src="data/analysis/gm_turnaround.png" width="70%"></p>

---

## What this project demonstrates

| Area | Skills |
|---|---|
| Data extraction | SEC EDGAR XBRL API (`companyfacts`), `requests`, JSON parsing, caching |
| Data cleaning | 10-K filtering, 52/53-week fiscal year alignment, restatement handling, de-duplication, tag fallbacks, quarterly values derived from 10-Q year-to-date figures |
| Data modeling | SQLite star schema (fact + dimension tables), primary keys, views, idempotent loads |
| SQL | `CASE WHEN` pivots, window functions (`LAG`, `ROW_NUMBER`, `RANK`, `FIRST_VALUE`, `SUM() OVER`), CTEs, self-joins, multi-key joins, `UNION ALL` |
| Python | pandas, reusable ETL module (`sec_etl.py`), matplotlib |
| Financial analysis | Margin, return, liquidity and cash-flow ratios; one-time item adjustment; CAGR; peer benchmarking; FX conversion; market share and HHI |

## Pipeline

```
SEC EDGAR API (10-K, 10-Q) ──► raw JSON ──► clean long table ──► CSV ──► SQLite ──► SQL views ──► ratios, peer & market analysis ──► charts ──► research note
                                                         ▲
                          manually collected research data (10-K, earnings releases, FX rates) with source column
```

## Repository structure

```
├── 01_extract_clean.ipynb      Step 1  Pull FormFactor XBRL data from SEC, clean, export CSV
├── 02_sql_analysis.ipynb       Step 2  Load into SQLite, compute financial ratios with SQL
├── 03_peer_comparison.ipynb    Step 3a Peer benchmarking vs Teradyne, Cohu, Onto Innovation, Kulicke & Soffa
├── 04_market_structure.ipynb   Step 3b Revenue mix, segment margins, probe-card market share, supply chain
├── 05_quarterly_update.ipynb   Step 4  Quarterly 10-Q data, 2026 margin turnaround, valuation scenarios
├── sec_etl.py                  Reusable ETL functions (fetch → flatten → clean → map → derive)
├── report/                     Research note (PDF)
├── data/
│   ├── clean/                  Cleaned financial statements (long and wide CSV)
│   ├── research/               Manually collected market data, every row with its source
│   └── analysis/               Output tables and charts
└── requirements.txt
```

## How to run

```bash
pip install -r requirements.txt
jupyter notebook
```

Run the notebooks in order (01 → 05). The SEC requires a `User-Agent` header with a name and email; replace the `HEADERS` value in notebooks 01 and 03 with your own. Raw SEC responses are cached in `data/raw/` and the SQLite database is rebuilt by the notebooks, so neither is committed.

## Key findings (historical analysis through FY2025)

These findings describe FormFactor through its FY2025 10-K. Several were overtaken by the 2026 recovery above, which is why the analysis was extended to quarterly data.

**1. Revenue is the most stable in its peer group, but profitability lags.**
FormFactor's revenue grew from $589.5M (2019) to $785.0M (2025). In the 2023 downturn its revenue fell 11.3%, the smallest decline among five U.S.-listed test and packaging peers (Teradyne −15.2%, Onto −18.8%, Cohu −21.7%, Kulicke & Soffa −50.6%).

**2. A reported profit jump in 2023 was a one-time gain.**
GAAP net income rose 62% in 2023 while revenue fell 11%. The gap was a $73.0M gain on the sale of the FRT business; excluding it, operating income fell from $54.9M to about $9.8M.

**3. Low gross margin and heavy capex, not R&D, drive the weak free cash flow.**
2021–2025 averages versus peers:

| | Gross margin | Operating margin (adj.) | R&D % rev | Capex % rev | FCF margin |
|---|---|---|---|---|---|
| Teradyne | 58.6% | 23.8% | 14.7% | 5.8% | 17.2% |
| Onto Innovation | 52.3% | 10.0% | 12.2% | 2.4% | 20.4% |
| Kulicke & Soffa | 44.9% | 10.0% | 16.4% | 2.8% | 15.4% |
| Cohu | 45.2% | 2.3% | 15.4% | 2.6% | 7.1% |
| **FormFactor** | **40.0%** | **7.5%** | **15.2%** | **8.8%** | **6.3%** |

**4. FormFactor is losing share to direct probe-card competitors, who are far more profitable.**
Converted to USD, Technoprobe's 2025 revenue ($709M) exceeded FormFactor's probe-card segment ($638M). In 2025 FormFactor's probe-card revenue grew 1.9% versus 15.7% (Technoprobe), 26.1% (Micronics Japan) and 33.3% (Chunghwa Precision Test) in local currency. Micronics Japan's operating margin (23.6%) and Technoprobe's EBITDA margin (32.1%) compare with 7.3% at FormFactor, so the margin gap is company-specific rather than structural to the industry.

**5. DRAM / HBM drives growth, but at lower margins.**
DRAM grew from $114M (17.2% of revenue) in 2023 to $309M (34.3%) in the twelve months to June 2026, driven by high-bandwidth memory for AI. Yet probe-card gross margin stayed around 40% (40.5% in 2025): management states DRAM products carry lower margins than Foundry & Logic, and tariffs raised U.S. manufacturing costs. The largest customer accounted for 22.9% of 2025 revenue.

<p align="center">
  <img src="data/analysis/peer_margins_5yr.png" width="100%">
</p>
<p align="center">
  <img src="data/analysis/form_revenue_by_market.png" width="48%">
  <img src="data/analysis/probe_card_revenue_usd.png" width="48%">
</p>

## Data sources

- SEC EDGAR XBRL `companyfacts` API — FormFactor, Teradyne, Cohu, Onto Innovation, Kulicke & Soffa
- FormFactor 10-K (FY2023, FY2025), 10-Q (six months ended July 1, 2023) and Q4 2023 / Q4 2025 earnings releases
- Technoprobe FY2025 results release; Micronics Japan FY2025 consolidated results; Chunghwa Precision Test 2025 revenue (Economic Daily News)
- IRS yearly average currency exchange rates
- FormFactor Q2 2026 earnings release and call; market data from stockanalysis.com (as of Oct 2, 2026)
- Mordor Intelligence probe card market report (market size estimate)

## Limitations

- Peer revenue scopes differ: FormFactor's probe-card figure excludes its Systems segment, while competitors' figures are total company revenue (Technoprobe includes the Device Interface Solutions business acquired from Teradyne).
- Kulicke & Soffa's fiscal year ends in September/October, about one quarter offset from the other companies.
- Onto Innovation was formed by a merger in October 2019, which inflates growth measured from a 2019 base.
- The total probe-card market size is a third-party estimate; estimates vary by provider.

## Next steps

- Technology analysis: MEMS and vertical probe roadmaps, HBM and advanced-packaging test challenges, co-packaged optics testing
- Full DCF model with explicit capex and working-capital assumptions
- Competitors' 2026 results, to test whether FormFactor is regaining probe-card share
