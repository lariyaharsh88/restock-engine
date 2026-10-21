"""ReStock web: upload four CSVs (or use the sample store), get an order list with the reason for every line.

No database, no API keys. State lives in memory per process; the sample dataset is loaded on start.
"""
from __future__ import annotations

import io
import json
import os
from datetime import date, timedelta
from typing import Dict, List, Optional

from fastapi import FastAPI, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from engine.io import load_products, load_sales, load_stock, load_suppliers, validate
from engine.run import plan_orders
from engine.schema import DemandHistory, Product, Recommendation, StockState, Supplier

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SAMPLE = os.path.join(ROOT, "data", "sample")
RESULTS = os.path.join(ROOT, "evals", "results")

app = FastAPI(title="ReStock")
app.mount("/static", StaticFiles(directory=os.path.join(ROOT, "web", "static")), name="static")
templates = Jinja2Templates(directory=os.path.join(ROOT, "web", "templates"))
templates.env.filters["inr"] = lambda v: f"₹{v:,.0f}"
templates.env.filters["pct"] = lambda v: f"{v * 100:.1f}%"
templates.env.filters["num"] = lambda v: f"{v:,.1f}" if isinstance(v, float) else f"{v:,}"


class Dataset:
    def __init__(self, products, suppliers, stock, history, label: str, is_sample: bool):
        self.products: Dict[str, Product] = products
        self.suppliers: Dict[str, Supplier] = suppliers
        self.stock: Dict[str, StockState] = stock
        self.history: Dict[str, DemandHistory] = history
        self.label = label
        self.is_sample = is_sample
        self.issues = validate(products, suppliers, stock, history)
        last = max((h.dates[-1] for h in history.values() if h.dates), default=date.today())
        self.today = last + timedelta(days=1)
        self.budget: Optional[float] = None
        self._recs: Optional[List[Recommendation]] = None

    def recs(self) -> List[Recommendation]:
        if self._recs is None:
            self._recs = plan_orders(self.products, self.suppliers, self.stock, self.history, self.today, budget=self.budget)
        return self._recs

    def set_budget(self, b: Optional[float]) -> None:
        self.budget = b
        self._recs = None


def load_sample() -> Dataset:
    return Dataset(load_products(os.path.join(SAMPLE, "products.csv")), load_suppliers(os.path.join(SAMPLE, "suppliers.csv")),
                   load_stock(os.path.join(SAMPLE, "stock.csv")), load_sales(os.path.join(SAMPLE, "sales.csv")),
                   "Sample store (simulated)", True)


STATE: Dict[str, Dataset] = {"ds": load_sample()}


def _ctx(request: Request, **kw):
    ds = STATE["ds"]
    kw.update(request=request, ds=ds, today=ds.today)
    return kw


def _totals(recs: List[Recommendation], products):
    orders = [r for r in recs if r.is_order]
    return {
        "lines": len(orders),
        "units": sum(r.qty for r in orders),
        "cost": sum(r.line_cost for r in orders),
        "margin_at_stake": sum(r.expected_lost_margin for r in orders),
        "deferred": sum(1 for r in recs if r.status == "deferred"),
        "ok": sum(1 for r in recs if r.status == "ok"),
        "capped": sum(1 for r in orders if any(c.name in ("expiry", "budget", "max_cover") for c in r.caps)),
    }


@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    ds = STATE["ds"]
    recs = ds.recs()
    at_risk = sorted((r for r in recs if r.stockout_risk >= 0.5), key=lambda r: -r.expected_lost_margin)[:8]
    by_sup: Dict[str, Dict] = {}
    for r in recs:
        if r.is_order:
            sid = ds.products[r.sku].supplier_id
            d = by_sup.setdefault(sid, {"name": ds.suppliers[sid].name, "lines": 0, "cost": 0.0})
            d["lines"] += 1
            d["cost"] += r.line_cost
    return templates.TemplateResponse("index.html", _ctx(request, totals=_totals(recs, ds.products), at_risk=at_risk, by_sup=by_sup))


@app.get("/orders", response_class=HTMLResponse)
def orders(request: Request, status: str = "order", supplier: str = ""):
    ds = STATE["ds"]
    recs = [r for r in ds.recs() if (status == "all" or r.status == status)]
    if supplier:
        recs = [r for r in recs if ds.products[r.sku].supplier_id == supplier]
    return templates.TemplateResponse("orders.html", _ctx(request, recs=recs, status=status, supplier=supplier, totals=_totals(ds.recs(), ds.products)))


@app.post("/budget")
def set_budget(budget: str = Form("")):
    b = budget.strip().replace(",", "")
    STATE["ds"].set_budget(float(b) if b else None)
    return RedirectResponse("/orders", status_code=303)


