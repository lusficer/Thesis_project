"""
Universal Data Adapter - preprocessing.py
Normalises 8 eCommerce CSV formats based on DATASETS_ANALYSIS.md

Supported formats:
  india_orders        - List_of_Orders.csv (Order ID, Order Date, CustomerName, State, City)
  india_order_details - Order_Details.csv  (Order ID, Amount, Profit, Quantity, Category, Sub-Category)
  uk_retail           - online_retail_II.csv / data.csv (Invoice/InvoiceNo, StockCode, Quantity, InvoiceDate, Price/UnitPrice)
  electronics         - Electronic_Sales.csv (Product, Quantity Ordered, Price Each, Order Date)
  fmcg                - product_sales_dataset_final.csv (Order_Date MM-DD-YY, Sub_Category, Quantity, " Unit_Price ")
  retail_transactions - Retail_Transactions_Dataset.csv (Date, Product as list-string, Total_Items)
  favorita            - train.csv (date, store_nbr, family, sales)
  olist               - (order_purchase_timestamp, product_id)
  generic             - best-effort fallback

Output columns: order_purchase_timestamp, product_id, quantity, product_name
price_map: {product_id: median_unit_price}
cost_map:  {product_id: median_cost_price}  — FMCG only; empty dict for all other formats
"""

import ast
import io
import re
import warnings
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _col_set(df: pd.DataFrame) -> set:
    return {c.strip().lower() for c in df.columns}

def _col_map(df: pd.DataFrame) -> Dict[str, str]:
    return {c.strip().lower(): c for c in df.columns}

def _pick(cm: Dict[str, str], *candidates: str) -> Optional[str]:
    for c in candidates:
        if c in cm:
            return cm[c]
    return None

def _parse_date_flexible(series: pd.Series, dayfirst: bool = False) -> pd.Series:
    """Try multiple date formats, returning the parse with fewest NaT."""
    result = pd.to_datetime(series, errors="coerce", dayfirst=dayfirst)
    null_ratio = result.isna().mean()
    if null_ratio > 0.3:
        for fmt in ("%m-%d-%y", "%d-%m-%Y", "%m/%d/%Y", "%Y/%m/%d",
                    "%d/%m/%Y", "%m-%d-%Y", "%Y-%m-%d %H:%M:%S"):
            attempt = pd.to_datetime(series, format=fmt, errors="coerce")
            if attempt.isna().mean() < null_ratio:
                result, null_ratio = attempt, attempt.isna().mean()
    return result


# ─── Format detection ─────────────────────────────────────────────────────────

def _detect_format(df: pd.DataFrame) -> str:
    cols = _col_set(df)

    if "order_purchase_timestamp" in cols and "product_id" in cols:
        return "olist"
    if {"family", "store_nbr", "sales"}.issubset(cols):
        return "favorita"
    if "quantity ordered" in cols:
        return "electronics"
    if "stockcode" in cols and "invoicedate" in cols:
        return "uk_retail"
    if "stockcode" in cols and "invoice" in cols:
        return "uk_retail"
    # India two-file split
    if "sub-category" in cols and "amount" in cols and "quantity" in cols:
        return "india_order_details"
    if "customername" in cols and "order date" in cols and "state" in cols:
        return "india_orders"
    # FMCG: has sub_category + order_date (with underscore)
    if "sub_category" in cols and "order_date" in cols:
        return "fmcg"
    if "product_name" in cols and "order_date" in cols:
        return "fmcg"
    # Retail Transactions: has total_items + season
    if "total_items" in cols and "season" in cols:
        return "retail_transactions"
    if "transaction_id" in cols and "product" in cols:
        return "retail_transactions"
    return "generic"


# ─── Per-format parsers ───────────────────────────────────────────────────────

