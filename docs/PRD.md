# PRD: ReStock, explainable replenishment for small retailers and D2C sellers

| | |
|---|---|
| Author | Harsh Lariya |
| Status | V1 built; pilot-ready |
| Last updated | 2026-10-14 |
| Companion docs | `LOGIC.md` (the maths), `CASE_STUDY.md` (results), `STARTUP.md` (market and business), `METRICS.md` |

## 1. One-liner

ReStock tells a small retailer **what to order today, how much, from whom, and why**, from the four CSVs any
POS or Shopify store can already export. No integrations, no model training, no API keys. The "why" is the
product: every line is a sentence a shop owner can check with a calculator.

## 2. The problem

A shop with 100 to 2,000 SKUs reorders by eye. The owner walks the shelf, sees what looks low, and orders
"two weeks' worth". This fails in four predictable ways:

1. **It under-orders the best sellers.** The product that ran out on Tuesday shows zero sales for the rest of
   the week, so the "average" the owner remembers is too low, so the next order is too small. The products
   that sell out are the ones that keep selling out.
2. **It over-orders perishables.** Rounding up to a case of a 3-day product is waste. The owner does not see
   the waste as a number; it is a bin behind the counter.
3. **It ignores lead time and supplier reliability.** The wholesaler who takes "5 to 9 days" gets the same
   order quantity as the van that comes every morning.
4. **Cash is the real constraint and nobody allocates it.** When money is short the owner orders in the
   sequence the rep calls, not in the order of margin at risk.

Evidence we have today: a simulated store with these properties, replayed under the common heuristics,
loses 8 to 10% of demand to empty shelves while holding 25 to 45% waste on perishables (`CASE_STUDY.md`).
Evidence we need: three to five pilot stores sharing sales exports (see Rollout).

## 3. Users

| Persona | Situation | Job to be done | What "good" looks like to them |
|---|---|---|---|
| **Owner-operator** of a kirana or small supermarket, 300 to 1,500 SKUs, 3 to 6 suppliers, orders by phone or on a distributor app | Orders 3 to 7 times a week, mostly from memory | "Tell me what to order so I stop running out of the things that sell and stop throwing away the things that don't" | An order list by supplier, in packs, that he trusts enough to send as-is |
| **Ops lead** at a D2C brand, 50 to 500 SKUs, 1 to 3 contract manufacturers with 2 to 6 week lead times, Shopify + marketplaces | Plans POs in a spreadsheet monthly; stockouts kill ad ROAS, overstock kills cash | "Tell me which POs to raise this week and defend the number to the founder" | A PO list with the reasoning written out, and a cash cap she can set |
| **Distributor sales rep** (later) | Visits 40 stores a week with a tablet | "Show the owner a suggested order he will actually accept" | Higher order value per visit, fewer returns |

V1 is built for the first two. The third is the distribution channel (see `STARTUP.md`).

## 4. Goals and non-goals

**Goals**
- G1. Produce an order list from four CSVs in under a minute, with a one-paragraph reason per line.
- G2. On the simulated benchmark, beat the min-max spreadsheet on waste and cash at equal or better fill rate,
  and beat "gut feel" on every metric.
- G3. Under a cash cap, protect more gross margin than any first-come ordering rule.
- G4. Be auditable: no number in the UI that is not a field in the JSON.

**Non-goals (V1)**
- Not a POS, not an accounting tool, not a marketplace. We do not take the order; we write it.
- No machine-learned forecasting. The segment has 56 days of noisy counts per SKU; a fitted model would be
  overfit and unexplainable. Revisit when a store has two years of clean data.
- No multi-location transfer logic.
- No automatic ordering. V1 is assisted; auto-order needs pilot trust first.

## 5. Success metrics

| Type | Metric | Target | Where it comes from |
|---|---|---|---|
| Benchmark | Fill rate vs min-max | ≥ min-max − 1 pt | `evals/results/backtest_unconstrained.json` |
| Benchmark | Waste (% of purchases) | ≤ 2% | same |
| Benchmark | Average inventory vs min-max | ≤ 50% | same |
| Benchmark | Gross margin under 80% cash vs baselines | ≥ +15% | `backtest_budget80.json` |
| Pilot (north star) | **Stockout SKU-days per week** per store | −50% within 8 weeks | store's sales export with stockout flag |
| Pilot | Perishable waste value per week | −50% | owner's bin count, weekly photo |
| Pilot | Order acceptance rate (lines sent unchanged / lines suggested) | ≥ 70% by week 4 | app event log |
| Pilot | Time to produce the weekly order | < 10 min (from 45 to 90 min) | owner diary |
| Guardrail | Average inventory value | not up more than 10% | stock export |
| Guardrail | Lines per order | not more than 1.5× pre-pilot | order log |

