"""
sec_etl.py — reusable ETL for SEC EDGAR XBRL "companyfacts" data.

Packages the step-by-step logic of notebook 01 into functions so the same
pipeline can be applied to any U.S.-listed company:

    import sec_etl
    long_df, report = sec_etl.build_company("FORM", "1039399", HEADERS)

Pipeline: fetch (with local cache) -> flatten -> clean -> map XBRL tags to metrics -> derive missing metrics.
"""
import json
import time
from pathlib import Path

import pandas as pd
import requests

# metric -> (statement, [candidate XBRL tags in priority order])
# Companies (and years) use different tags for the same line item, so each metric has fallbacks.
METRICS = {
    # ---- Income statement ----
    "revenue":            ("IS", ["RevenueFromContractWithCustomerExcludingAssessedTax", "Revenues",
                                  "RevenueFromContractWithCustomerIncludingAssessedTax",
                                  "SalesRevenueNet", "SalesRevenueGoodsNet"]),
    "cost_of_revenue":    ("IS", ["CostOfRevenue", "CostOfGoodsAndServicesSold", "CostOfGoodsSold",
                                  # Used by Cohu from 2021: excludes D&A, so gross margin is slightly overstated
                                  "CostOfGoodsAndServiceExcludingDepreciationDepletionAndAmortization"]),
    "gross_profit":       ("IS", ["GrossProfit"]),
    "rd_expense":         ("IS", ["ResearchAndDevelopmentExpense",
                                  "ResearchAndDevelopmentExpenseExcludingAcquiredInProcessCost"]),
    "sga_expense":        ("IS", ["SellingGeneralAndAdministrativeExpense"]),
    "operating_income":   ("IS", ["OperatingIncomeLoss"]),
    "income_tax":         ("IS", ["IncomeTaxExpenseBenefit"]),
    "net_income":         ("IS", ["NetIncomeLoss", "ProfitLoss"]),
    "eps_diluted":        ("IS", ["EarningsPerShareDiluted"]),
    "shares_diluted":     ("IS", ["WeightedAverageNumberOfDilutedSharesOutstanding"]),
    # ---- Balance sheet ----
    "cash":               ("BS", ["CashAndCashEquivalentsAtCarryingValue"]),
    "st_investments":     ("BS", ["MarketableSecuritiesCurrent", "AvailableForSaleSecuritiesDebtSecuritiesCurrent",
                                  "ShortTermInvestments"]),
    "accounts_receivable":("BS", ["AccountsReceivableNetCurrent", "AccountsAndOtherReceivablesNetCurrent",
                                  "AccountsNotesAndLoansReceivableNetCurrent", "ReceivablesNetCurrent"]),
    "inventory":          ("BS", ["InventoryNet"]),
    "current_assets":     ("BS", ["AssetsCurrent"]),
    "total_assets":       ("BS", ["Assets"]),
    "current_liabilities":("BS", ["LiabilitiesCurrent"]),
    "total_liabilities":  ("BS", ["Liabilities"]),
    "long_term_debt":     ("BS", ["LongTermDebtNoncurrent", "LongTermDebt"]),
    "total_equity":       ("BS", ["StockholdersEquity",
                                  "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest"]),
    "liab_and_equity":    ("BS", ["LiabilitiesAndStockholdersEquity"]),
    "goodwill":           ("BS", ["Goodwill"]),
    # ---- Cash flow statement ----
    "operating_cash_flow":("CF", ["NetCashProvidedByUsedInOperatingActivities",
                                  "NetCashProvidedByUsedInOperatingActivitiesContinuingOperations"]),
    "capex":              ("CF", ["PaymentsToAcquirePropertyPlantAndEquipment", "PaymentsToAcquireProductiveAssets"]),
    "depreciation":       ("CF", ["Depreciation", "DepreciationDepletionAndAmortization",
                                  "DepreciationAmortizationAndAccretionNet"]),
    "stock_comp":         ("CF", ["ShareBasedCompensation", "AllocatedShareBasedCompensationExpense"]),
    "buybacks":           ("CF", ["PaymentsForRepurchaseOfCommonStock"]),
    "acquisitions":       ("CF", ["PaymentsToAcquireBusinessesNetOfCashAcquired"]),
}


# ---------------------------------------------------------------- 1. Fetch
def fetch_companyfacts(cik, headers, raw_dir, use_cache=True):
    """Download the SEC companyfacts JSON, or read the cached copy if it already exists."""
    cik10 = str(cik).zfill(10)
    raw_dir = Path(raw_dir)
    raw_dir.mkdir(parents=True, exist_ok=True)
    path = raw_dir / f"companyfacts_CIK{cik10}.json"
    if use_cache and path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    url = f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik10}.json"
    resp = requests.get(url, headers=headers, timeout=30)
    resp.raise_for_status()
    time.sleep(0.3)  # stay well under the SEC limit of 10 requests per second
    facts = resp.json()
    path.write_text(json.dumps(facts), encoding="utf-8")
    return facts


# ---------------------------------------------------------------- 2. Flatten
def flatten(facts):
    """Nested JSON -> long table: one row per reported value."""
    rows = []
    for taxonomy, concepts in facts["facts"].items():
        for concept, info in concepts.items():
            for unit, entries in info["units"].items():
                for e in entries:
                    rows.append({"taxonomy": taxonomy, "concept": concept, "unit": unit, **e})
    return pd.DataFrame(rows)


