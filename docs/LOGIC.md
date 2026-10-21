# ReStock decision logic

This is the spec the code implements and the tests check. Every formula here has a worked example that
appears, with the same numbers, in `tests/test_engine.py`. If the two ever disagree, the test is right and
this document is stale.

Design rule: **a shop owner must be able to audit any line with a calculator.** That rules out fitted
black-box forecasters in V1 and is why every cap is recorded as a `from -> to: reason` step.

## 1. Inputs

| File | Columns | Notes |
|---|---|---|
| `products.csv` | sku, name, category, unit_cost, sell_price, supplier_id, pack_size, shelf_life_days | shelf_life blank = ambient |
| `suppliers.csv` | supplier_id, name, lead_time_days, lead_time_sd_days, review_period_days, min_order_value | review period = how often you can place an order |
| `sales.csv` | date, sku, qty_sold, stockout | stockout=1 marks an empty-shelf day |
| `stock.csv` | sku, on_hand, on_order | on_order = already ordered, not yet arrived |

The `stockout` flag is the single most important column. A day the shelf was empty is not a day of zero
demand; it is a day we do not know the demand. Treating it as zero makes the forecast fall exactly for the
products that sell out, which is the failure mode of every "average of the last 4 weeks" spreadsheet.

## 2. Forecast (`engine/forecast.py`)

Per SKU, from the last 56 days with empty-shelf days removed:

| Condition | Method | Level | Spread |
|---|---|---|---|
| fewer than 14 usable days | `cold_start` | blend of own mean and category mean, weighted by days/14 | max(sqrt(mean), mean), deliberately wide |
| more than 60% zero days | `intermittent` | P(sale on a day) × mean size of a sale | population sd of the series, floored at sqrt(mean) |
| otherwise | `ewma_dow` | exponentially weighted mean of the deseasonalised series | sd of residuals, floored at sqrt(level) |

Day-of-week index: for weekday k with n_k observations and mean m_k, and overall mean m,

    index_k = ((m_k · n_k + m · 3) / (n_k + 3)) / m,  then renormalised so the seven indices average 1.0

The "+3" is shrinkage: a weekday seen three times moves the multiplier only halfway to its observed value.

Level: `level_t = α · (q_t / index_dow(t)) + (1 − α) · level_{t−1}`, oldest to newest. α is set from the
forecast eval in `evals/` (see `docs/CASE_STUDY.md` for the sweep). The sd floor at sqrt(level) encodes
that count data is never less noisy than Poisson.

Expected demand over a horizon: `Σ level · index_dow(day)` for each day in the horizon.

Worked example (test `test_day_of_week_index_catches_weekend_peak`): 8 weeks of 10/day on weekdays and
20/day on weekends gives Saturday index ≈ 1.45, Monday ≈ 0.76, and a 7-day expectation of 90 ± 8%.

## 3. Order-up-to policy (`engine/policy.py`)

Periodic review: each supplier is reviewed every `review_period_days`. An order placed today must cover
demand until the *next* order can arrive, which is the protection period

    P = lead_time_days + review_period_days

    μ  = expected demand over P                           (day-of-week aware)
    σ  = sqrt( P · sd_daily²  +  mean_daily² · sd_leadtime² )
    SS = z(service level) · σ                              (safety stock)
    S  = μ + SS                                            (order-up-to level)
    IP = on_hand + on_order                                (inventory position)
    raw order = max(0, ceil(S − IP))

Service level by ABC class (class = cumulative share of forecast revenue, A ≤ 70%, B ≤ 90%, C rest):
A 97.5%, B 95%, C 90%. The z values are 1.96, 1.645, 1.28.

Worked example (test `test_order_up_to_math_matches_hand_calculation`): 12/day, sd 4, lead 5, review 4.
P = 9, μ = 108, σ = 4·√9 = 12, SS = 1.96·12 = 23.5, S = 131.5, IP = 40, order = 92.

With lead-time sd 2 on the same SKU: σ = √(9·16 + 144·4) = √720 = 26.8, SS = 52.6. Unreliable suppliers
cost safety stock; the number makes that cost visible.

