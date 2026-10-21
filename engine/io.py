"""CSV in, objects out. The four files a shop can export from any POS, Tally or Shopify.

products.csv   sku,name,category,unit_cost,sell_price,supplier_id,pack_size,shelf_life_days
suppliers.csv  supplier_id,name,lead_time_days,lead_time_sd_days,review_period_days,min_order_value
sales.csv      date,sku,qty_sold,stockout            (stockout: 1 if the shelf was empty that day, optional)
stock.csv      sku,on_hand,on_order
"""
from __future__ import annotations

import csv
import io
from datetime import date, datetime
from typing import Dict, Iterable, List, Optional, Tuple, Union

from .schema import DemandHistory, Product, StockState, Supplier

Source = Union[str, io.StringIO, Iterable[str]]


def _rows(src: Source) -> List[Dict[str, str]]:
    if isinstance(src, str):
        with open(src, newline="", encoding="utf-8-sig") as f:
            return list(csv.DictReader(f))
    return list(csv.DictReader(src))


def _opt_int(v: Optional[str]) -> Optional[int]:
    v = (v or "").strip()
    return int(float(v)) if v else None


def _parse_date(v: str) -> date:
    v = v.strip()
    for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y", "%Y/%m/%d"):
        try:
            return datetime.strptime(v, fmt).date()
        except ValueError:
            continue
    raise ValueError(f"unrecognised date {v!r}; use YYYY-MM-DD")


def load_products(src: Source) -> Dict[str, Product]:
    out = {}
    for r in _rows(src):
        out[r["sku"].strip()] = Product(
            sku=r["sku"].strip(), name=r.get("name", r["sku"]).strip(), category=(r.get("category") or "uncategorised").strip(),
            unit_cost=float(r["unit_cost"]), sell_price=float(r["sell_price"]), supplier_id=r["supplier_id"].strip(),
            pack_size=_opt_int(r.get("pack_size")) or 1, shelf_life_days=_opt_int(r.get("shelf_life_days")),
        )
    return out


def load_suppliers(src: Source) -> Dict[str, Supplier]:
    out = {}
    for r in _rows(src):
        out[r["supplier_id"].strip()] = Supplier(
            supplier_id=r["supplier_id"].strip(), name=r.get("name", r["supplier_id"]).strip(),
            lead_time_days=int(float(r["lead_time_days"])), lead_time_sd_days=float(r.get("lead_time_sd_days") or 0),
            review_period_days=int(float(r.get("review_period_days") or 7)), min_order_value=float(r.get("min_order_value") or 0),
        )
    return out


def load_sales(src: Source) -> Dict[str, DemandHistory]:
    tmp: Dict[str, List[Tuple[date, int, bool]]] = {}
    for r in _rows(src):
        so = (r.get("stockout") or "0").strip().lower() in ("1", "true", "yes", "y")
        tmp.setdefault(r["sku"].strip(), []).append((_parse_date(r["date"]), int(float(r["qty_sold"])), so))
    out = {}
    for sku, rows in tmp.items():
        rows.sort()
        out[sku] = DemandHistory(sku, [d for d, _, _ in rows], [q for _, q, _ in rows], [s for _, _, s in rows])
    return out


def load_stock(src: Source) -> Dict[str, StockState]:
    return {r["sku"].strip(): StockState(r["sku"].strip(), int(float(r["on_hand"])), int(float(r.get("on_order") or 0))) for r in _rows(src)}


def validate(products, suppliers, stock, history) -> List[str]:
    """Problems that would make a recommendation silently wrong. Empty list = good to go."""
    issues = []
    for sku, p in products.items():
        if p.supplier_id not in suppliers:
            issues.append(f"{sku}: supplier {p.supplier_id} not in suppliers.csv")
        if p.sell_price < p.unit_cost:
            issues.append(f"{sku}: sell_price below unit_cost (negative margin)")
        if sku not in history:
            issues.append(f"{sku}: no sales history, will use category average (cold start)")
    for sku in history:
        if sku not in products:
            issues.append(f"{sku}: in sales.csv but not in products.csv (ignored)")
    for sku in stock:
        if sku not in products:
            issues.append(f"{sku}: in stock.csv but not in products.csv (ignored)")
    return issues