# ---------------------------------------------------------------- 3. Clean
def clean(df_raw):
    """Keep annual 10-K values, assign fiscal years, and keep the latest filing for restated values."""
    df = df_raw[(df_raw["taxonomy"] == "us-gaap") & (df_raw["form"].isin(["10-K", "10-K/A"]))].copy()
    for col in ["start", "end", "filed"]:
        if col not in df:
            df[col] = pd.NaT
        df[col] = pd.to_datetime(df[col], errors="coerce")

    df["period_type"] = df["start"].isna().map({True: "instant", False: "flow"})
    df["duration_days"] = (df["end"] - df["start"]).dt.days
    is_annual_flow = (df["period_type"] == "flow") & df["duration_days"].between(350, 380)
    df = df[is_annual_flow | (df["period_type"] == "instant")].copy()

    # Fiscal year: periods ending in Jun-Dec belong to that calendar year, Jan-May to the prior year
    # (e.g. Onto's FY2021 ended 2022-01-01)
    df["fiscal_year"] = df["end"].dt.year.where(df["end"].dt.month >= 6, df["end"].dt.year - 1)

    # Keep balance-sheet values only at fiscal year-end dates (taken from annual revenue periods)
    rev_tags = METRICS["revenue"][1]
    fy_end_dates = set(df.loc[(df["period_type"] == "flow") & df["concept"].isin(rev_tags), "end"])
    df = df[(df["period_type"] == "flow") | df["end"].isin(fy_end_dates)].copy()

    key = ["concept", "unit", "fiscal_year", "period_type"]
    df = df.sort_values("filed").drop_duplicates(subset=key, keep="last").reset_index(drop=True)
    return df


# ---------------------------------------------------------------- 4. Map to metrics
def map_metrics(df, metrics=METRICS):
    """Map XBRL tags to analysis metrics, using the first available candidate tag in each year."""
    records, report = [], []
    for metric, (statement, candidates) in metrics.items():
        sub = df[df["concept"].isin(candidates)].copy()
        if sub.empty:
            report.append((metric, "missing", ""))
            continue
        sub["priority"] = sub["concept"].map({c: i for i, c in enumerate(candidates)})
        sub = sub.sort_values("priority").drop_duplicates("fiscal_year", keep="first")
        sub["metric"], sub["statement"] = metric, statement
        records.append(sub)
        report.append((metric, "ok", ", ".join(sorted(sub["concept"].unique()))))
    fin_long = pd.concat(records, ignore_index=True) if records else pd.DataFrame()
    return fin_long, pd.DataFrame(report, columns=["metric", "status", "tags_used"])


def add_derived(fin_long):
    """Fill missing metrics with accounting identities:
    - total liabilities = liabilities and equity - stockholders' equity
    - gross profit      = revenue - cost of revenue
    - SG&A              = selling & marketing + G&A (for filers that report them separately, e.g. Onto)
    """
    wide = fin_long.pivot_table(index="fiscal_year", columns="metric", values="val")
    raw = fin_long.pivot_table(index="fiscal_year", columns="concept", values="val")
    col = lambda frame, name: frame[name] if name in frame else pd.Series(index=frame.index, dtype=float)

    formulas = {
        "total_liabilities": ("BS", col(wide, "liab_and_equity") - col(wide, "total_equity")),
        "gross_profit":      ("IS", col(wide, "revenue") - col(wide, "cost_of_revenue")),
        "sga_expense":       ("IS", col(raw, "SellingAndMarketingExpense") + col(raw, "GeneralAndAdministrativeExpense")),
    }
    adds = []
    for metric, (statement, calc) in formulas.items():
        calc = calc.reindex(wide.index)
        missing = col(wide, metric).isna() & calc.notna()
        if missing.any():
            adds.append(pd.DataFrame({"fiscal_year": wide.index[missing], "metric": metric,
                                      "val": calc[missing].values, "concept": "derived",
                                      "statement": statement}))
    return pd.concat([fin_long] + adds, ignore_index=True) if adds else fin_long


# ---------------------------------------------------------------- 5. End-to-end
def build_company(ticker, cik, headers, raw_dir="data/raw", n_years=10, use_cache=True):
    """Fetch -> flatten -> clean -> map -> derive. Returns (long table, tag-mapping report)."""
    facts = fetch_companyfacts(cik, headers, raw_dir, use_cache)
    df = clean(flatten(facts))
    fin_long, report = map_metrics(df)
    # temporarily include the SG&A components so add_derived can sum them
    parts = df[df["concept"].isin(["SellingAndMarketingExpense", "GeneralAndAdministrativeExpense"])
               & (df["period_type"] == "flow")].assign(metric="_sga_part", statement="IS")
    fin_long = add_derived(pd.concat([fin_long, parts], ignore_index=True))
    fin_long = fin_long[fin_long["metric"] != "_sga_part"]

    # flag metrics filled by an identity as 'derived' in the report
    derived = set(fin_long.loc[fin_long["concept"] == "derived", "metric"])
    report.loc[(report["status"] == "missing") & report["metric"].isin(derived), "status"] = "derived"

    last_fy = int(fin_long.loc[fin_long["metric"] == "revenue", "fiscal_year"].max())
    fin_long = fin_long[fin_long["fiscal_year"].between(last_fy - n_years + 1, last_fy)]

    out = (fin_long[["fiscal_year", "statement", "metric", "val", "concept", "end", "filed", "accn"]]
           .rename(columns={"val": "value", "end": "period_end", "filed": "filed_date"})
           .copy())
    out["period_end"] = pd.to_datetime(out["period_end"]).dt.strftime("%Y-%m-%d")
    out["filed_date"] = pd.to_datetime(out["filed_date"]).dt.strftime("%Y-%m-%d")
    out.insert(0, "ticker", ticker)
    report.insert(0, "ticker", ticker)
    return out.sort_values(["statement", "metric", "fiscal_year"]).reset_index(drop=True), report