def _parse_olist(df: pd.DataFrame) -> pd.DataFrame:
    cm = _col_map(df)
    out = pd.DataFrame()
    out["order_purchase_timestamp"] = _parse_date_flexible(df[cm["order_purchase_timestamp"]])
    out["product_id"] = df[cm["product_id"]].astype(str).str.strip()
    qty_col = _pick(cm, "quantity", "order_item_id")
    out["quantity"] = pd.to_numeric(df[qty_col], errors="coerce").fillna(1) if qty_col else 1
    name_col = _pick(cm, "product_category_name", "product_id")
    out["product_name"] = df[name_col].fillna("Unknown").astype(str) if name_col else out["product_id"]
    return out


# StockCodes that are NOT real products in UK Retail datasets
_UK_RETAIL_JUNK_CODES = {
    "POST", "D", "DOT", "M", "AMAZONFEE", "BANK CHARGES", "PADS",
    "CRUK", "gift_0001", "DCGS0003", "DCGS0004", "DCGS0070", "DCGS0072",
    "SP1002", "gift voucher", "ADJUST", "TEST001", "TEST002",
}
_UK_RETAIL_JUNK_PREFIX = ("C",)          # 'C' prefix = cancelled order / credit note
_UK_RETAIL_DESC_BLACKLIST = {
    "", "nan", "none", "?", "??", "???", "check", "samples",
    "amazon fees", "cruk commission", "dotcom postage",
}


def _parse_uk_retail(df: pd.DataFrame) -> pd.DataFrame:
    """
    UK Online Retail II: Invoice, StockCode, Description, Quantity, InvoiceDate, Price, Customer ID, Country
    General Data:        InvoiceNo, StockCode, Description, Quantity, InvoiceDate, UnitPrice, CustomerID, Country

    Cleaning rules applied:
    1. Remove cancellations: StockCode starting with 'C' (credit notes)
    2. Remove junk/test StockCodes (POST, DOT, AMAZONFEE, etc.)
    3. Remove rows where Description is null or looks like a code (all digits / short alphanumeric)
    4. Use Description as product_name; if missing, SKIP the row (don't fall back to StockCode)
    5. Remove negative/zero quantity
    """
    df = df.copy(); df.columns = [c.strip() for c in df.columns]
    cm = _col_map(df)

    sku_col  = _pick(cm, "stockcode")
    desc_col = _pick(cm, "description")
    qty_col  = _pick(cm, "quantity")
    date_col = _pick(cm, "invoicedate")

    out = pd.DataFrame()
    out["_sku"]      = df[sku_col].astype(str).str.strip() if sku_col else "UNKNOWN"
    out["_desc"]     = df[desc_col].astype(str).str.strip().str.upper() if desc_col else ""
    out["quantity"]  = pd.to_numeric(df[qty_col], errors="coerce") if qty_col else 0
    out["order_purchase_timestamp"] = _parse_date_flexible(df[date_col], dayfirst=True) if date_col else pd.NaT

    # ── Filter 1: positive quantity only ──────────────────────────────
    out = out[out["quantity"] > 0].copy()

    # ── Filter 2: remove cancelled/credit StockCodes (start with C + digits)
    import re as _re
    cancelled_mask = out["_sku"].str.match(r"^C\d+", na=False)
    out = out[~cancelled_mask].copy()

    # ── Filter 3: remove known junk codes ─────────────────────────────
    junk_mask = out["_sku"].str.upper().isin({c.upper() for c in _UK_RETAIL_JUNK_CODES})
    out = out[~junk_mask].copy()

    # ── Filter 4: remove rows where Description is missing or looks like a code
    # A "real" description has at least 2 words OR ≥10 chars with spaces
    def _is_real_desc(s: str) -> bool:
        s = s.strip()
        if not s or s.lower() in _UK_RETAIL_DESC_BLACKLIST:
            return False
        # Pure numeric or very short codes like "84465" "15060A" → not a description
        if _re.fullmatch(r"[A-Z0-9]{1,6}", s):
            return False
        # Must have at least one letter and one space (i.e., 2+ words) OR be ≥15 chars
        has_space = " " in s
        has_letter = bool(_re.search(r"[A-Z]", s))
        return has_letter and (has_space or len(s) >= 10)

    real_desc_mask = out["_desc"].apply(_is_real_desc)
    out = out[real_desc_mask].copy()

    # ── Build output ──────────────────────────────────────────────────
    result = pd.DataFrame()
    result["order_purchase_timestamp"] = out["order_purchase_timestamp"].values
    result["product_id"]   = out["_sku"].values
    result["quantity"]     = out["quantity"].values
    # Title-case the description for nicer display
    result["product_name"] = out["_desc"].str.title().values

    return result


