
import io
import warnings
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Union

import numpy as np
import pandas as pd

from app.core.preprocessing import clean_ecommerce_data, build_daily_sales, smart_merge_files

warnings.filterwarnings("ignore")


# ─────────────────────────────────────────────────────────────────────
# Encoding detection
# ─────────────────────────────────────────────────────────────────────

_ENCODINGS = ["utf-8", "utf-8-sig", "latin-1", "iso-8859-1", "cp1252", "utf-16"]


def _read_csv_robust(source: Union[str, Path, bytes, io.IOBase], **kwargs) -> pd.DataFrame:
    """
    Try multiple encodings until CSV loads successfully.
    `source` can be a file path, raw bytes, or file-like object.
    """
    if isinstance(source, (str, Path)):
        raw_bytes = Path(source).read_bytes()
    elif isinstance(source, (bytes, bytearray)):
        raw_bytes = source
    else:
        raw_bytes = source.read()

    for enc in _ENCODINGS:
        try:
            return pd.read_csv(io.BytesIO(raw_bytes), encoding=enc, low_memory=False, **kwargs)
        except (UnicodeDecodeError, pd.errors.ParserError):
            continue

    raise ValueError("Could not decode CSV with any supported encoding.")


# ─────────────────────────────────────────────────────────────────────
# Main ingestion entry point
# ─────────────────────────────────────────────────────────────────────

def ingest_csv(
    source: Union[str, Path, bytes, io.IOBase],
    config: Optional[dict] = None,
) -> Tuple[pd.DataFrame, Dict[str, float]]:
    """
    Load a CSV file and return (daily_sales_df, price_map).

    daily_sales_df columns:
        ds           – date (datetime64)
        product_id   – str
        product_name – str
        y            – float (daily quantity sold)

    Parameters
    ----------
    source : file path / bytes / file-like
    config : optional dict passed to clean_ecommerce_data()

    Returns
    -------
    (daily_sales, price_map)
    """
    raw_df = _read_csv_robust(source)
    df_clean, price_map = clean_ecommerce_data(raw_df, config)
    daily = build_daily_sales(df_clean)
    return daily, price_map


def ingest_multiple_csvs(
    sources: List[Union[str, Path, bytes, io.IOBase]],
    configs: Optional[List[dict]] = None,
) -> Tuple[pd.DataFrame, Dict[str, float]]:
    """
    Ingest and merge multiple CSV files.

    Returns
    -------
    (merged_daily_sales, combined_price_map)
    """
    configs = configs or [{}] * len(sources)
    raw_dfs = [_read_csv_robust(s) for s in sources]
    merged_clean, price_map = smart_merge_files(raw_dfs, configs)
    daily = build_daily_sales(merged_clean)
    return daily, price_map


# ─────────────────────────────────────────────────────────────────────
# DB-ready helpers
# ─────────────────────────────────────────────────────────────────────

def daily_sales_to_db_rows(
    daily_df: pd.DataFrame,
    product_id_map: Dict[str, int],
    import_batch: Optional[str] = None,
) -> List[dict]:
    """
    Convert daily_sales DataFrame to list of dicts ready for
    bulk-inserting into the `sales_history` DB table.

    Parameters
    ----------
    daily_df       : output of build_daily_sales() / ingest_csv()
    product_id_map : {product_name_or_str_id: db_integer_id}
    import_batch   : optional batch tag string

    Returns
    -------
    list of dicts with keys: product_id, date, quantity_sold, import_batch
    """
    rows = []
    for _, row in daily_df.iterrows():
        pid = product_id_map.get(str(row["product_id"]))
        if pid is None:
            pid = product_id_map.get(str(row.get("product_name", "")))
        if pid is None:
            continue  # skip unmapped products

        rows.append({
            "product_id":    pid,
            "date":          row["ds"].date() if hasattr(row["ds"], "date") else row["ds"],
            "quantity_sold": int(max(0, round(row["y"]))),
            "import_batch":  import_batch,
        })
    return rows


def get_product_sales_series(
    daily_df: pd.DataFrame,
    product_identifier: str,
    min_days: int = 30,
) -> Optional[pd.DataFrame]:
    """
    Extract a single-product time series from the merged daily_df.

    Parameters
    ----------
    daily_df            : output of ingest_csv()
    product_identifier  : product_id or product_name string
    min_days            : minimum required days (default 30)

    Returns
    -------
    pd.DataFrame with columns [ds, y] or None if insufficient data
    """
    # Try by product_id first, then product_name
    mask = (daily_df["product_id"] == product_identifier) | \
           (daily_df["product_name"] == product_identifier)
    series = daily_df[mask][["ds", "y"]].copy()

    # Fill missing dates with 0
    if len(series) < 2:
        return None

    full_range = pd.date_range(series["ds"].min(), series["ds"].max(), freq="D")
    series = (
        series.set_index("ds")
        .reindex(full_range, fill_value=0)
        .reset_index()
        .rename(columns={"index": "ds"})
    )

    if len(series) < min_days:
        return None

    return series.sort_values("ds").reset_index(drop=True)


def validate_csv_schema(df: pd.DataFrame, required_output_cols: Optional[List[str]] = None) -> dict:
    """
    Run a quick schema check on a raw CSV DataFrame.

    Returns
    -------
    dict with keys: valid (bool), detected_format (str), issues (list of str)
    """
    from app.core.preprocessing import _detect_format

    issues = []
    fmt = _detect_format(df)

    if fmt == "generic":
        issues.append("Format not auto-detected; generic parser will be used.")

    if df.empty:
        issues.append("DataFrame is empty.")

    if len(df) < 30:
        issues.append(f"Only {len(df)} rows found; at least 30 recommended.")

    return {
        "valid":           len(issues) == 0 or (len(issues) == 1 and "generic" in issues[0]),
        "detected_format": fmt,
        "row_count":       len(df),
        "issues":          issues,
    }


# ─────────────────────────────────────────────────────────────────────
# Aliases required by app/core/__init__.py
# ─────────────────────────────────────────────────────────────────────

def aggregate_sales_by_day(
    df_clean: pd.DataFrame,
    product_id: Optional[str] = None,
) -> pd.DataFrame:
    """
    Aggregate cleaned sales data to daily totals.

    Parameters
    ----------
    df_clean   : output of clean_ecommerce_data() — columns:
                 order_purchase_timestamp, product_id, quantity, product_name
    product_id : if given, filter to this product before aggregating

    Returns
    -------
    pd.DataFrame with columns [ds, product_id, product_name, y]
    (same format as build_daily_sales)
    """
    df = df_clean.copy()
    if product_id is not None:
        df = df[df["product_id"].astype(str) == str(product_id)]
    return build_daily_sales(df)


def filter_product(
    daily_df: pd.DataFrame,
    product_identifier: str,
    min_days: int = 30,
) -> Optional[pd.DataFrame]:
    """
    Alias of get_product_sales_series — kept for __init__.py backward-compat.

    Extract [ds, y] series for a single product.
    Returns None if < min_days of data.
    """
    return get_product_sales_series(daily_df, product_identifier, min_days)