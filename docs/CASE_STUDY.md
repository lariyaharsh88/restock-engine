---
title: "ReStock: an order list a shop owner can argue with"
slug: "restock-engine"
summary: "I built an explainable replenishment engine that runs from four CSV exports with no integrations or API keys. On a simulated 120-SKU store it matches the best spreadsheet policy's fill rate (98.1%) with a third of the inventory and 0.4% waste instead of 45%, and under a cash cap it protects 22% more gross margin than either baseline."
role: "Solo: problem framing, decision logic, simulator, evals, UI, docs"
timeline: "Oct 2026, one week"
tags: ["0→1", "Decision systems", "Evals", "B2B SMB", "Explainability"]
status: "benchmark complete, pilot pending"
metrics:
  - { value: "98.1%", label: "fill rate, equal to the min–max spreadsheet, with 66% less inventory" }
  - { value: "0.4% vs 45%", label: "perishable waste as a share of purchases, engine vs min–max" }
  - { value: "+22%", label: "gross margin under an 80% cash cap vs the best baseline" }
  - { value: "23.7%", label: "7-day forecast WAPE on holdout, vs 24.8% for a 28-day average" }
---

## TL;DR

Small retailers reorder by eye, and the products that sell out are exactly the ones whose "average" looks
low. I built ReStock, a rules-based replenishment engine that reads four CSV exports and writes an order list
in which every line carries a one-paragraph reason. To design against a number before any pilot existed,
I built a store simulator with the failure modes that break spreadsheets (empty-shelf days, weekend peaks,
promos, perishables, case packs, unreliable suppliers) and replayed three policies on it. Everything below
is reproducible from the repo; nothing uses an API key.

**What the numbers are:** means over five simulated stores. **What they are not:** customer results. The
pilot plan that would turn them into customer results is in the PRD.

## The problem, stated so it can be measured

A kirana or small supermarket with 300 to 1,500 SKUs orders three to seven times a week from memory. Two
things go wrong at once and the owner sees neither as a number: empty shelves on the fast sellers, and a bin
of expired stock behind the counter. D2C brands have the same problem with a spreadsheet instead of a memory
and six-week manufacturer lead times instead of a daily van.

I reframed it from "forecast better" to **"produce an order the owner will send unchanged."** That puts
explanation on the critical path and rules out any method that cannot show its arithmetic.

## Why a simulator, and what is in it

No pilot data existed, and I did not want to tune a policy on the first store that said yes. A simulator
also lets every policy see identical demand and lead-time draws, which a real pilot never can.

The simulated store (`sim/generator.py`) has 120 SKUs across six categories, four suppliers (a daily dairy
van, a 2-day metro distributor, a weekly FMCG stockist, a 7-day wholesaler with a ₹5,000 minimum),
weekend-heavy day-of-week profiles, 30% of SKUs with slow trends, promo spikes of 1.8 to 3.5× on half the
SKUs, 8 intermittent SKUs, 60 perishables with 3 to 240 days of shelf life, case packs of 6 to 24, and
negative-binomial demand noise. Policies see only what a shop sees: daily sales with an empty-shelf flag,
stock on hand, open orders, master data.

Baselines: **gut feel** (when stock looks under a week, order two weeks of the 28-day average) and
**min–max** (order up to 30 days when under 10 days, in packs). Both are what the segment actually does.

## The engine in one paragraph

Per SKU: drop empty-shelf days (they are censored, not zero), estimate a day-of-week index with shrinkage and
an exponentially weighted level, floor the noise at Poisson. Per supplier review: cover lead time plus review
period, add safety stock for a service level set by ABC class, subtract what is held and on order, cap by
expiry sell-through and 60 days of cover, round to packs. Across SKUs: fund lines by margin-at-risk per rupee
until the cash runs out, and top up or defer supplier minimums. Then write the sentence. The maths with
worked examples is in `docs/LOGIC.md`; the tests in `tests/` carry the same numbers.

## Results: unconstrained cash

Five seeds, 365 days, 90-day warm-up, means. Reproduce: `python scripts/run_backtest.py`.

| Policy | Fill rate | SKU-days out of stock | Avg inventory | Turns/yr | Waste (% of purchases) | Lost margin | GMROI |
|---|---|---|---|---|---|---|---|
| Gut feel | 90.7% | 8.2% | ₹19.3 L | 38.9 | 24.2% | ₹11.4 L | 7.3 |
| Min–max spreadsheet | 98.1% | 1.8% | ₹39.9 L | 20.3 | 44.7% | ₹2.5 L | 3.8 |
| **ReStock engine** | **98.1%** | **0.9%** | **₹13.6 L** | **59.4** | **0.4%** | **₹2.1 L** | **11.1** |

