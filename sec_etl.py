"""
sec_etl.py — 把 Step 1 notebook 的流程包裝成可重複使用的函數

用法：
    import sec_etl
    long_df, report = sec_etl.build_company("FORM", "1039399", HEADERS)

Step 1 是「一步一步看懂」；這個檔案是「看懂之後，包起來重複用」。
同樣的程式碼要套用到 5 家公司時，寫成函數就不用複製貼上 5 次。
"""
import json
import time
from pathlib import Path

import pandas as pd
import requests

# 指標 → (報表, [候選 XBRL 標籤，依優先順序])
# 比 Step 1 多加了幾個營收標籤，因為不同公司用不同的標籤
METRICS = {
    # ---- 損益表 ----
    "revenue":            ("IS", ["RevenueFromContractWithCustomerExcludingAssessedTax", "Revenues",
                                  "RevenueFromContractWithCustomerIncludingAssessedTax",
                                  "SalesRevenueNet", "SalesRevenueGoodsNet"]),
    "cost_of_revenue":    ("IS", ["CostOfRevenue", "CostOfGoodsAndServicesSold", "CostOfGoodsSold",
                                  # Cohu 2021 年起改用這個標籤：成本「不含折舊攤提」，毛利率會略為偏高
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
    # ---- 資產負債表 ----
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
    # ---- 現金流量表 ----
    "operating_cash_flow":("CF", ["NetCashProvidedByUsedInOperatingActivities",
                                  "NetCashProvidedByUsedInOperatingActivitiesContinuingOperations"]),
    "capex":              ("CF", ["PaymentsToAcquirePropertyPlantAndEquipment", "PaymentsToAcquireProductiveAssets"]),
    "depreciation":       ("CF", ["Depreciation", "DepreciationDepletionAndAmortization",
                                  "DepreciationAmortizationAndAccretionNet"]),
    "stock_comp":         ("CF", ["ShareBasedCompensation", "AllocatedShareBasedCompensationExpense"]),
    "buybacks":           ("CF", ["PaymentsForRepurchaseOfCommonStock"]),
    "acquisitions":       ("CF", ["PaymentsToAcquireBusinessesNetOfCashAcquired"]),
}


# ---------------------------------------------------------------- 1. 擷取
def fetch_companyfacts(cik, headers, raw_dir, use_cache=True):
    """抓 SEC companyfacts JSON；已經抓過就讀本機檔案（快取），不重複打 API。"""
    cik10 = str(cik).zfill(10)
    raw_dir = Path(raw_dir)
    raw_dir.mkdir(parents=True, exist_ok=True)
    path = raw_dir / f"companyfacts_CIK{cik10}.json"
    if use_cache and path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    url = f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik10}.json"
    resp = requests.get(url, headers=headers, timeout=30)
    resp.raise_for_status()
    time.sleep(0.3)  # SEC 限制每秒最多 10 次請求，禮貌性暫停
    facts = resp.json()
    path.write_text(json.dumps(facts), encoding="utf-8")
    return facts


# ---------------------------------------------------------------- 2. 攤平
def flatten(facts):
    """巢狀 JSON → 長表格（和 Step 1 第 2 節一樣的四層迴圈）"""
    rows = []
    for taxonomy, concepts in facts["facts"].items():
        for concept, info in concepts.items():
            for unit, entries in info["units"].items():
                for e in entries:
                    rows.append({"taxonomy": taxonomy, "concept": concept, "unit": unit, **e})
    return pd.DataFrame(rows)


# ---------------------------------------------------------------- 3. 清理
def clean(df_raw):
    """只留 10-K 年度資料、推算會計年度、去重（保留最新申報）"""
    df = df_raw[(df_raw["taxonomy"] == "us-gaap") & (df_raw["form"].isin(["10-K", "10-K/A"]))].copy()
    for col in ["start", "end", "filed"]:
        if col not in df:
            df[col] = pd.NaT
        df[col] = pd.to_datetime(df[col], errors="coerce")

    df["period_type"] = df["start"].isna().map({True: "instant", False: "flow"})
    df["duration_days"] = (df["end"] - df["start"]).dt.days
    is_annual_flow = (df["period_type"] == "flow") & df["duration_days"].between(350, 380)
    df = df[is_annual_flow | (df["period_type"] == "instant")].copy()

    # 會計年度：年度結束在 6 月以後算當年，1~5 月結束算前一年
    # 例：Onto 的 2021 年度結束在 2022-01-01 → 算 2021
    df["fiscal_year"] = df["end"].dt.year.where(df["end"].dt.month >= 6, df["end"].dt.year - 1)

    # 年度結束日：用「任何一個營收候選標籤」的年度期間結束日當標準
    rev_tags = METRICS["revenue"][1]
    fy_end_dates = set(df.loc[(df["period_type"] == "flow") & df["concept"].isin(rev_tags), "end"])
    df = df[(df["period_type"] == "flow") | df["end"].isin(fy_end_dates)].copy()

    key = ["concept", "unit", "fiscal_year", "period_type"]
    df = df.sort_values("filed").drop_duplicates(subset=key, keep="last").reset_index(drop=True)
    return df


# ---------------------------------------------------------------- 4. 對應指標
def map_metrics(df, metrics=METRICS):
    """XBRL 標籤 → 分析指標；逐年使用第一個有資料的候選標籤"""
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
    """缺值時用會計公式推算：
    - 總負債 = 負債與權益合計 − 股東權益
    - 毛利   = 營收 − 銷貨成本
    - 管銷費用 = 銷售費用 + 管理費用（有些公司把兩者分開申報，例如 Onto）
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


# ---------------------------------------------------------------- 5. 一次跑完
def build_company(ticker, cik, headers, raw_dir="data/raw", n_years=10, use_cache=True):
    """擷取 → 攤平 → 清理 → 對應 → 推算，回傳 (長表格, 對應報告)"""
    facts = fetch_companyfacts(cik, headers, raw_dir, use_cache)
    df = clean(flatten(facts))
    fin_long, report = map_metrics(df)
    # 管銷費用的兩個組成項目，先放進來給 add_derived 用，算完再移除
    parts = df[df["concept"].isin(["SellingAndMarketingExpense", "GeneralAndAdministrativeExpense"])
               & (df["period_type"] == "flow")].assign(metric="_sga_part", statement="IS")
    fin_long = add_derived(pd.concat([fin_long, parts], ignore_index=True))
    fin_long = fin_long[fin_long["metric"] != "_sga_part"]

    # 更新檢查報告：用公式補上的指標標記為 derived
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