### Caps, in order

1. **Max cover.** `IP + order ≤ expected demand over 60 days`. Guards against a noisy sd asking for months of stock.
2. **Expiry.** For perishables, units arrive after the lead time and must sell within 80% of their shelf life,
   so `IP + order ≤ expected demand over (lead_time + 0.8 · shelf_life) days`.
3. **Pack rounding.** Round *up* to whole packs, except when the expiry cap bound, in which case round to the
   *nearest* pack. A short pack of milk costs a few sales; an extra pack is waste.

Each cap that changes the quantity is recorded as `Cap(name, qty_before, qty_after, reason)`.

Why rounding changed during development: the first version rounded perishables *down*. On 3-day-shelf-life
dairy in packs of 12 that produced zero orders for days and a 92% fill rate on the category. Nearest-pack
rounding took it to 99% with waste still under 1%. See the case study.

### Risk numbers (what happens if you do not order)

With k = (IP − μ) / σ:

    stockout risk     = 1 − Φ(k)
    expected shortfall = σ · ( φ(k) − k · (1 − Φ(k)) )       (standard normal loss function)
    margin at stake   = expected shortfall · (sell_price − unit_cost)
    priority          = margin at stake / line cost          (rupees of margin protected per rupee spent)

These drive the sort order of the order list and the budget allocation below.

## 4. Cross-SKU constraints (`engine/allocate.py`)

**Cash budget.** Lines are funded greedily in descending priority. A line that does not fit is cut to the
number of whole packs that do; if not even one pack fits it is deferred with the reason recorded. Greedy by
margin-per-rupee is a knapsack heuristic, not an optimum, and that is deliberate: the owner can see why line
7 was funded and line 8 was not.

**Supplier minimum order value.** If the cycle's order to a supplier is below its minimum:
- gap ≤ 30% of the minimum: top up one pack at a time, starting with the SKU with the fewest days of cover,
  until the minimum is met;
- gap > 30%: defer the whole supplier order to the next review. Ordering filler to hit a minimum is how dead
  stock is born.

## 5. Explanation contract (`engine/explain.py`)

Every recommendation renders to one paragraph in this order: how much it sells and on what evidence; how many
days must be covered and why; the target and what is held; the decision; each adjustment as `from -> to:
reason`; what is at stake if skipped. Nothing in the sentence is computed in the template. Every number is a
field on the `Recommendation` object, which the JSON endpoint exposes.

## 6. Parameters

| Parameter | Default | Why |
|---|---|---|
| forecast window | 56 days | long enough for 8 observations per weekday, short enough to track drift |
| EWMA α | see case study | tuned on seeds 1-5, reported on 6-10 |
| DOW shrinkage k | 3 | half-weight after three observations |
| cold-start threshold | 14 days | two weeks before trusting a SKU's own history |
| intermittent threshold | 60% zero days | below this a daily model works; above it, Croston-style |
| service levels | A 97.5 / B 95 / C 90 | classic ABC split, overridable per store |
| expiry sell-through | 80% | leaves a fifth of shelf life as buffer for slow days |
| max cover | 60 days | nobody in this segment should hold two months of anything |
| MOV top-up tolerance | 30% | small gaps are topped up, large gaps wait |

## 7. Known simplifications (and what would change them)

- Normal demand over the protection period. Fine at μ ≥ 10; for slow movers the Poisson tail is fatter, so
  the stated service level is optimistic. Fix: Poisson/negative-binomial quantiles for low-μ SKUs.
- No promo or holiday awareness. Promo weeks are where the engine loses most of its remaining sales. Fix: a
  calendar input that multiplies the forecast, which is an input problem, not a modelling problem.
- One lot age per receipt; no partial expiry within a lot. Fine for a replenishment decision.
- Greedy budget allocation. A proper knapsack would gain little and lose auditability.
- Orders are not consolidated across review points, so the engine places more, smaller lines than the
  baselines. Handling cost is real; V1.1 adds a minimum line quantity and "round the whole order to the
  supplier's delivery day".