Min–max reaches the same fill rate by holding three times the stock and throwing away almost half of what
it buys in perishable categories. Gut feel holds more than the engine and still runs out, because it averages
the empty-shelf days into its forecast. Fill-rate standard deviation across seeds was 0.2 points for the
engine, so the equality with min–max is not seed luck.

<Compare before="44.7% (min–max)" after="0.4% (engine)" label="Perishable waste as a share of purchases" />

## Results: cash is short

Weekly cash set to 80% of what the engine spends unconstrained, same budget for every policy, released
weekly. Reproduce: `python scripts/run_backtest.py --budget 0.8`.

| Policy | Fill rate | SKU-days out of stock | Realised gross margin | Lost margin |
|---|---|---|---|---|
| Gut feel | 69.7% | 29.3% | ₹76.5 L | ₹40.3 L |
| Min–max spreadsheet | 70.1% | 30.1% | ₹77.3 L | ₹39.5 L |
| **ReStock engine** | **79.0%** | **14.5%** | **₹94.6 L** | **₹22.1 L** |

With the same money the engine earns 22% more gross margin than min–max and 24% more than gut feel, because
it spends the first rupee on the line with the most margin at risk, not on the line whose rep called first.
The fill rate ceiling here is about 80% by construction; the engine gets to 79%.

## Three things the evals changed

**1. The first forecast lost to a 28-day average.** On seeds 1-5 the engine's 7-day WAPE was 27.2% against
24.2% for a plain average. The exponential smoothing constant of 0.2 was tracking noise. A sweep
(`evals/sweep_alpha.sh`) put the optimum at 0.05. On holdout seeds 6-10 the engine now scores **23.7%**
against **24.8%** for the average and 29.9% for "same as last week". The day-of-week index adds almost
nothing at a 7-day horizon, as it should; it matters for the dairy van, where the horizon is two days.

**2. Rounding down starved the dairy.** The first perishable rule rounded orders down to whole packs so a
3-day product was never over-bought. On 3-day-shelf-life dairy in packs of 12 that produced zero orders for
days: category fill rate 92.3% while the rest of the store sat at 96 to 98%. Counting the sell window from
arrival rather than from today, and rounding to the nearest pack when the expiry cap binds, took dairy to
98.8% with waste still under 1%. That change moved the store's fill rate from 95.7% to 97.1% on the smoke
run and is recorded in `docs/LOGIC.md` and the PRD decision log.

**3. The remaining lost sales are an input problem, not a model problem.** Promo windows (the spike plus the
restock lag after it) carry 5.7% of demand but **58.8% of all lost units**. Fill rate is 99.2% outside them
and 80.5% inside. No amount of smoothing anticipates a 3× spike from history alone, so the V1.1 feature is a
promo and festival calendar the owner fills in, which multiplies the forecast. Cheap to build, and it
targets most of the remaining gap.

## What the engine does worse

It orders little and often: 9,371 order lines a year against 1,832 for min–max at the same fill rate. For a
D2C brand raising POs that is a real handling cost. V1.1 adds a minimum line quantity and consolidation to
the supplier's delivery day; the order-lines guardrail in the PRD exists because of this number.

It also assumes normal demand over the protection period, which overstates the service level on slow movers.
Poisson quantiles for low-volume SKUs are a small change, queued behind the promo calendar because the promo
gap is ten times larger.

## What I would need to believe before calling this a product

- Owners record stockouts when asked at order time. If they do not, the censoring advantage is theoretical
  and the V1.1 inference fallback (zero sales on a ≥3/day SKU = probably empty) has to carry it.
- Acceptance of the list crosses 70% unchanged lines by week four of an assisted pilot. The explanation is the
  bet; the acceptance rate is how the bet is scored.
- The benchmark lift survives real exports. The simulator is deliberately harder than the engine's
  assumptions (promos, overdispersion, lead-time noise), but it is still my simulator.

The pilot plan, kill criteria and the business case are in `docs/PRD.md` §13 and `docs/STARTUP.md`.

## What I'd do differently

Build the simulator first, before a line of policy code. I built the engine first, got a 95.7% fill rate,
and only found the dairy bug by writing a per-category breakdown. The eval harness should have been the first
commit.