def _parse_india_orders(df: pd.DataFrame) -> pd.DataFrame:
    """
    List_of_Orders.csv: Order ID | Order Date | CustomerName | State | City
    No quantity/product — needs join with Order_Details. Return empty with warning.
    """
    warnings.warn(
        "India Orders (List_of_Orders.csv) contains no quantity or product data. "
        "Upload BOTH List_of_Orders.csv AND Order_Details.csv together for complete analysis."
    )
    return pd.DataFrame(columns=["order_purchase_timestamp","product_id","quantity","product_name"])


def _parse_india_order_details(df: pd.DataFrame) -> pd.DataFrame:
    """
    Order_Details.csv: Order ID | Amount | Profit | Quantity | Category | Sub-Category
    No date column alone — returns NaT dates (dropped by post-processing).
    Use smart_merge_files with both India files for correct output.
    """
    df = df.copy(); df.columns = [c.strip() for c in df.columns]
    cm = _col_map(df)
    out = pd.DataFrame()
    out["order_purchase_timestamp"] = pd.NaT
    prod_col = _pick(cm, "sub-category", "category")
    out["product_id"]   = df[prod_col].astype(str).str.strip() if prod_col else "UNKNOWN"
    out["quantity"]     = pd.to_numeric(df[_pick(cm, "quantity")], errors="coerce") if _pick(cm,"quantity") else 1
    out["product_name"] = df[prod_col].astype(str) if prod_col else "Unknown"
    return out


def _parse_india_joined(orders_df: pd.DataFrame, details_df: pd.DataFrame) -> pd.DataFrame:
    """Join List_of_Orders + Order_Details on Order ID to produce dated sales."""
    orders_df  = orders_df.copy();  orders_df.columns  = [c.strip() for c in orders_df.columns]
    details_df = details_df.copy(); details_df.columns = [c.strip() for c in details_df.columns]
    merged = details_df.merge(orders_df[["Order ID","Order Date"]], on="Order ID", how="left")
    out = pd.DataFrame()
    out["order_purchase_timestamp"] = _parse_date_flexible(merged["Order Date"], dayfirst=True)
    out["product_id"]   = merged["Sub-Category"].astype(str).str.strip()
    out["quantity"]     = pd.to_numeric(merged["Quantity"], errors="coerce")
    out["product_name"] = merged["Sub-Category"].astype(str)
    return out


def _parse_electronics(df: pd.DataFrame) -> pd.DataFrame:
    """
    Electronic_Sales.csv:
    Order ID | Product | Quantity Ordered | Price Each | Order Date | Purchase Address | Month | Sales | City | Hour
    """
    df = df.copy(); df.columns = [c.strip() for c in df.columns]
    cm = _col_map(df)
    out = pd.DataFrame()
    out["order_purchase_timestamp"] = _parse_date_flexible(df[_pick(cm,"order date")], dayfirst=False)
    prod_col = _pick(cm, "product")
    out["product_id"]   = df[prod_col].astype(str).str.strip() if prod_col else "UNKNOWN"
    out["quantity"]     = pd.to_numeric(df[_pick(cm,"quantity ordered")], errors="coerce").fillna(1)
    out["product_name"] = df[prod_col].astype(str) if prod_col else "Unknown"
    return out


