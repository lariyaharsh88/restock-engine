"""Hand-checkable tests for the decision logic. Each number here is worked in docs/LOGIC.md."""
import math
from datetime import date, timedelta

import pytest

from engine import (Cap, DemandHistory, Forecast, PolicyParams, Product, StockState, Supplier,
                    allocate_budget, apply_min_order_value, classify_abc, explain, forecast_sku, recommend)
from engine.policy import z_for, normal_loss
from engine.run import plan_orders

MON = date(2026, 3, 2)  # a Monday


def history(qty, start=MON, stockout=None):
    return DemandHistory("X", [start + timedelta(days=i) for i in range(len(qty))], list(qty), stockout or [])


# ---------------------------------------------------------------- forecast

def test_cold_start_blends_toward_category_average():
    f = forecast_sku(history([5, 5, 5, 5, 5, 5, 5]), fallback_daily_mean=10.0)   # 7 of 14 days -> 50/50 blend
    assert f.method == "cold_start"
    assert f.daily_mean == pytest.approx(7.5)


def test_no_history_uses_fallback_or_zero():
    assert forecast_sku(history([]), fallback_daily_mean=4.0).daily_mean == 4.0
    assert forecast_sku(history([])).daily_mean == 0.0


def test_stockout_days_are_excluded():
    qty = [10] * 20 + [0] * 8                    # last 8 days the shelf was empty
    so = [False] * 20 + [True] * 8
    f = forecast_sku(history(qty, stockout=so))
    assert f.n_days_used == 20
    assert f.daily_mean == pytest.approx(10.0, abs=1e-6)


def test_intermittent_sku_uses_probability_times_size():
    qty = [0, 0, 0, 0, 2, 0, 0, 0, 0, 2] * 3     # sells 2 units once every 5 days
    f = forecast_sku(history(qty))
    assert f.method == "intermittent"
    assert f.daily_mean == pytest.approx(0.4)
    assert f.dow_index == [1.0] * 7


def test_day_of_week_index_catches_weekend_peak():
    qty = []
    for i in range(56):
        d = MON + timedelta(days=i)
        qty.append(20 if d.weekday() >= 5 else 10)
    f = forecast_sku(history(qty))
    assert f.method == "ewma_dow"
    assert f.dow_index[5] > 1.3 and f.dow_index[0] < 0.9
    assert sum(f.dow_index) / 7 == pytest.approx(1.0)
    assert f.expected(MON, 7) == pytest.approx(5 * 10 + 2 * 20, rel=0.08)


def test_sd_has_poisson_floor():
    f = forecast_sku(history([9] * 30))
    assert f.daily_sd == pytest.approx(3.0)


# ---------------------------------------------------------------- policy

PROD = Product("X", "Tea 250g", "staples", unit_cost=100.0, sell_price=125.0, supplier_id="S", pack_size=1)
SUP = Supplier("S", "Stockist", lead_time_days=5, lead_time_sd_days=0.0, review_period_days=4)


def flat(mean, sd):
    return Forecast("X", mean, sd, [1.0] * 7, 56, "ewma_dow")


def test_order_up_to_math_matches_hand_calculation():
    # 12/day, sd 4, P = 5 + 4 = 9 -> mu 108, sigma 12, z(97.5%) 1.96 -> SS 23.5, S 131.5, IP 40 -> order 92
    r = recommend(PROD, SUP, StockState("X", 40, 0), flat(12, 4), MON, "A")
    assert r.protection_days == 9
    assert r.expected_demand == pytest.approx(108)
    assert r.safety_stock == pytest.approx(1.96 * 12, abs=0.05)
    assert r.qty == 92
    assert r.status == "order"


def test_on_order_counts_toward_position_and_no_order_when_covered():
    r = recommend(PROD, SUP, StockState("X", 40, 100), flat(12, 4), MON, "A")
    assert r.inventory_position == 140
    assert r.qty == 0 and r.status == "ok"


def test_service_level_by_class_changes_safety_stock():
    a = recommend(PROD, SUP, StockState("X", 0, 0), flat(12, 4), MON, "A")
    c = recommend(PROD, SUP, StockState("X", 0, 0), flat(12, 4), MON, "C")
    assert a.safety_stock > c.safety_stock
    assert c.safety_stock == pytest.approx(z_for(0.90) * 12, abs=0.05)


def test_lead_time_variability_adds_safety_stock():
    sup = Supplier("S", "Stockist", 5, lead_time_sd_days=2.0, review_period_days=4)
    r = recommend(PROD, sup, StockState("X", 0, 0), flat(12, 4), MON, "A")
    assert r.safety_stock == pytest.approx(1.96 * math.sqrt(9 * 16 + 144 * 4), abs=0.1)


def test_pack_rounding_rounds_up():
    pr = Product("X", "Tea", "staples", 100, 125, "S", pack_size=12)
    r = recommend(pr, SUP, StockState("X", 40, 0), flat(12, 4), MON, "A")
    assert r.qty == 96
    assert [c.name for c in r.caps] == ["pack_rounding"]
    assert r.caps[0].qty_before == 92


