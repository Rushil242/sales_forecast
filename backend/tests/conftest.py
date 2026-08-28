"""Shared fixtures.

Tests run against a temporary SQLite file and never touch the developer's
database or the network unless explicitly marked ``network``.
"""

from __future__ import annotations

import os

import numpy as np
import pandas as pd
import pytest

os.environ.setdefault("RETAILIQ_ENVIRONMENT", "test")


@pytest.fixture(scope="session", autouse=True)
def _test_settings(tmp_path_factory):
    """Point the app at a throwaway data directory and database."""
    data_dir = tmp_path_factory.mktemp("retailiq-data")
    os.environ["RETAILIQ_DATA_DIR"] = str(data_dir)
    os.environ["RETAILIQ_DATABASE_URL"] = f"sqlite:///{data_dir / 'test.db'}"

    from app.config import get_settings
    from app.db.session import init_db, reset_engine

    get_settings.cache_clear()
    reset_engine()
    init_db()
    yield
    reset_engine()


@pytest.fixture
def transactions() -> pd.DataFrame:
    """A synthetic but structurally realistic transaction table.

    Built with a fixed seed so assertions are stable. This is test scaffolding,
    not application data -- the app itself never generates observations.
    """
    rng = np.random.default_rng(1234)
    dates = pd.date_range("2023-01-01", periods=400, freq="D")
    # Weekday-heavy pattern, mirroring the real dataset's trading profile.
    weekday_weight = np.array([1.0, 1.1, 1.0, 1.15, 0.85, 0.15, 0.6])

    rows = []
    for product, base in (("Widget A", 40.0), ("Widget B", 12.0)):
        for i, day in enumerate(dates):
            trend = 1.0 + 0.0005 * i
            units = base * trend * weekday_weight[day.dayofweek]
            units = max(0.0, units + rng.normal(0, base * 0.12))
            rows.append({
                "Transaction ID": f"T{i}-{product}",
                "Date": day.strftime("%Y-%m-%d"),
                "Product Name": product,
                "Product Category": "Test",
                "Units Sold": round(units),
                "Unit Price": 9.99,
                "Total Revenue": round(units) * 9.99,
                "Region": "United Kingdom",
            })
    return pd.DataFrame(rows)


@pytest.fixture
def dataset(transactions):
    from app.services.ingestion import build_dataset

    return build_dataset(transactions, "test.csv")


@pytest.fixture
def series(dataset):
    from app.services.series import build_daily_series

    return build_daily_series(dataset, "Widget A")


@pytest.fixture
def short_series() -> pd.Series:
    """A 15-day series, matching the original Zara sample's length."""
    index = pd.date_range("2024-01-01", periods=15, freq="D")
    return pd.Series(np.linspace(8, 14, 15), index=index)


@pytest.fixture
def client():
    from fastapi.testclient import TestClient

    from app.main import create_app

    with TestClient(create_app()) as test_client:
        yield test_client