def _parse_fmcg(df: pd.DataFrame) -> pd.DataFrame:
    """
    product_sales_dataset_final.csv:
    Order_ID | Order_Date (MM-DD-YY) | ... | Category | Sub_Category | Product_Name |
    Quantity | ' Unit_Price ' | ' Revenue ' | ' Profit '

    CRITICAL ISSUES:
    1. Order_Date format is MM-DD-YY (e.g. '08-23-23' = August 23, 2023)
    2. Price/Revenue/Profit column names have leading+trailing SPACES
    """
    df = df.copy()
    # Strip ALL column names first to fix space issue
    df.columns = [c.strip() for c in df.columns]
    cm = _col_map(df)

    out = pd.DataFrame()
    # Use explicit format for MM-DD-YY
    date_raw = df[_pick(cm, "order_date")] if _pick(cm, "order_date") else df.iloc[:, 0]
    out["order_purchase_timestamp"] = _parse_date_flexible(date_raw, dayfirst=False)

    # product_id (SKU) = Product_Name - use the specific name so each product is a unique entity
    # Fallback: Sub_Category if Product_Name is missing (avoid losing data)
    sku_col  = _pick(cm, "product_name", "sub_category", "category")
    name_col = _pick(cm, "product_name", "sub_category", "category")
    out["product_id"]   = df[sku_col].astype(str).str.strip() if sku_col else "UNKNOWN"
    qty_col = _pick(cm, "quantity")
    out["quantity"]     = pd.to_numeric(df[qty_col], errors="coerce").fillna(1) if qty_col else 1
    out["product_name"] = df[name_col].astype(str).str.strip() if name_col else "Unknown"
    return out


def _parse_retail_transactions(df: pd.DataFrame) -> pd.DataFrame:
    """
    Retail_Transactions_Dataset.csv:
    Transaction_ID | Date | Customer_Name | Product | Total_Items | Total_Cost |
    Payment_Method | City | Store_Type | Discount_Applied | Customer_Category | Season | Promotion

    CRITICAL: Product column contains Python list strings like "['Ketchup', 'Shaving Cream']"
    Each transaction must be exploded into individual product rows.
    Quantity per item = Total_Items / count(products in list).
    """
    df = df.copy(); df.columns = [c.strip() for c in df.columns]
    cm = _col_map(df)

    date_col        = _pick(cm, "date")
    product_col     = _pick(cm, "product")
    total_items_col = _pick(cm, "total_items")

    def _parse_product_list(val) -> List[str]:
        if pd.isna(val): return ["Unknown"]
        s = str(val).strip()
        try:
            r = ast.literal_eval(s)
            if isinstance(r, list):
                return [str(x).strip() for x in r if str(x).strip()]
        except Exception:
            pass
        s = re.sub(r"[\[\]\'\"()]", "", s)
        parts = [p.strip() for p in s.split(",") if p.strip()]
        return parts if parts else ["Unknown"]

    dates       = _parse_date_flexible(df[date_col], dayfirst=False) if date_col else pd.Series([pd.NaT]*len(df))
    total_items = pd.to_numeric(df[total_items_col], errors="coerce").fillna(1) if total_items_col else pd.Series([1]*len(df))

    rows = []
    for i in range(len(df)):
        products = _parse_product_list(df[product_col].iloc[i]) if product_col else ["Unknown"]
        n        = len(products)
        ti       = int(total_items.iloc[i])
        qty_each = max(1, round(ti / n)) if n > 0 else 1
        for prod in products:
            rows.append({
                "order_purchase_timestamp": dates.iloc[i],
                "product_id":   prod,
                "quantity":     qty_each,
                "product_name": prod,
            })
    return pd.DataFrame(rows)