def test_expiry_cap_limits_perishables_and_rounds_nearest():
    milk = Product("X", "Milk", "dairy", 50, 60, "S", pack_size=12, shelf_life_days=3)
    van = Supplier("S", "Van", 1, 0.0, review_period_days=1)
    # 20/day. P = 2 -> S ~ 40 + 1.96*sqrt(2)*5 = 54; IP 0. Sell window = 1 + int(2.4) = 3 days -> 60 sellable -> cap 60 (no bind).
    r = recommend(milk, van, StockState("X", 0, 0), flat(20, 5), MON, "A")
    assert not any(c.name == "expiry" for c in r.caps)
    # With 30 on hand: raw = 24, sellable - IP = 30 -> no bind. With 50 on hand: raw 4, cap 10 -> no bind; rounding nearest only when expiry binds.
    big = Product("X", "Curd", "dairy", 50, 60, "S", pack_size=12, shelf_life_days=2)
    r2 = recommend(big, van, StockState("X", 0, 0), flat(20, 5), MON, "A")   # window = 1 + int(1.6) = 2 days -> 40 sellable, raw ~54
    assert any(c.name == "expiry" for c in r2.caps)
    assert r2.qty == 36   # 40 rounded to nearest pack of 12, not up to 48


def test_max_cover_cap():
    params = PolicyParams(max_cover_days=10)
    r = recommend(PROD, SUP, StockState("X", 0, 0), flat(12, 20), MON, "A", params)   # huge sd would ask for > 10 days
    assert r.qty <= 120
    assert any(c.name == "max_cover" for c in r.caps)


def test_risk_numbers_describe_not_ordering():
    r = recommend(PROD, SUP, StockState("X", 108, 0), flat(12, 4), MON, "A")   # IP equals mean demand
    assert r.stockout_risk == pytest.approx(0.5, abs=1e-6)
    assert r.expected_shortfall_units == pytest.approx(12 * normal_loss(0.0), abs=1e-6)
    assert r.expected_lost_margin == pytest.approx(r.expected_shortfall_units * 25)


def test_abc_classification_by_revenue():
    prods = [Product(f"P{i}", "", "c", 10, 20 if i == 0 else 11, "S") for i in range(5)]
    fc = {"P0": flat(100, 1), "P1": flat(10, 1), "P2": flat(5, 1), "P3": flat(1, 1), "P4": flat(0.1, 1)}
    abc = classify_abc(prods, fc)
    assert abc["P0"] == "A" and abc["P4"] == "C"


# ---------------------------------------------------------------- allocation

def rec(sku, qty, cost, lost_margin, pack=1, cover=5.0):
    from engine.schema import Recommendation
    return Recommendation(sku, qty, "order", "A", 0.975, 9, 0, 0, 0, 0, cover, 0.5, 0, lost_margin, qty * cost,
                          lost_margin / (qty * cost))


def test_budget_funds_highest_margin_at_risk_per_rupee_first():
    products = {"HI": Product("HI", "", "c", 10, 20, "S"), "LO": Product("LO", "", "c", 10, 11, "S")}
    recs = [rec("LO", 50, 10, 20), rec("HI", 50, 10, 400)]
    allocate_budget(recs, products, budget=600)
    hi, lo = {r.sku: r for r in recs}["HI"], {r.sku: r for r in recs}["LO"]
    assert hi.qty == 50 and lo.qty == 10          # 500 for HI, remaining 100 buys 10 LO
    assert lo.caps[-1].name == "budget"


def test_budget_defers_when_not_even_one_pack_fits():
    products = {"A": Product("A", "", "c", 100, 150, "S", pack_size=12)}
    recs = [rec("A", 24, 100, 500, pack=12)]
    allocate_budget(recs, products, budget=1000)
    assert recs[0].status == "deferred" and recs[0].qty == 0


def test_min_order_value_tops_up_small_gap_and_defers_big_gap():
    products = {"A": Product("A", "", "c", 100, 150, "S", pack_size=1), "B": Product("B", "", "c", 100, 150, "S", pack_size=1)}
    sup = {"S": Supplier("S", "Wholesaler", 7, 0, 7, min_order_value=5000)}
    recs = [rec("A", 20, 100, 10, cover=3.0), rec("B", 20, 100, 10, cover=8.0)]   # 4000 total, gap 1000 = 20% -> top up
    apply_min_order_value(recs, products, sup)
    assert sum(r.line_cost for r in recs) >= 5000
    assert {r.sku: r for r in recs}["A"].qty >= {r.sku: r for r in recs}["B"].qty   # fewest cover days topped first
    recs2 = [rec("A", 5, 100, 10)]   # 500 total, gap 90% -> defer
    apply_min_order_value(recs2, products, sup)
    assert recs2[0].status == "deferred" and recs2[0].qty == 0


# ---------------------------------------------------------------- end to end

def test_plan_orders_explains_every_line():
    products = {"X": PROD, "Y": Product("Y", "Soap", "personal_care", 20, 30, "S", pack_size=6)}
    sup = {"S": SUP}
    stock = {"X": StockState("X", 40, 0), "Y": StockState("Y", 500, 0)}
    hist = {"X": history([12] * 56), "Y": history([3] * 56)}
    recs = plan_orders(products, sup, stock, hist, MON)
    by = {r.sku: r for r in recs}
    assert by["X"].is_order and "Order" in by["X"].explanation and "Sells ~12.0/day" in by["X"].explanation
    assert by["Y"].status == "ok" and "Enough for now" in by["Y"].explanation
    assert recs[0].sku == "X"   # orders sort first
