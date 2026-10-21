"""Daily demand forecast per SKU.

Design goals, in order: (1) explainable to a shop owner, (2) robust to the two things real
sales files always contain, empty-shelf days and intermittent SKUs, (3) no fitted black box.

Method selection:
  cold_start   fewer than `cold_start_min_days` usable days -> plain mean, wide sd
  intermittent more than 60% of usable days are zero     -> Croston-style: P(sale) * mean(sale size)
  ewma_dow     otherwise -> day-of-week index (shrunk) x exponentially weighted level
"""
from __future__ import annotations

import math
from statistics import mean, pstdev
from typing import List, Optional

from .schema import DemandHistory, Forecast, PolicyParams

DOW_SHRINK_K = 3.0  # pseudo-observations pulling each weekday multiplier toward 1.0


def _usable(history: DemandHistory, window: int):
    """Last `window` days, dropping censored (stockout) days."""
    rows = list(zip(history.dates, history.qty, history.stockout))[-window:]
    return [(d, q) for d, q, so in rows if not so]


def forecast_sku(history: DemandHistory, params: Optional[PolicyParams] = None,
                 fallback_daily_mean: Optional[float] = None) -> Forecast:
    p = params or PolicyParams()
    rows = _usable(history, p.forecast_window_days)
    n = len(rows)
    flat = [1.0] * 7

    if n < p.cold_start_min_days:
        if n == 0:
            m = fallback_daily_mean if fallback_daily_mean is not None else 0.0
        else:
            m = mean(q for _, q in rows)
            if fallback_daily_mean is not None:
                # blend toward the category average until we have enough days of our own
                w = n / p.cold_start_min_days
                m = w * m + (1 - w) * fallback_daily_mean
        sd = max(math.sqrt(max(m, 0.0)), m)  # deliberately wide: we know little
        return Forecast(history.sku, m, sd, flat, n, "cold_start")

    qtys = [q for _, q in rows]
    zero_share = sum(1 for q in qtys if q == 0) / n
    if zero_share > 0.60:
        nonzero = [q for q in qtys if q > 0]
        prob = len(nonzero) / n
        size = mean(nonzero) if nonzero else 0.0
        m = prob * size
        sd = max(pstdev(qtys) if n > 1 else size, math.sqrt(max(m, 0.0)))
        return Forecast(history.sku, m, sd, flat, n, "intermittent")

    overall = mean(qtys)
    if overall <= 0:
        return Forecast(history.sku, 0.0, 0.0, flat, n, "ewma_dow")

    # Day-of-week multipliers with shrinkage toward 1.0 (a weekday seen 3 times barely moves)
    by_dow: List[List[int]] = [[] for _ in range(7)]
    for d, q in rows:
        by_dow[d.weekday()].append(q)
    idx = []
    for k in range(7):
        n_k = len(by_dow[k])
        m_k = mean(by_dow[k]) if n_k else overall
        shrunk = (m_k * n_k + overall * DOW_SHRINK_K) / (n_k + DOW_SHRINK_K)
        idx.append(shrunk / overall)
    norm = mean(idx)
    idx = [i / norm for i in idx]

    # Exponentially weighted level on the deseasonalised series, oldest -> newest
    level = qtys[0] / idx[rows[0][0].weekday()]
    for d, q in rows[1:]:
        level = p.ewma_alpha * (q / idx[d.weekday()]) + (1 - p.ewma_alpha) * level
    level = max(level, 0.0)

    resid = [q - level * idx[d.weekday()] for d, q in rows]
    sd = pstdev(resid) if n > 1 else math.sqrt(level)
    sd = max(sd, math.sqrt(level))  # Poisson floor: demand is never less noisy than counts
    return Forecast(history.sku, level, sd, idx, n, "ewma_dow")