@app.get("/sku/{sku}", response_class=HTMLResponse)
def sku_page(request: Request, sku: str):
    ds = STATE["ds"]
    r = next((x for x in ds.recs() if x.sku == sku), None)
    if r is None:
        return RedirectResponse("/orders", status_code=303)
    h = ds.history.get(sku)
    pts = list(zip(h.dates, h.qty, h.stockout))[-56:] if h else []
    f = r.forecast
    fc = [(ds.today + timedelta(days=i), f.for_day(ds.today + timedelta(days=i))) for i in range(14)] if f else []
    return templates.TemplateResponse("sku.html", _ctx(request, r=r, p=ds.products[sku], s=ds.suppliers[ds.products[sku].supplier_id],
                                                       chart=_chart(pts, fc), history=pts[-14:][::-1]))


def _chart(pts, fc, w=720, h=180):
    """Inline SVG: bars = daily sales (grey = empty-shelf day), line = forecast."""
    vals = [q for _, q, _ in pts] + [v for _, v in fc]
    if not vals:
        return ""
    top = max(max(vals), 1) * 1.15
    n = len(pts) + len(fc)
    bw = (w - 40) / max(n, 1)
    out = [f'<svg viewBox="0 0 {w} {h}" class="chart" role="img" aria-label="sales and forecast">']
    for i, (d, q, so) in enumerate(pts):
        bh = q / top * (h - 30)
        out.append(f'<rect x="{30 + i * bw:.1f}" y="{h - 20 - bh:.1f}" width="{max(bw - 1, 1):.1f}" height="{bh:.1f}" class="{"bar so" if so else "bar"}"><title>{d} sold {q}{" (empty shelf)" if so else ""}</title></rect>')
    path = []
    for j, (d, v) in enumerate(fc):
        x = 30 + (len(pts) + j + 0.5) * bw
        y = h - 20 - v / top * (h - 30)
        path.append(f'{"M" if j == 0 else "L"}{x:.1f},{y:.1f}')
    if path:
        out.append(f'<path d="{" ".join(path)}" class="fc"/>')
        out.append(f'<line x1="{30 + len(pts) * bw:.1f}" y1="10" x2="{30 + len(pts) * bw:.1f}" y2="{h - 20}" class="today"/>')
    out.append(f'<text x="2" y="14" class="axis">{top / 1.15:.0f}</text><text x="2" y="{h - 20}" class="axis">0</text>')
    out.append("</svg>")
    return "".join(out)


@app.get("/backtest", response_class=HTMLResponse)
def backtest(request: Request):
    runs = {}
    for name in ("unconstrained", "budget80"):
        p = os.path.join(RESULTS, f"backtest_{name}.json")
        if os.path.exists(p):
            with open(p) as f:
                runs[name] = json.load(f)
    fe = None
    p = os.path.join(RESULTS, "forecast_eval.json")
    if os.path.exists(p):
        with open(p) as f:
            fe = {k: v for k, v in json.load(f).items() if not k.startswith("_")}
    return templates.TemplateResponse("backtest.html", _ctx(request, runs=runs, forecast_eval=fe))


@app.get("/upload", response_class=HTMLResponse)
def upload_form(request: Request):
    return templates.TemplateResponse("upload.html", _ctx(request, error=None))


@app.post("/upload", response_class=HTMLResponse)
async def upload(request: Request, products: UploadFile = File(...), suppliers: UploadFile = File(...),
                 sales: UploadFile = File(...), stock: UploadFile = File(...), label: str = Form("My store")):
    try:
        def rd(u: UploadFile):
            return io.StringIO((u.file.read()).decode("utf-8-sig"))
        ds = Dataset(load_products(rd(products)), load_suppliers(rd(suppliers)), load_stock(rd(stock)), load_sales(rd(sales)), label or "My store", False)
        ds.recs()
    except Exception as e:  # show the parse error, keep the old dataset
        return templates.TemplateResponse("upload.html", _ctx(request, error=f"{type(e).__name__}: {e}"))
    STATE["ds"] = ds
    return RedirectResponse("/", status_code=303)


@app.post("/reset")
def reset():
    STATE["ds"] = load_sample()
    return RedirectResponse("/", status_code=303)


@app.get("/api/orders")
def api_orders():
    ds = STATE["ds"]
    return [{"sku": r.sku, "qty": r.qty, "status": r.status, "class": r.abc_class, "stockout_risk": round(r.stockout_risk, 3),
             "line_cost": round(r.line_cost, 2), "caps": [c.__dict__ for c in r.caps], "why": r.explanation} for r in ds.recs()]