Acceptance rate is the honest one. A list the owner edits heavily is a list he does not trust, whatever the
backtest says.

## 6. Scope

| | V1 (built) | V1.1 | V2 |
|---|---|---|---|
| Input | 4 CSVs, upload | Shopify / Tally / Vyapar export presets; WhatsApp a photo of the stock sheet | POS connectors, distributor catalogue sync |
| Forecast | DOW × EWMA, censoring-aware, intermittent, cold start | Promo and festival calendar input | Hierarchical pooling across stores in a cluster |
| Policy | Order-up-to with ABC service levels, expiry cap, pack rounding | Min line quantity, order consolidation to supplier delivery day | Multi-supplier choice by price and reliability |
| Constraints | Cash budget, supplier minimums | Shelf space cap per category | Credit limits per supplier |
| Output | Order list by supplier, SKU page, JSON | WhatsApp-ready order text per supplier | One-tap order into distributor apps |
| Trust | Explanation per line, data checks | "What changed since last week" diff | Accuracy report per store |

MoSCoW for V1 was: **must** = forecast with censoring, order-up-to, packs, expiry, explanation, CSV upload;
**should** = ABC service levels, cash budget, supplier minimum; **could** = SKU chart, JSON API;
**won't** = integrations, auto-order, ML.

## 7. User stories and acceptance criteria

**US-1. Weekly order.** As an owner, I upload four files and get an order list grouped by supplier.
- AC: with the sample store, `/` renders in under 2 s and shows lines, purchase value and margin at risk.
- AC: every line shows quantity in units and in packs, cost, stockout risk and a reason paragraph.
- AC: a line whose quantity was changed by a cap shows the step `from -> to: reason`.

**US-2. Why this number.** As an owner, I click a line and see the arithmetic.
- AC: the SKU page lists forecast method, level, sd, day-of-week indices, protection period, expected demand,
  service level, safety stock, order-up-to, inventory position, risk, shortfall, margin at stake.
- AC: the chart shows the last 8 weeks with empty-shelf days visibly different, and the next 2 weeks of forecast.

**US-3. Short on cash.** As an owner, I type the cash I have and the list re-plans.
- AC: lines are funded by margin at risk per rupee; cut lines show `budget` with the amount that fit;
  unfunded lines move to Deferred with the reason.
- AC: total purchase value never exceeds the budget.

**US-4. Supplier minimum.** As an owner, I am never shown an order the supplier will refuse.
- AC: orders under the minimum are topped up (small gap) or deferred (large gap), and the line says which.

**US-5. Bad data.** As an owner, I am told what is wrong with my files before I trust the list.
- AC: unknown supplier, negative margin, missing history, orphan rows are listed on the Today page; the
  app still plans with what it has (cold start for missing history).

**US-6. Perishables.** As an owner, I am not told to buy a case of something that expires before it sells.
- AC: expiry cap applies and is shown; perishable lines round to the nearest pack, not up.

## 8. Functional requirements

| ID | Requirement | Spec |
|---|---|---|
| FR-1 | Parse the four CSVs with tolerant dates and optional columns | `engine/io.py` |
| FR-2 | Forecast per SKU with censoring, intermittent and cold-start paths | `LOGIC.md` §2 |
| FR-3 | Classify SKUs A/B/C by forecast revenue | `LOGIC.md` §3 |
| FR-4 | Order-up-to quantity with lead-time variability | `LOGIC.md` §3 |
| FR-5 | Caps: max cover, expiry, pack rounding, recorded as steps | `LOGIC.md` §3 |
| FR-6 | Risk, shortfall, margin at stake, priority per line | `LOGIC.md` §3 |
| FR-7 | Cash budget allocation by priority with partial lines | `LOGIC.md` §4 |
| FR-8 | Supplier minimum order value handling | `LOGIC.md` §4 |
| FR-9 | One-paragraph explanation per line, all numbers from the object | `LOGIC.md` §5 |
| FR-10 | Web: Today, Order list (filters, budget), SKU page, Backtest, Upload, JSON | `web/app.py` |
| FR-11 | Reproducible backtest of the engine vs two baselines, written to `evals/results/` | `scripts/run_backtest.py` |

Non-functional: pure Python 3.9+, standard library for the engine (FastAPI and Jinja only for the web),
120 SKUs plan in under 100 ms, no persistent storage of uploaded data.

## 9. Input contract and validation

Listed in `LOGIC.md` §1. Validation (`engine/io.validate`) reports but does not block:
unknown supplier, sell price below cost, SKU without history, rows in sales or stock for unknown SKUs.
Hard failures (bad date, missing required column) return the parse error on the upload page and keep the
previous dataset loaded.

