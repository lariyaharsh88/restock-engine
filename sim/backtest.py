"""Day-by-day replay of a store under a replenishment policy.

The simulator knows true demand. Policies only see what a real shop sees: daily sales with an
empty-shelf flag, stock on hand, open orders, product and supplier master data.

Metrics are collected only after `warmup` days so every policy starts with the same history.
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Callable, Dict, List, Optional, Tuple

from engine.schema import DemandHistory, PolicyParams, Product, Recommendation, StockState, Supplier
from engine.run import plan_orders
from .generator import Store, make_store

# A policy receives the visible state and returns {sku: qty_to_order} for SKUs whose supplier is reviewed today.
PolicyFn = Callable[["Visible"], Dict[str, int]]


@dataclass
class Visible:
    today: date
    products: Dict[str, Product]
    suppliers: Dict[str, Supplier]
    stock: Dict[str, StockState]
    history: Dict[str, DemandHistory]
    review_skus: List[str]          # SKUs that can be ordered today
    budget: Optional[float]         # cash available for today's orders (None = unlimited)


@dataclass
class Metrics:
    days: int
    demand_units: int = 0
    sold_units: int = 0
    lost_units: int = 0
    sku_days: int = 0
    stockout_sku_days: int = 0
    waste_units: int = 0
    waste_value: float = 0.0
    realised_margin: float = 0.0
    lost_margin: float = 0.0
    cogs_sold: float = 0.0
    inventory_value_sum: float = 0.0   # summed over days, divide by days for average
    orders_placed: int = 0
    order_lines: int = 0
    purchase_value: float = 0.0

    def summary(self) -> Dict[str, float]:
        avg_inv = self.inventory_value_sum / max(self.days, 1)
        turns = (self.cogs_sold / avg_inv) * (365 / max(self.days, 1)) if avg_inv > 0 else 0.0
        return {
            "fill_rate": self.sold_units / max(self.demand_units, 1),
            "stockout_sku_days_pct": self.stockout_sku_days / max(self.sku_days, 1),
            "avg_inventory_value": avg_inv,
            "inventory_turns_annualised": turns,
            "waste_units": self.waste_units,
            "waste_value": self.waste_value,
            "waste_pct_of_purchases": self.waste_value / max(self.purchase_value, 1),
            "realised_margin": self.realised_margin,
            "lost_margin": self.lost_margin,
            "gmroi": self.realised_margin / avg_inv * (365 / max(self.days, 1)) if avg_inv > 0 else 0.0,
            "orders_placed": self.orders_placed,
            "order_lines": self.order_lines,
            "purchase_value": self.purchase_value,
        }


@dataclass
class _Lot:
    qty: int
    expires_on: Optional[date]


@dataclass
class SimState:
    lots: Dict[str, List[_Lot]] = field(default_factory=dict)
    pipeline: List[Tuple[int, str, int]] = field(default_factory=list)  # (arrival_day, sku, qty)
    hist_dates: Dict[str, List[date]] = field(default_factory=dict)
    hist_qty: Dict[str, List[int]] = field(default_factory=dict)
    hist_so: Dict[str, List[bool]] = field(default_factory=dict)


def _on_hand(state: SimState, sku: str) -> int:
    return sum(l.qty for l in state.lots.get(sku, []))


def _on_order(state: SimState, sku: str) -> int:
    return sum(q for _, s, q in state.pipeline if s == sku)


def run_backtest(policy: PolicyFn, store: Optional[Store] = None, seed: int = 7, days: int = 365, warmup: int = 90,
                 budget_per_day: Optional[float] = None, initial_cover_days: int = 10) -> Dict[str, float]:
    store = store or make_store(seed, horizon_days=days)
    rng = random.Random(seed * 7919 + 1)      # demand draws; same for every policy
    lt_rng = random.Random(seed * 104729 + 2)  # lead-time draws; same for every policy
    state = SimState()
    _budget_state.update({"week": -1, "remaining": 0.0})
    for sku, pr in store.products.items():
        start_qty = int(round(store.truth[sku].base_mean * initial_cover_days))
        exp = store.start + timedelta(days=pr.shelf_life_days) if pr.shelf_life_days else None
        state.lots[sku] = [_Lot(start_qty, exp)]
        state.hist_dates[sku], state.hist_qty[sku], state.hist_so[sku] = [], [], []
    m = Metrics(days=days - warmup)
    sup_of = {sku: store.suppliers[pr.supplier_id] for sku, pr in store.products.items()}

    for day in range(days):
        today = store.start + timedelta(days=day)
        measuring = day >= warmup
        # 1. receive
        arrived = [p for p in state.pipeline if p[0] <= day]
        state.pipeline = [p for p in state.pipeline if p[0] > day]
        for _, sku, qty in arrived:
            pr = store.products[sku]
            exp = today + timedelta(days=pr.shelf_life_days) if pr.shelf_life_days else None
            state.lots[sku].append(_Lot(qty, exp))
        # 2. sell (FEFO)
        for sku, pr in store.products.items():
            demand = store.true_demand(rng, sku, day)
            start_oh = _on_hand(state, sku)
            remaining = demand
            lots = sorted(state.lots[sku], key=lambda l: (l.expires_on is None, l.expires_on or today))
            for lot in lots:
                take = min(lot.qty, remaining)
                lot.qty -= take
                remaining -= take
                if remaining == 0:
                    break
            sold = demand - remaining
            stockout_flag = start_oh == 0 or remaining > 0
            state.hist_dates[sku].append(today)
            state.hist_qty[sku].append(sold)
            state.hist_so[sku].append(stockout_flag)
            # 3. expire
            waste = 0
            for lot in state.lots[sku]:
                if lot.expires_on is not None and lot.expires_on <= today and lot.qty > 0:
                    waste += lot.qty
                    lot.qty = 0
            state.lots[sku] = [l for l in state.lots[sku] if l.qty > 0]
            if measuring:
                m.demand_units += demand
                m.sold_units += sold
                m.lost_units += remaining
                m.sku_days += 1
                m.stockout_sku_days += 1 if start_oh == 0 else 0
                m.waste_units += waste
                m.waste_value += waste * pr.unit_cost
                m.realised_margin += sold * pr.unit_margin
                m.lost_margin += remaining * pr.unit_margin
                m.cogs_sold += sold * pr.unit_cost
                m.inventory_value_sum += _on_hand(state, sku) * pr.unit_cost
        # 4. order (per supplier review cadence)
        review = [sku for sku in store.products if day % sup_of[sku].review_period_days == 0]
        if review:
            vis = Visible(
                today=today, products=store.products, suppliers=store.suppliers,
                stock={s: StockState(s, _on_hand(state, s), _on_order(state, s)) for s in store.products},
                history={s: DemandHistory(s, state.hist_dates[s], state.hist_qty[s], state.hist_so[s]) for s in store.products},
                review_skus=review,
                # cash is released weekly; mid-week reviews draw on the unspent part
                budget=_weekly_budget(day, budget_per_day) if budget_per_day is not None else None,
            )
            orders = policy(vis)
            placed = False
            for sku, qty in orders.items():
                if qty <= 0 or sku not in review:
                    continue
                sup = sup_of[sku]
                lt = max(1, int(round(lt_rng.gauss(sup.lead_time_days, sup.lead_time_sd_days))))
                state.pipeline.append((day + lt, sku, qty))
                placed = True
                if measuring:
                    m.order_lines += 1
                    m.purchase_value += qty * store.products[sku].unit_cost
                if budget_per_day is not None:
                    _spend(day, qty * store.products[sku].unit_cost)
            if placed and measuring:
                m.orders_placed += 1
    return m.summary()


# --- weekly cash budget bookkeeping (module-level because policies are plain functions) ---
_budget_state: Dict[str, float] = {"week": -1, "remaining": 0.0}


def _weekly_budget(day: int, per_day: float) -> float:
    week = day // 7
    if _budget_state["week"] != week:
        _budget_state["week"] = week
        _budget_state["remaining"] = per_day * 7
    return _budget_state["remaining"]


def _spend(day: int, amount: float) -> None:
    _budget_state["remaining"] = max(0.0, _budget_state["remaining"] - amount)


# ---------------------------------------------------------------- policies

def _avg_daily(h: DemandHistory, days: int) -> float:
    q = h.qty[-days:]
    return sum(q) / len(q) if q else 0.0


def policy_gut_feel(v: Visible) -> Dict[str, int]:
    """What most small shops do: when a product looks low (under a week of sales), order two weeks' worth.
    Uses raw sales including empty-shelf days, so it under-orders exactly the products that run out."""
    out: Dict[str, int] = {}
    budget = v.budget
    for sku in v.review_skus:
        pr, h, st = v.products[sku], v.history[sku], v.stock[sku]
        avg = _avg_daily(h, 28)
        if st.inventory_position < 7 * avg:
            qty = int(round(14 * avg))
            if pr.pack_size > 1:
                qty = int(-(-qty // pr.pack_size) * pr.pack_size)
            if budget is not None:
                if qty * pr.unit_cost > budget:
                    continue
                budget -= qty * pr.unit_cost
            if qty > 0:
                out[sku] = qty
    return out


def policy_minmax(v: Visible) -> Dict[str, int]:
    """A better spreadsheet: min = 10 days, max = 30 days of 28-day average, orders in packs."""
    out: Dict[str, int] = {}
    budget = v.budget
    for sku in v.review_skus:
        pr, h, st = v.products[sku], v.history[sku], v.stock[sku]
        avg = _avg_daily(h, 28)
        if st.inventory_position < 10 * avg:
            qty = int(round(30 * avg - st.inventory_position))
            if pr.pack_size > 1:
                qty = int(-(-qty // pr.pack_size) * pr.pack_size)
            if budget is not None:
                if qty * pr.unit_cost > budget:
                    continue
                budget -= qty * pr.unit_cost
            if qty > 0:
                out[sku] = qty
    return out


def make_engine_policy(params: Optional[PolicyParams] = None) -> PolicyFn:
    p = params or PolicyParams()

    def policy_engine(v: Visible) -> Dict[str, int]:
        products = {s: v.products[s] for s in v.review_skus}
        recs: List[Recommendation] = plan_orders(products, v.suppliers, v.stock, v.history, v.today, budget=v.budget, params=p)
        return {r.sku: r.qty for r in recs if r.is_order}

    return policy_engine


POLICIES: Dict[str, PolicyFn] = {
    "gut_feel": policy_gut_feel,
    "min_max": policy_minmax,
    "engine": make_engine_policy(),
}
