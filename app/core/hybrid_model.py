"""
  ThesisHybridModel — Two-Stage Forecasting
  Stage 1: Prophet (trend + seasonality)
  Stage 2: XGBoost (residual correction with asymmetric loss)
"""

import warnings
import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")

try:
    from prophet import Prophet
    PROPHET_AVAILABLE = True
except ImportError:
    PROPHET_AVAILABLE = False

try:
    import xgboost as xgb
    XGBOOST_AVAILABLE = True
except ImportError:
    XGBOOST_AVAILABLE = False

MODEL_VERSION = "hybrid_asym_v1"

# Custom asymmetric loss for XGBoost
# Under-forecasting penalised more heavily than over-forecasting

def _asymmetric_loss_grad_hess(penalty_under: float = 5.0, penalty_over: float = 1.0):
    """
    Returns (grad_fn, hess_fn) for XGBoost custom objective.
    Gradient / Hessian of asymmetric squared error:
        L = 0.5 * w * residual²
    where w = penalty_under if residual > 0 (under-forecast) else penalty_over.
    """
    def gradient(predt: np.ndarray, dtrain) -> np.ndarray:
        y = dtrain.get_label()
        residual = y - predt            # positive → under-forecast
        weight = np.where(residual > 0, penalty_under, penalty_over)
        return -weight * residual       # dL/d(predt)

    def hessian(predt: np.ndarray, dtrain) -> np.ndarray:
        y = dtrain.get_label()
        residual = y - predt
        weight = np.where(residual > 0, penalty_under, penalty_over)
        return weight                   # d²L/d(predt)²

    def obj(predt, dtrain):
        return gradient(predt, dtrain), hessian(predt, dtrain)

    return obj


# Feature engineering for residual model

def _build_features(df: pd.DataFrame) -> pd.DataFrame:
    """
    Build temporal + lag features from a df with column 'ds'.
    Returns df with engineered feature columns.
    """
    d = df.copy()
    d["day_of_week"] = pd.to_datetime(d["ds"]).dt.dayofweek
    d["is_weekend"]  = (d["day_of_week"] >= 5).astype(int)
    d["month"]       = pd.to_datetime(d["ds"]).dt.month
    d["day_of_year"] = pd.to_datetime(d["ds"]).dt.dayofyear

    # Rolling mean (needs 'y' or 'residual' column present during training)
    if "residual" in d.columns:
        target_col = "residual"
    elif "y" in d.columns:
        target_col = "y"
    else:
        target_col = None

    if target_col:
        d["rolling_mean_7"] = d[target_col].shift(1).rolling(7, min_periods=1).mean().fillna(0)
        d["lag_7"]          = d[target_col].shift(7).fillna(0)
        d["lag_14"]         = d[target_col].shift(14).fillna(0)
    else:
        d["rolling_mean_7"] = 0.0
        d["lag_7"]          = 0.0
        d["lag_14"]         = 0.0

    return d


FEATURE_COLS = ["day_of_week", "is_weekend", "month", "day_of_year",
                "rolling_mean_7", "lag_7", "lag_14"]


# ThesisHybridModel