def _parse_favorita(df: pd.DataFrame) -> pd.DataFrame:
    """
    Favorita train.csv: id | date | store_nbr | family | sales | onpromotion
    product_id = family (aggregated across all stores).
    """
    df = df.copy(); df.columns = [c.strip() for c in df.columns]
    cm = _col_map(df)
    out = pd.DataFrame()
    out["order_purchase_timestamp"] = _parse_date_flexible(df[_pick(cm, "date")], dayfirst=False)
    family_col = _pick(cm, "family")
    out["product_id"]   = df[family_col].astype(str).str.strip() if family_col else "UNKNOWN"
    sales_col = _pick(cm, "sales")
    out["quantity"]     = pd.to_numeric(df[sales_col], errors="coerce").fillna(0) if sales_col else 0
    out["product_name"] = df[family_col].astype(str) if family_col else "Unknown"
    return out


def _parse_generic(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy(); df.columns = [c.strip() for c in df.columns]
    cm = _col_map(df)
    date_col = None
    for kw in ["date","timestamp","time","day","period","month","invoice"]:
        m = [k for k in cm if kw in k and "id" not in k]
        if m: date_col = cm[m[0]]; break
    product_col = None
    for kw in ["product","item","sku","stock","sub_cat","category","name","description","family"]:
        m = [k for k in cm if kw in k and "id" not in k]
        if m: product_col = cm[m[0]]; break
    qty_col = None
    for kw in ["quantity","qty","units","total_items","sold","sales"]:
        m = [k for k in cm if k == kw or k.startswith(kw)]
        if m: qty_col = cm[m[0]]; break
    out = pd.DataFrame()
    out["order_purchase_timestamp"] = _parse_date_flexible(df[date_col] if date_col else df.iloc[:,0], dayfirst=True)
    out["product_id"]   = df[product_col].astype(str).str.strip() if product_col else "PRODUCT_1"
    out["quantity"]     = pd.to_numeric(df[qty_col], errors="coerce").fillna(1) if qty_col else 1
    out["product_name"] = df[product_col].fillna("Unknown").astype(str) if product_col else "Unknown"
    return out


_PARSERS = {
    "olist":               _parse_olist,
    "uk_retail":           _parse_uk_retail,
    "india_orders":        _parse_india_orders,
    "india_order_details": _parse_india_order_details,
    "electronics":         _parse_electronics,
    "fmcg":                _parse_fmcg,
    "retail_transactions": _parse_retail_transactions,
    "favorita":            _parse_favorita,
    "generic":             _parse_generic,
}


# ─── Price extraction ─────────────────────────────────────────────────────────

def _extract_price_map(df_raw: pd.DataFrame, df_clean: pd.DataFrame) -> Dict[str, float]:
    """
    Build {product_id: median_price}.
    Strips column spaces before matching (fixes FMCG ' Unit_Price ').
    Only matches explicit price keywords — never matches quantity/revenue.
    """
    price_map: Dict[str, float] = {}
    # Strip spaces from column names for matching
    stripped_cm = {c.strip().lower(): c for c in df_raw.columns}
    PRICE_KEYWORDS = ["unit_price","unitprice","price_each","price each",
                      "unit price","item_price","selling_price","price"]
    price_col = _pick(stripped_cm, *PRICE_KEYWORDS)
    if price_col is None:
        return price_map

    fmt = _detect_format(df_raw)
    raw_cm = _col_map(df_raw)

    # Determine product column for grouping
    prod_col_map = {
        "uk_retail":           _pick(raw_cm, "stockcode"),
        "electronics":         _pick(raw_cm, "product"),
        "india_order_details": _pick(raw_cm, "sub-category", "category"),
    }
    # FMCG: columns already stripped in parser but raw_df still has spaces
    if fmt == "fmcg":
        stripped_raw = {c.strip().lower(): c for c in df_raw.columns}
        prod_col_map["fmcg"] = _pick(stripped_raw, "product_name", "sub_category", "category")

    prod_col_raw = prod_col_map.get(fmt)

    raw_prices = pd.to_numeric(df_raw[price_col], errors="coerce")
    if prod_col_raw and prod_col_raw in df_raw.columns:
        mini = pd.DataFrame({
            "product_id": df_raw[prod_col_raw].astype(str).str.strip().values,
            "_price":     raw_prices.values,
        })
        mini = mini[(mini["_price"] > 0) & mini["product_id"].notna()]
        for pid, grp in mini.groupby("product_id"):
            price_map[str(pid)] = float(grp["_price"].median())

    return price_map


# ─── Cost extraction (FMCG only) ─────────────────────────────────────────────

def _extract_cost_map(
    df_raw: pd.DataFrame,
    price_map: Dict[str, float],
) -> Dict[str, float]:
    """
    Build {product_id: median_cost_price} from FMCG datasets only.

    Formula per row:  cost_price = (Revenue - Profit) / Quantity

    Validation rules (set null if violated):
      - cost_price must be > 0
      - cost_price must be < base_price (= median Unit_Price from price_map)
        to guard against data errors / negative-margin outliers

    Returns an empty dict for any non-FMCG format.
    """
    fmt = _detect_format(df_raw)
    if fmt != "fmcg":
        return {}

    # Strip column names so ' Revenue ', ' Profit ' etc. are matched cleanly
    df = df_raw.copy()
    df.columns = [c.strip() for c in df.columns]
    cm = _col_map(df)

    # All three columns must exist; otherwise cost cannot be computed
    revenue_col  = _pick(cm, "revenue")
    profit_col   = _pick(cm, "profit")
    quantity_col = _pick(cm, "quantity")
    if not (revenue_col and profit_col and quantity_col):
        return {}

    prod_col = _pick(cm, "product_name", "sub_category", "category")
    if prod_col is None:
        return {}

    revenue  = pd.to_numeric(df[revenue_col],  errors="coerce")
    profit   = pd.to_numeric(df[profit_col],   errors="coerce")
    quantity = pd.to_numeric(df[quantity_col], errors="coerce").replace(0, np.nan)

    mini = pd.DataFrame({
        "product_id": df[prod_col].astype(str).str.strip(),
        "_cost":      (revenue - profit) / quantity,
    })
    # Drop rows where cost could not be computed
    mini = mini[mini["_cost"].notna() & (mini["_cost"] > 0)].copy()

    cost_map: Dict[str, float] = {}
    for pid, grp in mini.groupby("product_id"):
        pid_str    = str(pid)
        median_cost = float(grp["_cost"].median())
        base_price  = price_map.get(pid_str)

        # Reject if cost >= base_price (data error / zero-margin anomaly)
        if base_price is not None and median_cost >= base_price:
            continue

        cost_map[pid_str] = median_cost

    return cost_map


# ─── Public API ───────────────────────────────────────────────────────────────

def clean_ecommerce_data(
    df: pd.DataFrame,
    config: Optional[dict] = None,
) -> Tuple[pd.DataFrame, Dict[str, float], Dict[str, float]]:
    """
    Returns (df_clean, price_map, cost_map).
    cost_map is non-empty only for FMCG datasets that have Revenue, Profit, Quantity.
    """
    config = config or {}
    fmt    = config.get("format") or _detect_format(df)
    parser = _PARSERS.get(fmt, _parse_generic)
    df_clean = parser(df)

    df_clean["quantity"] = pd.to_numeric(df_clean["quantity"], errors="coerce").fillna(0)
    df_clean = df_clean[df_clean["quantity"] > 0].copy()
    df_clean = df_clean.dropna(subset=["order_purchase_timestamp"]).copy()
    df_clean["product_id"]   = df_clean["product_id"].astype(str).str.strip()
    df_clean["product_name"] = df_clean["product_name"].astype(str).str.strip()
    df_clean["order_purchase_timestamp"] = pd.to_datetime(df_clean["order_purchase_timestamp"], errors="coerce")
    df_clean = df_clean.dropna(subset=["order_purchase_timestamp"])
    df_clean = df_clean.sort_values("order_purchase_timestamp").reset_index(drop=True)

    price_map = _extract_price_map(df, df_clean)
    cost_map  = _extract_cost_map(df, price_map)   # empty {} for non-FMCG
    return df_clean, price_map, cost_map


def smart_merge_files(
    files,
    configs: Optional[List[dict]] = None,
) -> Tuple[pd.DataFrame, Dict[str, float], Dict[str, float]]:
    """
    Merge multiple CSV DataFrames/paths. Detects India 2-file pair and joins them.
    Returns (df_clean, price_map, cost_map).
    """
    raw_dfs = []
    for f in files:
        if isinstance(f, pd.DataFrame):
            raw_dfs.append(f)
        elif isinstance(f, (str, Path)):
            for enc in ("utf-8","utf-8-sig","latin-1","cp1252"):
                try:
                    raw_dfs.append(pd.read_csv(f, encoding=enc, low_memory=False)); break
                except Exception: continue
        elif hasattr(f, "read"):
            raw_bytes = f.read()
            for enc in ("utf-8","utf-8-sig","latin-1","cp1252"):
                try:
                    raw_dfs.append(pd.read_csv(io.BytesIO(raw_bytes), encoding=enc, low_memory=False)); break
                except Exception: continue

    if not raw_dfs:
        return pd.DataFrame(columns=["order_purchase_timestamp","product_id","quantity","product_name"]), {}, {}

    configs = configs or [{}] * len(raw_dfs)
    merged_parts: List[pd.DataFrame] = []
    combined_price_map: Dict[str, float] = {}
    combined_cost_map:  Dict[str, float] = {}
    processed: set = set()

    # Detect India two-file pair
    india_orders_idx = india_details_idx = None
    for i, df in enumerate(raw_dfs):
        fmt = _detect_format(df)
        if fmt == "india_orders":          india_orders_idx  = i
        elif fmt == "india_order_details": india_details_idx = i

    if india_orders_idx is not None and india_details_idx is not None:
        try:
            joined = _parse_india_joined(raw_dfs[india_orders_idx], raw_dfs[india_details_idx])
            merged_parts.append(joined)
            processed.update([india_orders_idx, india_details_idx])
            # Price = Amount / Quantity per Sub-Category (India datasets have no cost columns)
            det = raw_dfs[india_details_idx].copy()
            det.columns = [c.strip() for c in det.columns]
            if {"Amount","Quantity","Sub-Category"}.issubset(det.columns):
                det["_unit"] = pd.to_numeric(det["Amount"],errors="coerce") / pd.to_numeric(det["Quantity"],errors="coerce").replace(0,np.nan)
                for pid, grp in det.groupby("Sub-Category"):
                    combined_price_map[str(pid).strip()] = float(grp["_unit"].median())
        except Exception as e:
            warnings.warn(f"India join failed: {e}")

    for i, (df, cfg) in enumerate(zip(raw_dfs, configs)):
        if i in processed: continue
        try:
            df_clean, price_map, cost_map = clean_ecommerce_data(df, cfg)
            merged_parts.append(df_clean)
            combined_price_map.update(price_map)
            combined_cost_map.update(cost_map)   # non-empty only for FMCG files
        except Exception as e:
            warnings.warn(f"File {i} could not be parsed: {e}")

    if not merged_parts:
        return pd.DataFrame(columns=["order_purchase_timestamp","product_id","quantity","product_name"]), {}, {}

    merged = pd.concat(merged_parts, ignore_index=True)
    merged = merged.sort_values("order_purchase_timestamp").reset_index(drop=True)
    return merged, combined_price_map, combined_cost_map


def build_daily_sales(df_clean: pd.DataFrame) -> pd.DataFrame:
    """Aggregate to daily sales per product: ds, product_id, product_name, y"""
    df = df_clean.copy()
    df["date"] = df["order_purchase_timestamp"].dt.date
    daily = (
        df.groupby(["date","product_id","product_name"])["quantity"]
        .sum().reset_index()
        .rename(columns={"date":"ds","quantity":"y"})
    )
    daily["ds"] = pd.to_datetime(daily["ds"])
    return daily.sort_values(["product_id","ds"]).reset_index(drop=True)