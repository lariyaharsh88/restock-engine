"""ReStock engine: explainable replenishment decisions from plain sales history.

Pure functions, no network, no API keys. See docs/LOGIC.md for the maths.
"""
from .schema import Product, Supplier, StockState, DemandHistory, Forecast, Recommendation, Cap, PolicyParams
from .forecast import forecast_sku
from .policy import classify_abc, recommend, protection_period
from .allocate import allocate_budget, apply_min_order_value
from .explain import explain

__all__ = [
    "Product", "Supplier", "StockState", "DemandHistory", "Forecast", "Recommendation", "Cap", "PolicyParams",
    "forecast_sku", "classify_abc", "recommend", "protection_period",
    "allocate_budget", "apply_min_order_value", "explain",
]