class ThesisHybridModel:
    """
    Two-stage demand forecasting model:
      1. Prophet  → baseline trend + seasonality
      2. XGBoost  → corrects Prophet residuals using temporal features
                    with an asymmetric loss that penalises under-forecasting

    Usage
    -----
    model = ThesisHybridModel(penalty_under=5.0)
    model.fit(df)          # df must have columns: ds (datetime), y (quantity)
    forecast = model.predict(future_days=30)
    # forecast has columns: ds, yhat, yhat_lower, yhat_upper
    """

    MIN_ROWS = 30           # minimum training observations required
    MIN_XGB_ROWS = 20       # min rows for XGBoost residual training

    def __init__(
        self,
        penalty_under: float = 5.0,
        penalty_over: float  = 1.0,
        xgb_n_estimators: int  = 200,
        xgb_max_depth: int     = 4,
        xgb_learning_rate: float = 0.05,
    ):
        self.penalty_under    = penalty_under
        self.penalty_over     = penalty_over
        self.xgb_n_estimators = xgb_n_estimators
        self.xgb_max_depth    = xgb_max_depth
        self.xgb_lr           = xgb_learning_rate

        self._prophet_model   = None
        self._xgb_model       = None
        self._xgb_enabled     = False
        self._is_fitted       = False
        self._train_df        = None   # kept for rolling stats at predict time


    def fit(self, df: pd.DataFrame) -> "ThesisHybridModel":
        """
        Train the hybrid model.

        Parameters
        ----------
        df : pd.DataFrame
            Must contain columns:
              - ds : datetime-like
              - y  : numeric (daily quantity sold, non-negative)

        Returns
        -------
        self
        """
        df = self._validate_and_clean(df)

        if len(df) < self.MIN_ROWS:
            raise ValueError(
                f"ThesisHybridModel requires at least {self.MIN_ROWS} days of data "
                f"(got {len(df)})."
            )

        self._train_df = df.copy()

        self._prophet_model = self._fit_prophet(df)

        # In-sample Prophet forecast to get residuals
        prophet_train_forecast = self._prophet_model.predict(
            self._prophet_model.make_future_dataframe(periods=0)
        )
        prophet_train_forecast = prophet_train_forecast[["ds", "yhat"]].copy()
        prophet_train_forecast["ds"] = pd.to_datetime(prophet_train_forecast["ds"])

        merged = df.merge(prophet_train_forecast, on="ds", how="left")
        merged["prophet_yhat"] = merged["yhat"].fillna(merged["y"].mean())
        merged["residual"]     = merged["y"] - merged["prophet_yhat"]

        if XGBOOST_AVAILABLE and len(merged) >= self.MIN_XGB_ROWS:
            self._xgb_model   = self._fit_xgboost(merged)
            self._xgb_enabled = True
        else:
            self._xgb_enabled = False

        self._is_fitted = True
        return self

    def predict(self, future_days: int = 30) -> pd.DataFrame:
        """
        Generate a forecast for the next `future_days` calendar days.

        Parameters
        ----------
        future_days : int
            Number of days ahead to forecast.

        Returns
        -------
        pd.DataFrame with columns:
            ds          – forecast date
            yhat        – point estimate (clipped ≥ 0)
            yhat_lower  – lower bound (Prophet uncertainty or ±20 %)
            yhat_upper  – upper bound
        """
        if not self._is_fitted:
            raise RuntimeError("Model is not fitted yet. Call fit() first.")

        future_df = self._prophet_model.make_future_dataframe(periods=future_days)
        prophet_fc = self._prophet_model.predict(future_df)

        # Keep only the genuinely future rows
        last_train_date = self._train_df["ds"].max()
        future_fc = prophet_fc[
            pd.to_datetime(prophet_fc["ds"]) > last_train_date
        ][["ds", "yhat", "yhat_lower", "yhat_upper"]].copy()
        future_fc["ds"] = pd.to_datetime(future_fc["ds"])
        future_fc = future_fc.reset_index(drop=True)

        if len(future_fc) == 0:
            # Edge-case: return empty with correct schema
            return pd.DataFrame(columns=["ds", "yhat", "yhat_lower", "yhat_upper"])

        if self._xgb_enabled and self._xgb_model is not None:
            residual_correction = self._predict_residuals(future_fc)
            future_fc["yhat"]        += residual_correction
            future_fc["yhat_lower"]  += residual_correction
            future_fc["yhat_upper"]  += residual_correction

        future_fc["yhat"]       = future_fc["yhat"].clip(lower=0)
        future_fc["yhat_lower"] = future_fc["yhat_lower"].clip(lower=0)
        future_fc["yhat_upper"] = future_fc["yhat_upper"].clip(lower=0)

        return future_fc[["ds", "yhat", "yhat_lower", "yhat_upper"]].reset_index(drop=True)


    @property
    def mode(self) -> str:
        """'hybrid' or 'prophet_only'"""
        return "hybrid" if self._xgb_enabled else "prophet_only"

    def get_params(self) -> dict:
        return {
            "penalty_under":    self.penalty_under,
            "penalty_over":     self.penalty_over,
            "xgb_n_estimators": self.xgb_n_estimators,
            "xgb_max_depth":    self.xgb_max_depth,
            "xgb_learning_rate":self.xgb_lr,
            "mode":             self.mode,
        }


    @staticmethod
    def _validate_and_clean(df: pd.DataFrame) -> pd.DataFrame:
        required = {"ds", "y"}
        if not required.issubset(df.columns):
            raise ValueError(f"DataFrame must contain columns {required}. Got: {list(df.columns)}")

        df = df[["ds", "y"]].copy()
        df["ds"] = pd.to_datetime(df["ds"])
        df["y"]  = pd.to_numeric(df["y"], errors="coerce").fillna(0).clip(lower=0)
        df       = df.sort_values("ds").drop_duplicates("ds").reset_index(drop=True)
        return df

    def _fit_prophet(self, df: pd.DataFrame):
        """Fit a Prophet model with daily seasonality."""
        if not PROPHET_AVAILABLE:
            raise ImportError("prophet package is not installed. Run: pip install prophet")

        m = Prophet(
            yearly_seasonality=True,
            weekly_seasonality=True,
            daily_seasonality=False,
            seasonality_mode="multiplicative",
            interval_width=0.80,
            changepoint_prior_scale=0.05,
        )
        m.fit(df[["ds", "y"]])
        return m

    def _fit_xgboost(self, merged: pd.DataFrame):
        """Fit XGBoost on Prophet residuals using asymmetric loss."""
        feat_df   = _build_features(merged)
        X_train   = feat_df[FEATURE_COLS].values
        residuals = merged["residual"].values

        dtrain = xgb.DMatrix(X_train, label=residuals)
        obj    = _asymmetric_loss_grad_hess(self.penalty_under, self.penalty_over)

        params = {
            "max_depth":        self.xgb_max_depth,
            "eta":              self.xgb_lr,
            "subsample":        0.8,
            "colsample_bytree": 0.8,
            "seed":             42,
        }
        booster = xgb.train(
            params,
            dtrain,
            num_boost_round=self.xgb_n_estimators,
            obj=obj,
            verbose_eval=False,
        )
        return booster

    def _predict_residuals(self, future_fc: pd.DataFrame) -> np.ndarray:
        """
        Predict XGBoost residuals for future dates.
        Uses rolling stats from the end of the training series as lag proxy.
        """
        # Build feature rows for each future date
        # We use the last known values from training for lag features
        last_actuals = self._train_df["y"].values
        last_residuals = np.zeros(len(last_actuals))  # approximate

        corrections = np.zeros(len(future_fc))

        for i, row in future_fc.iterrows():
            feat = {
                "ds": row["ds"],
                "residual": 0,   # placeholder, we use lag from history
            }
            tmp = pd.DataFrame([feat])
            tmp["day_of_week"] = pd.to_datetime(row["ds"]).dayofweek
            tmp["is_weekend"]  = int(pd.to_datetime(row["ds"]).dayofweek >= 5)
            tmp["month"]       = pd.to_datetime(row["ds"]).month
            tmp["day_of_year"] = pd.to_datetime(row["ds"]).dayofyear

            # Use last 7/14 days of actual sales as lag proxy
            tmp["rolling_mean_7"] = float(np.mean(last_actuals[-7:]))  if len(last_actuals) >= 7  else float(np.mean(last_actuals))
            tmp["lag_7"]          = float(last_actuals[-7])             if len(last_actuals) >= 7  else float(last_actuals[-1])
            tmp["lag_14"]         = float(last_actuals[-14])            if len(last_actuals) >= 14 else float(last_actuals[-1])

            dtest = xgb.DMatrix(tmp[FEATURE_COLS].values)
            corrections[i] = self._xgb_model.predict(dtest)[0]

        return corrections
