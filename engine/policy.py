"""Periodic-review order-up-to policy with service levels by ABC class.

For each SKU at a review point:
  P   = supplier lead time + review period              (days we must cover with this order)
  mu  = expected demand over P (day-of-week aware)
  sig = sqrt(P * sd_daily^2 + mean_daily^2 * sd_leadtime^2)
  SS  = z(service level of the SKU's ABC class) * sig
  S   = mu + SS                                          (order-up-to level)
  IP  = on hand + on order
  raw = max(0, S - IP)
Then caps, in this order: max cover days, expiry sell-through, pack rounding (up).
Budget and supplier minimums are applied across SKUs in allocate.py.
"""
from __future__ import annotations

import math
from datetime import date
from statistics import NormalDist
from typing import Dict, Iterable, List, Optional

from .schema import Cap, Forecast, PolicyParams, Product, Recommendation, StockState, Supplier

_N = NormalDist()


def z_for(service_level: float) -> float:
    return _N.inv_cdf(min(max(service_level, 0.5), 0.9999))


def normal_loss(k: float) -> float:
    """E[(Z - k)+] for standard normal Z."""
    return _N.pdf(k) - k * (1 - _N.cdf(k))


def protection_period(supplier: Supplier) -> int:
    return supplier.lead_time_days + supplier.review_period_days


def classify_abc(products: Iterable[Product], forecasts: Dict[str, Forecast],
                 params: Optional[PolicyParams] = None) -> Dict[str, str]:
    """A = SKUs making the top 70% of forecast revenue, B = next 20%, C = rest."""
    p = params or PolicyParams()
    rev = {pr.sku: max(forecasts[pr.sku].daily_mean, 0.0) * pr.sell_price for pr in products if pr.sku in forecasts}
    total = sum(rev.values())
    out: Dict[str, str] = {}
    cum = 0.0
    for sku, r in sorted(rev.items(), key=lambda kv: kv[1], reverse=True):
        cum += r
        share = cum / total if total > 0 else 1.0
        if share <= p.abc_cutoffs["A"] or (not out and r > 0):
            out[sku] = "A"
        elif share <= p.abc_cutoffs["B"]:
            out[sku] = "B"
        else:
            out[sku] = "C"
    return out


def _round_up_pack(qty: int, pack: int) -> int:
    return int(math.ceil(qty / pack) * pack) if pack > 1 else qty


def _round_nearest_pack(qty: int, pack: int) -> int:
    return int(round(qty / pack) * pack) if pack > 1 else qty


def recommend(product: Product, supplier: Supplier, stock: StockState, forecast: Forecast,
              today: date, abc_class: str, params: Optional[PolicyParams] = None) -> Recommendation:
    p = params or PolicyParams()
    P = protection_period(supplier)
    sl = p.service_levels.get(abc_class, 0.90)
    mu = forecast.expected(today, P)
    sig = math.sqrt(P * forecast.daily_sd ** 2 + (forecast.daily_mean ** 2) * (supplier.lead_time_sd_days ** 2))
    ss = z_for(sl) * sig
    S = mu + ss
    ip = stock.inventory_position
    caps: List[Cap] = []

    raw = max(0, int(math.ceil(S - ip)))

    # Cap 1: never hold more than max_cover_days of demand
    max_hold = forecast.expected(today, p.max_cover_days)
    if ip + raw > max_hold and raw > 0:
        capped = max(0, int(math.floor(max_hold - ip)))
        caps.append(Cap("max_cover", raw, capped, f"holding more than {p.max_cover_days} days of demand ties up cash"))
        raw = capped

    # Cap 2: perishables. Units arrive after the lead time and must sell within 80% of their shelf life,
    # so the sell window counted from today is lead time + 0.8 * shelf life.
    if product.shelf_life_days and raw > 0:
        sell_days = supplier.lead_time_days + int(product.shelf_life_days * p.expiry_sell_through)
        sellable = forecast.expected(today, sell_days)
        capped = max(0, int(math.floor(sellable - ip)))
        if capped < raw:
            caps.append(Cap("expiry", raw, capped,
                            f"shelf life {product.shelf_life_days}d: can sell ~{sellable:.0f} by day {sell_days}, {ip} already held"))
            raw = capped

    # Cap 3: whole packs. Round up, except expiry-limited lines round to the nearest pack
    # (a short pack costs a few lost sales; an extra pack of a 3-day product is waste).
    expiry_limited = any(c.name == "expiry" for c in caps)
    if product.pack_size > 1 and raw > 0:
        rounded = _round_nearest_pack(raw, product.pack_size) if expiry_limited else _round_up_pack(raw, product.pack_size)
        if rounded != raw:
            caps.append(Cap("pack_rounding", raw, rounded,
                            f"supplier sells packs of {product.pack_size}" + (" (nearest pack: perishable)" if expiry_limited else "")))
            raw = rounded

    # Risk numbers describe the situation if we do NOT order now
    if sig > 0:
        k = (ip - mu) / sig
        risk = 1 - _N.cdf(k)
        shortfall = sig * normal_loss(k)
    else:
        risk = 1.0 if ip < mu else 0.0
        shortfall = max(mu - ip, 0.0)
    lost_margin = shortfall * max(product.unit_margin, 0.0)
    line_cost = raw * product.unit_cost
    priority = (lost_margin / line_cost) if line_cost > 0 else 0.0
    daily = forecast.daily_mean
    cover = (ip / daily) if daily > 0 else float("inf")

    status = "order" if raw > 0 else "ok"
    return Recommendation(
        sku=product.sku, qty=raw, status=status, abc_class=abc_class, service_level=sl,
        protection_days=P, expected_demand=mu, safety_stock=ss, order_up_to=S, inventory_position=ip,
        days_of_cover=cover, stockout_risk=risk, expected_shortfall_units=shortfall,
        expected_lost_margin=lost_margin, line_cost=line_cost, priority=priority, caps=caps, forecast=forecast,
    )
