from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Dict, List, Optional


@dataclass(frozen=True)
class Product:
    sku: str
    name: str
    category: str
    unit_cost: float
    sell_price: float
    supplier_id: str
    pack_size: int = 1                      # units per case; orders are rounded to whole packs
    shelf_life_days: Optional[int] = None   # None = non-perishable

    @property
    def unit_margin(self) -> float:
        return self.sell_price - self.unit_cost


@dataclass(frozen=True)
class Supplier:
    supplier_id: str
    name: str
    lead_time_days: int
    lead_time_sd_days: float = 0.0
    review_period_days: int = 7             # how often you can place an order with this supplier
    min_order_value: float = 0.0            # supplier refuses orders below this (0 = no minimum)


@dataclass
class StockState:
    sku: str
    on_hand: int
    on_order: int = 0

    @property
    def inventory_position(self) -> int:
        return self.on_hand + self.on_order


@dataclass
class DemandHistory:
    """Daily sales for one SKU. `stockout[i]` marks a day the shelf was empty, so the
    observed sale is a floor on real demand (censored) and is excluded from estimation."""
    sku: str
    dates: List[date]
    qty: List[int]
    stockout: List[bool] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.stockout:
            self.stockout = [False] * len(self.qty)
        assert len(self.dates) == len(self.qty) == len(self.stockout), "history columns differ in length"


@dataclass
class Forecast:
    sku: str
    daily_mean: float            # deseasonalised level, units/day
    daily_sd: float              # sd of daily demand around the seasonal forecast
    dow_index: List[float]       # 7 multipliers, Monday=0 .. Sunday=6, average 1.0
    n_days_used: int
    method: str                  # "ewma_dow" | "intermittent" | "cold_start"

    def for_day(self, d: date) -> float:
        return self.daily_mean * self.dow_index[d.weekday()]

    def expected(self, start: date, horizon_days: int) -> float:
        """Expected demand over `horizon_days` starting at `start` (inclusive)."""
        from datetime import timedelta
        return sum(self.for_day(start + timedelta(days=i)) for i in range(max(0, horizon_days)))


@dataclass
class Cap:
    name: str          # "pack_rounding" | "expiry" | "max_cover" | "budget" | "min_order_value"
    qty_before: int
    qty_after: int
    reason: str


@dataclass
class Recommendation:
    sku: str
    qty: int
    status: str                      # "order" | "ok" | "deferred"
    abc_class: str
    service_level: float
    protection_days: int
    expected_demand: float           # over the protection period
    safety_stock: float
    order_up_to: float
    inventory_position: int
    days_of_cover: float             # IP / daily forecast
    stockout_risk: float             # P(demand over protection period > IP)
    expected_shortfall_units: float  # E[(demand - IP)+] over protection period
    expected_lost_margin: float      # shortfall * unit margin
    line_cost: float                 # qty * unit cost
    priority: float                  # expected_lost_margin per rupee of line cost (0 if no cost)
    caps: List[Cap] = field(default_factory=list)
    forecast: Optional[Forecast] = None
    explanation: str = ""

    @property
    def is_order(self) -> bool:
        return self.status == "order" and self.qty > 0


@dataclass
class PolicyParams:
    service_levels: Dict[str, float] = field(default_factory=lambda: {"A": 0.975, "B": 0.95, "C": 0.90})
    abc_cutoffs: Dict[str, float] = field(default_factory=lambda: {"A": 0.70, "B": 0.90})  # cumulative revenue share
    expiry_sell_through: float = 0.80   # only stock what can sell within this fraction of shelf life
    max_cover_days: int = 60            # never hold more than this many days of demand
    forecast_window_days: int = 56
    ewma_alpha: float = 0.05            # tuned on simulated seeds 1-5, reported on 6-10 (evals/sweep_alpha.sh)
    cold_start_min_days: int = 14
    mov_topup_tolerance: float = 0.30   # top up to supplier minimum if the gap is <= 30% of it, else defer
