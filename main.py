from __future__ import annotations

from datetime import timedelta
from io import StringIO
from typing import List, Optional

import pandas as pd
import torch
from chronos import ChronosPipeline
from fastapi import FastAPI, File, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel


MODEL_ID = "amazon/chronos-t5-mini"
DEFAULT_PRODUCT = "Cargo Shorts"
DEFAULT_PREDICTION_DAYS = 30


class HistoricalPoint(BaseModel):
    date: str
    units_sold: float


class ForecastPoint(BaseModel):
    date: str
    predicted_units: float
    lower_ci: float
    upper_ci: float


class ForecastResponse(BaseModel):
    product_name: str
    prediction_days: int
    history: List[HistoricalPoint]
    forecast: List[ForecastPoint]


app = FastAPI(title="Agentic AI Data Analyst - Forecast API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


pipeline: Optional[ChronosPipeline] = None


@app.on_event("startup")
def load_model() -> None:
    global pipeline
    if pipeline is None:
        dtype = torch.bfloat16 if torch.cuda.is_available() else torch.float32
        try:
            pipeline = ChronosPipeline.from_pretrained(
                MODEL_ID,
                device_map="auto" if torch.cuda.is_available() else "cpu",
                dtype=dtype,
            )
        except TypeError:
            # Backward compatibility with older chronos/transformers versions.
            pipeline = ChronosPipeline.from_pretrained(
                MODEL_ID,
                device_map="auto" if torch.cuda.is_available() else "cpu",
                torch_dtype=dtype,
            )


def _validate_columns(df: pd.DataFrame) -> None:
    required_columns = {
        "Transaction ID",
        "Date",
        "Product Category",
        "Product Name",
        "Color",
        "Units Sold",
        "Unit Price",
        "Total Revenue",
        "Region",
        "Payment Method",
    }
    missing = sorted(required_columns - set(df.columns))
    if missing:
        raise HTTPException(
            status_code=400,
            detail=f"CSV is missing required columns: {', '.join(missing)}",
        )


def _prepare_daily_series(df: pd.DataFrame, product_name: str) -> pd.Series:
    df = df.copy()
    df["Date"] = pd.to_datetime(df["Date"], format="%Y-%m-%d", errors="coerce")
    df["Units Sold"] = pd.to_numeric(df["Units Sold"], errors="coerce")
    df = df.dropna(subset=["Date", "Units Sold"])  # keep valid rows only

    filtered = df[df["Product Name"] == product_name]
    if filtered.empty:
        raise HTTPException(
            status_code=404,
            detail=f"No rows found for product_name='{product_name}'.",
        )

    daily = filtered.groupby("Date", as_index=True)["Units Sold"].sum().sort_index()

    full_range = pd.date_range(daily.index.min(), daily.index.max(), freq="D")
    daily_continuous = daily.reindex(full_range, fill_value=0.0)
    daily_continuous.index.name = "Date"

    return daily_continuous.astype(float)


def _forecast(series: pd.Series, prediction_days: int) -> tuple[list[HistoricalPoint], list[ForecastPoint]]:
    if pipeline is None:
        raise HTTPException(status_code=500, detail="Forecast model failed to load.")

    context = torch.tensor(series.values, dtype=torch.float32)

    # Pass context positionally for compatibility across chronos versions
    # where the argument is named either `context` or `inputs`.
    quantiles, _ = pipeline.predict_quantiles(
        context,
        prediction_length=prediction_days,
        quantile_levels=[0.1, 0.5, 0.9],
    )

    # Output shapes are typically [batch, prediction_length, num_quantiles]
    if quantiles.ndim == 3:
        q10 = quantiles[0, :, 0]
        q50 = quantiles[0, :, 1]
        q90 = quantiles[0, :, 2]
    else:
        q10 = quantiles[:, 0]
        q50 = quantiles[:, 1]
        q90 = quantiles[:, 2]

    start_forecast_date = series.index.max() + timedelta(days=1)
    future_dates = pd.date_range(start=start_forecast_date, periods=prediction_days, freq="D")

    history = [
        HistoricalPoint(date=idx.strftime("%Y-%m-%d"), units_sold=float(value))
        for idx, value in series.items()
    ]

    forecast = [
        ForecastPoint(
            date=dt.strftime("%Y-%m-%d"),
            predicted_units=max(0.0, float(q50[i])),
            lower_ci=max(0.0, float(q10[i])),
            upper_ci=max(0.0, float(q90[i])),
        )
        for i, dt in enumerate(future_dates)
    ]

    return history, forecast


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "model": MODEL_ID}


@app.post("/api/forecast", response_model=ForecastResponse)
async def forecast_endpoint(
    file: UploadFile = File(...),
    product_name: str = Query(DEFAULT_PRODUCT),
    prediction_days: int = Query(DEFAULT_PREDICTION_DAYS, ge=1, le=180),
) -> ForecastResponse:
    if not file.filename.lower().endswith(".csv"):
        raise HTTPException(status_code=400, detail="Please upload a .csv file.")

    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="Uploaded file is empty.")

    try:
        df = pd.read_csv(StringIO(content.decode("utf-8")))
    except UnicodeDecodeError as exc:
        raise HTTPException(status_code=400, detail="CSV must be UTF-8 encoded.") from exc
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Unable to parse CSV: {exc}") from exc

    _validate_columns(df)
    daily_series = _prepare_daily_series(df, product_name=product_name)
    history, forecast = _forecast(daily_series, prediction_days=prediction_days)

    return ForecastResponse(
        product_name=product_name,
        prediction_days=prediction_days,
        history=history,
        forecast=forecast,
    )