## 10. UX

- **Today**: six numbers (lines, value, margin at risk, SKUs fine, lines trimmed, deferred), orders by
  supplier, the eight SKUs most likely to run out, data checks.
- **Order list**: tabs To order / Fine for now / Deferred / All, supplier filter, cash box, one row per SKU
  with the reason inline and cap chips.
- **SKU**: decision banner, reason, chart, the arithmetic as a two-column table, adjustments, last 14 days.
- **Backtest**: the benchmark tables, with the caveat that they are simulated stores.
- **Upload**: four file inputs and the column contract.

Copy rules: units and packs always both shown; money in rupees with no decimals; risk as a percentage; no
jargon word without the plain word next to it ("safety stock" appears as "safety").

## 11. Edge cases

| Case | Behaviour |
|---|---|
| New SKU, no history | cold start on category average, wide sd, class C |
| SKU sold out every day for two weeks | all days censored; falls back to the earlier window, then cold start |
| Demand spike (promo) | sd rises after the fact; next orders larger; no anticipation in V1 (V1.1 calendar) |
| Supplier lead time longer than shelf life | expiry cap can go to zero; line shows `expiry` with sellable = 0 |
| Pack larger than 60 days of demand | max-cover cap to zero; shown; the owner can still override by hand |
| Budget smaller than one pack of anything | every line deferred with reason; Today shows deferred count |
| on_order larger than target | status ok, no negative orders |
| Duplicate SKU rows in sales | summed per day on load |
| Negative or non-integer qty | parsed as float then int; negative days count as zero demand |

## 12. Risks

| Risk | Likelihood | Mitigation |
|---|---|---|
| Owners do not record stockouts, so censoring never triggers | High | V1.1 infers a stockout day when sales are zero on a SKU that averages ≥ 3/day; ask for a one-tap "ran out" in the order flow |
| Sales exports are messy (SKU names change, returns as negative rows) | High | validation report, name-to-SKU mapping table in V1.1 |
| The benchmark flatters the engine because the simulator and the engine share assumptions | Medium | baselines get the same data; promos, lead-time noise and overdispersion are in the simulator and not in the engine; pilots are the real test |
| Owners over-trust and stop walking the shelf | Low | the explanation makes the inputs visible; a wrong on_hand produces a visibly wrong sentence |
| Order lines multiply (engine orders little and often) | Medium | V1.1 min line quantity and consolidation; guardrail metric |

## 13. Rollout

1. **Shadow (weeks 1-2).** Five stores send weekly exports. We produce lists; owners order as usual. We log
   what we would have ordered vs what they ordered, and what ran out.
2. **Assisted (weeks 3-8).** Owners order from the list, editing freely. Acceptance rate, stockout SKU-days
   and waste are the three numbers reported weekly.
3. **Decision gate.** Continue to V1.1 if acceptance ≥ 70% and stockout SKU-days down ≥ 30% in at least three
   of five stores. Otherwise the problem is trust or data, not maths, and the next work is in the input flow.

## 14. Open questions

- Do owners accept "deferred for budget" lines, or does seeing them create anxiety that leads to over-ordering elsewhere?
- Is the right cash unit per order cycle or per week per supplier?
- Should class C items be allowed to stock out deliberately (service level 80%) to fund A items? The maths says yes; shop owners may not.
- For D2C: should the protection period include the manufacturer's production slot, which is booked, not just lead time?

## 15. Decision log

| Decision | Alternatives considered | Why |
|---|---|---|
| CSV upload, no integrations in V1 | Shopify API, Tally connector | Every POS exports CSV; integrations each cost weeks and an API key; the value is in the decision, not the pipe |
| Order-up-to periodic review | Continuous review (s, Q); EOQ | Small shops order on a cadence set by the supplier, not whenever stock hits a point |
| ABC service levels | One service level for all | 97.5% on C items is cash tied in slow movers; the split is standard and explainable |
| Greedy budget by margin-per-rupee | Knapsack solver; equal pro-rata cuts | Auditable, close to optimal, and pro-rata cuts the best sellers along with the rest |
| Nearest-pack rounding for perishables | Round up everywhere; round down for perishables | Round up wastes; round down starved dairy in the backtest (fill 92% → 99% after the change) |
| Defer rather than fill to supplier minimum when the gap is big | Always fill | Filler becomes dead stock; the 30% tolerance keeps small gaps from blocking an urgent order |
| Simulated benchmark with three policies | Wait for pilot data | Needed a reproducible number to design against; the case study states exactly what it does and does not prove |
