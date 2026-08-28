"""Measure which external signals actually help *this* series, and use only those.

Why this module exists
----------------------
The obvious design is to attach every covariate we can fetch and let the model sort
it out. Measured on the bundled dataset over six rolling windows, that is wrong:

    none        MASE 0.5142
    holiday     MASE 0.5076   +1.28%   <- helps
    calendar    MASE 0.5169   -0.53%   <- hurts
    weather     MASE 0.5153   -0.22%   <- hurts
    all         MASE 0.5147   -0.09%   <- the noise cancels the gain

Calendar features hurt because Chronos-2 already reads day-of-week and seasonality
straight off the timestamps; supplying them again is redundant input that dilutes
attention. Weather carries no signal for a mail-order giftware business. Attaching
everything therefore *destroys* the gain holidays would otherwise have delivered.

So the system measures instead of assuming. For each series it runs a short
rolling-origin evaluation per covariate group, keeps the groups that demonstrably
reduce error, and reports the numbers. For an ice-cream seller weather would win;
for this retailer it does not. That decision is data's to make, not ours.

This doubles as the driver-attribution panel: the same measurement that selects the
groups explains to the user why each was kept or dropped.
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from dataclasses import asdict, dataclass, field

import numpy as np
import pandas as pd

from app.config import get_settings
from app.services.enrichment.base import CovariateFrame
from app.services.forecasting.base import Forecaster
from app.services.forecasting.metrics import mase

LOG = logging.getLogger(__name__)

# A group must beat the no-covariate baseline by at least this much to be kept.
# Anything smaller is inside the noise of a handful of windows.
MIN_IMPROVEMENT_PCT = 0.25


@dataclass
class GroupScore:
    group: str
    mase: float
    delta_pct: float
    helps: bool
    reason: str = ""


@dataclass
class CovariateSelection:
    """The outcome of the measurement, and the evidence behind it."""

    selected: list[str] = field(default_factory=list)
    scores: list[GroupScore] = field(default_factory=list)
    baseline_mase: float | None = None
    selected_mase: float | None = None
    improvement_pct: float = 0.0
    windows: int = 0
    method: str = "skipped"  # measured | cached | skipped | unavailable
    duration_ms: int = 0
    note: str = ""

    def to_dict(self) -> dict:
        return {
            **asdict(self),
            "scores": [asdict(s) for s in self.scores],
        }


def _cache_path(key: str):
    directory = get_settings().data_dir / "cache" / "covariate-selection"
    directory.mkdir(parents=True, exist_ok=True)
    return directory / f"{key}.json"


def load_cached(series: pd.Series, horizon: int, groups: list[str]) -> CovariateSelection | None:
    """Return a previously measured selection for an identical series and horizon."""
    path = _cache_path(_fingerprint(series, horizon, groups))
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text())
        scores = [GroupScore(**s) for s in payload.pop("scores", [])]
        selection = CovariateSelection(**payload, scores=scores)
        selection.method = "cached"
        return selection
    except Exception as exc:
        LOG.debug("Could not read cached covariate selection: %s", exc)
        return None


def store_cached(series: pd.Series, horizon: int, groups: list[str],
                 selection: CovariateSelection) -> None:
    try:
        _cache_path(_fingerprint(series, horizon, groups)).write_text(
            json.dumps(selection.to_dict(), default=str)
        )
    except Exception as exc:
        LOG.debug("Could not cache covariate selection: %s", exc)


def _fingerprint(series: pd.Series, horizon: int, groups: list[str]) -> str:
    payload = json.dumps({
        "n": len(series),
        "start": str(series.index[0].date()),
        "end": str(series.index[-1].date()),
        "sum": round(float(series.sum()), 3),
        "h": horizon,
        "groups": sorted(groups),
    }, sort_keys=True)
    return hashlib.sha256(payload.encode()).hexdigest()[:32]


def _score_config(
    forecaster: Forecaster,
    series: pd.Series,
    horizon: int,
    cuts: list[int],
    groups: list[str] | None,
    per_window: dict[int, CovariateFrame] | None,
) -> float | None:
    """Mean MASE across the cut points for one covariate-group configuration.

    ``groups`` of ``None`` scores the univariate baseline.
    """
    values: list[float] = []
    for cut in cuts:
        train = series.iloc[:cut]
        actual = series.iloc[cut:cut + horizon].to_numpy(dtype="float64")
        if actual.size < horizon:
            continue

        window_cov = None
        if groups and per_window is not None:
            full = per_window.get(cut)
            if full is not None:
                window_cov = full.only(groups)
        try:
            output = forecaster.predict(train, horizon, window_cov)
        except Exception as exc:
            LOG.warning("Covariate selection window at %d failed: %s", cut, exc)
            continue
        score = mase(actual, output.mean, train.to_numpy(dtype="float64"))
        if score is not None and np.isfinite(score):
            values.append(score)

    return float(np.mean(values)) if values else None


def select_covariates(
    forecaster: Forecaster,
    series: pd.Series,
    horizon: int,
    build_window_covariates,
    *,
    available_groups: list[str],
    windows: int = 3,
) -> CovariateSelection:
    """Measure each covariate group and keep the ones that help.

    ``build_window_covariates(train_index, future_index) -> CovariateFrame`` is
    injected so this module never has to know how covariates are fetched.
    """
    started = time.perf_counter()

    if not forecaster.supports_covariates:
        return CovariateSelection(
            method="unavailable",
            note=f"{forecaster.name} cannot consume covariates, so none were attached.",
        )
    if not available_groups:
        return CovariateSelection(
            method="unavailable", note="No covariate sources were available."
        )

    # Cut points, newest first, spaced one horizon apart so holdouts never overlap.
    n = len(series)
    min_train = max(2 * horizon, 60)
    cuts = [n - horizon * (i + 1) for i in range(windows)]
    cuts = [c for c in cuts if c >= min_train]
    if not cuts:
        return CovariateSelection(
            method="skipped",
            note=(
                f"Series of {n} days is too short to measure covariate value at a "
                f"{horizon}-day horizon, so all available groups were attached unmeasured."
            ),
            selected=list(available_groups),
        )

    # Build the covariate frame once per window and slice it per configuration.
    per_window: dict[int, CovariateFrame] = {}
    for cut in cuts:
        train = series.iloc[:cut]
        future_index = pd.date_range(
            train.index[-1] + pd.Timedelta(days=1), periods=horizon, freq="D"
        )
        try:
            per_window[cut] = build_window_covariates(
                pd.DatetimeIndex(train.index), future_index
            )
        except Exception as exc:
            LOG.warning("Could not build covariates for window %d: %s", cut, exc)

    baseline = _score_config(forecaster, series, horizon, cuts, None, None)
    if baseline is None:
        return CovariateSelection(
            method="skipped", note="The baseline evaluation produced no usable score."
        )

    scores: list[GroupScore] = []
    for group in available_groups:
        value = _score_config(forecaster, series, horizon, cuts, [group], per_window)
        if value is None:
            scores.append(GroupScore(group, float("nan"), 0.0, False, "evaluation failed"))
            continue
        delta = (baseline - value) / baseline * 100
        helps = delta >= MIN_IMPROVEMENT_PCT
        scores.append(GroupScore(
            group=group, mase=round(value, 4), delta_pct=round(delta, 2), helps=helps,
            reason=(
                f"reduces error by {delta:.2f}%" if helps
                else f"no measurable benefit ({delta:+.2f}%)"
            ),
        ))

    selected = [s.group for s in scores if s.helps]

    # Verify the combination, since groups that help alone can conflict together.
    selected_mase = baseline
    if selected:
        combined = _score_config(forecaster, series, horizon, cuts, selected, per_window)
        if combined is not None and combined < baseline:
            selected_mase = combined
        elif combined is not None:
            LOG.info(
                "Combined covariates (%s) scored %.4f vs baseline %.4f; dropping all",
                ", ".join(selected), combined, baseline,
            )
            selected, selected_mase = [], baseline

    improvement = (baseline - selected_mase) / baseline * 100 if baseline else 0.0
    duration = int((time.perf_counter() - started) * 1000)

    if selected:
        note = (
            f"Measured over {len(cuts)} rolling windows: "
            + ", ".join(f"{s.group} {s.delta_pct:+.2f}%" for s in scores)
            + f". Kept {', '.join(selected)} for a net {improvement:+.2f}%."
        )
    else:
        note = (
            f"Measured over {len(cuts)} rolling windows and no external signal improved "
            "accuracy on this series ("
            + ", ".join(f"{s.group} {s.delta_pct:+.2f}%" for s in scores)
            + "), so the forecast uses sales history alone."
        )

    LOG.info("Covariate selection in %d ms: %s", duration, note)

    return CovariateSelection(
        selected=selected,
        scores=scores,
        baseline_mase=round(baseline, 4),
        selected_mase=round(selected_mase, 4),
        improvement_pct=round(improvement, 2),
        windows=len(cuts),
        method="measured",
        duration_ms=duration,
        note=note,
    )
