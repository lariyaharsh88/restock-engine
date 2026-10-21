"""Synthetic store generator. Produces a catalogue, suppliers and a TRUE daily demand process
with the features that break naive reorder rules: weekend peaks, slow growth or decline,
promo spikes, intermittent SKUs, perishables, lead-time variability and case packs.

Everything is seeded. `python -m sim.generator --seed 7` prints a summary.
"""
from __future__ import annotations

import math
import random
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Dict, List, Optional, Tuple

from engine.schema import Product, Supplier

CATEGORIES = [
    # name, share of SKUs, mean daily demand range, margin range, shelf-life range (None = ambient)
    ("staples", 0.25, (2, 20), (0.08, 0.15), None),
    ("snacks", 0.20, (3, 30), (0.12, 0.25), (60, 180)),
    ("beverages", 0.15, (4, 40), (0.10, 0.20), (90, 240)),
    ("dairy_bakery", 0.15, (5, 35), (0.10, 0.18), (3, 10)),
    ("personal_care", 0.15, (0.3, 6), (0.18, 0.35), None),
    ("household", 0.10, (0.2, 4), (0.15, 0.30), None),
]
DOW_PROFILE = [0.90, 0.88, 0.92, 0.96, 1.05, 1.18, 1.11]  # Mon..Sun, weekend heavy


@dataclass
class SkuTruth:
    sku: str
    base_mean: float
    trend_per_day: float          # multiplicative drift per day (e.g. 0.001 = +0.1%/day)
    dow: List[float]
    intermittent_p: Optional[float]   # if set, demand occurs on a day with this probability
    promo_days: List[Tuple[int, int, float]]  # (start_day, end_day, multiplier)
    dispersion: float             # negative binomial overdispersion (higher = noisier)

    def mean_on(self, day_index: int, d: date) -> float:
        m = self.base_mean * ((1 + self.trend_per_day) ** day_index) * self.dow[d.weekday()]
        for s, e, mult in self.promo_days:
            if s <= day_index <= e:
                m *= mult
        return m


def _neg_binomial(rng: random.Random, mean: float, dispersion: float) -> int:
    """Negative binomial as Gamma-Poisson mixture. dispersion -> 0 gives Poisson."""
    if mean <= 0:
        return 0
    if dispersion <= 1e-9:
        return _poisson(rng, mean)
    shape = 1.0 / dispersion
    lam = rng.gammavariate(shape, mean / shape)
    return _poisson(rng, lam)


def _poisson(rng: random.Random, lam: float) -> int:
    if lam > 50:  # normal approximation keeps it fast for high-volume SKUs
        return max(0, int(round(rng.gauss(lam, math.sqrt(lam)))))
    L = math.exp(-lam)
    k, p = 0, 1.0
    while True:
        p *= rng.random()
        if p <= L:
            return k
        k += 1


@dataclass
class Store:
    products: Dict[str, Product]
    suppliers: Dict[str, Supplier]
    truth: Dict[str, SkuTruth]
    start: date
    seed: int

    def true_demand(self, rng: random.Random, sku: str, day_index: int) -> int:
        t = self.truth[sku]
        d = self.start + timedelta(days=day_index)
        if t.intermittent_p is not None and rng.random() > t.intermittent_p:
            return 0
        m = t.mean_on(day_index, d)
        if t.intermittent_p is not None:
            m = m / t.intermittent_p  # keep the long-run mean equal to base_mean
        return _neg_binomial(rng, m, t.dispersion)


def make_store(seed: int = 7, n_skus: int = 120, start: date = date(2026, 1, 1), horizon_days: int = 365) -> Store:
    rng = random.Random(seed)
    suppliers = {
        "S1": Supplier("S1", "Metro distributor", lead_time_days=2, lead_time_sd_days=0.5, review_period_days=3),
        "S2": Supplier("S2", "FMCG stockist", lead_time_days=4, lead_time_sd_days=1.0, review_period_days=7),
        "S3": Supplier("S3", "Regional wholesaler", lead_time_days=7, lead_time_sd_days=2.0, review_period_days=7, min_order_value=5000),
        "S4": Supplier("S4", "Dairy van", lead_time_days=1, lead_time_sd_days=0.0, review_period_days=1),
    }
    products: Dict[str, Product] = {}
    truth: Dict[str, SkuTruth] = {}
    i = 0
    for cat, share, (lo, hi), (mlo, mhi), shelf in CATEGORIES:
        count = max(1, round(n_skus * share))
        for _ in range(count):
            i += 1
            sku = f"SKU{i:03d}"
            base = math.exp(rng.uniform(math.log(lo), math.log(hi)))
            cost = round(rng.uniform(8, 400), 2)
            margin = rng.uniform(mlo, mhi)
            price = round(cost / (1 - margin), 2)
            pack = rng.choice([1, 1, 6, 12, 24]) if cat != "dairy_bakery" else rng.choice([1, 6, 12])
            sup = "S4" if cat == "dairy_bakery" else rng.choices(["S1", "S2", "S3"], weights=[0.45, 0.35, 0.20])[0]
            sl = rng.randint(*shelf) if shelf else None
            products[sku] = Product(sku, f"{cat.replace('_', ' ').title()} {i}", cat, cost, price, sup, pack, sl)

            r = rng.random()
            trend = 0.0
            if r < 0.15:
                trend = rng.uniform(0.0005, 0.002)     # growing
            elif r < 0.30:
                trend = -rng.uniform(0.0005, 0.002)    # declining
            dow = [max(0.3, v * rng.uniform(0.9, 1.1)) for v in DOW_PROFILE]
            intermittent = rng.uniform(0.15, 0.4) if (base < 1.0 and rng.random() < 0.6) else None
            promos = []
            for _ in range(rng.choice([0, 0, 1, 2])):
                s = rng.randint(30, horizon_days - 15)
                promos.append((s, s + rng.randint(3, 10), rng.uniform(1.8, 3.5)))
            truth[sku] = SkuTruth(sku, base, trend, dow, intermittent, promos, dispersion=rng.uniform(0.05, 0.6))
    return Store(products, suppliers, truth, start, seed)


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, default=7)
    a = ap.parse_args()
    s = make_store(a.seed)
    cats: Dict[str, int] = {}
    for p in s.products.values():
        cats[p.category] = cats.get(p.category, 0) + 1
    print(f"seed {a.seed}: {len(s.products)} SKUs, {len(s.suppliers)} suppliers")
    for c, n in cats.items():
        print(f"  {c:15s} {n}")
    print("  intermittent:", sum(1 for t in s.truth.values() if t.intermittent_p is not None))
    print("  perishable  :", sum(1 for p in s.products.values() if p.shelf_life_days))
    print("  with promos :", sum(1 for t in s.truth.values() if t.promo_days))
