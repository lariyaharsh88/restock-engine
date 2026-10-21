# ReStock as a company

The product memo answers one question: is "explainable replenishment from a CSV" a wedge into a real business,
or a nice portfolio piece? This is written as the case to a seed investor, with the assumptions marked so they
can be attacked. Figures marked *(verify)* are from memory of public reports and must be sourced before any
external use.

## 1. The wedge

Every inventory product on the market starts with an integration (POS, ERP, Shopify API) and then does the
maths. ReStock inverts that: the maths first, from files the shop already has. That is the wedge because

- **Zero integration = zero sales cycle.** A distributor rep can run a store's export on a tablet in the shop.
- **Explanation = trust = adoption.** The number one reason replenishment tools get ignored is "I don't know
  why it says 40". Every ReStock line says why.
- **The hard part is the decision, not the data pipe.** Pipes are commodities; a policy that handles censored
  demand, perishables, packs, supplier minimums and cash in a way an owner accepts is the product.

## 2. Who pays, and how much

| Segment | Size (India) | Pain in rupees | Willingness to pay | Channel |
|---|---|---|---|---|
| Kirana and small supermarkets | ~12 to 13 million stores *(verify: commonly cited; Nielsen / Bain)* of which perhaps 1 to 2 million are "organised enough" to export sales | A 1,000-SKU store doing ₹60-80 lakh/yr loses 5 to 10% of sales to empty shelves and 2 to 5% of purchases to expiry *(assumption, from the simulator and trade conversations; verify in pilots)*: ₹4 to 10 lakh a year | Low direct (₹300 to 1,000/month); high indirect through distributors | Distributor and FMCG stockist apps, POS vendors |
| D2C brands (Shopify / marketplaces) | Tens of thousands of active brands *(verify)*; D2C sales estimated at tens of billions of dollars by 2025 *(verify: Avendus / RedSeer)* | Stockouts waste paid acquisition; overstock ties up cash they raised at a cost | ₹5,000 to 25,000/month, comparable to tools they already pay for in dollars | Direct, content, Shopify app store |
| Distributors and stockists | Thousands of regional distributors, hundreds of thousands of sub-stockists *(verify)* | Reps spend visits taking orders by hand; order value per visit is the KPI | Pay per store on the platform | Direct sales to distributor owners |

**Beachhead:** D2C brands with 100 to 500 SKUs. They have clean exports, feel the cash pain, pay in software
budgets, and the ops lead is one person who can decide. Prove retention there, then go to distributors
as the channel into kirana, where ReStock is sold as "the rep's suggested order" and the distributor pays.

## 3. Business model

- **Self-serve SaaS** for D2C: free up to 50 SKUs, ₹4,999/month to 500 SKUs, ₹14,999/month beyond, priced on
  SKU count because that tracks value and is easy to meter from the upload.
- **Per-store licence** sold to distributors: ₹150 to 300 per store per month, bundled into their rep app.
  A distributor with 2,000 stores is a ₹36 to 72 lakh/yr contract.
- **Later: order routing.** When the list is sent to a supplier through us, a take rate on the order is
  possible but changes the relationship with distributors. Not before year two.

Bottom-up TAM at the two prices above: 20,000 D2C brands × ₹60,000/yr = ₹120 crore, plus 1.5 million
organised stores × ₹2,400/yr = ₹360 crore. Roughly a ₹500 crore (~$60M) *(assumptions above)* annual
software opportunity in India alone, before order routing. Enough for a company, not a platform; the platform
story is the order flow.

## 4. Why now

- Every POS and billing app in the segment (Vyapar, Khatabook, Tally, marg, Shopify) now exports clean daily
  sales. Five years ago the data did not exist.
- Distributor digitisation (Udaan, ElasticRun, brand DMS apps, Kirana Club) put a tablet in the rep's hand,
  which is the delivery device for "suggested order".
- Quick-commerce dark stores set a new bar for availability; small retailers lose the customers who notice.
- Cash is expensive. Working capital tied in slow stock has a visible cost again.

## 5. Competition and position

| | What they do | Where ReStock differs |
|---|---|---|
| Inventory Planner, Cogsy, Prediko (Shopify apps) | Forecast and PO suggestions via API integration, priced in dollars for US brands | CSV-first, explanation-first, rupee-priced, handles packs, perishables and supplier minimums natively |
| Vyapar, Khatabook, marg | Billing with low-stock alerts (a threshold, not a forecast) | We are the layer above: the threshold they alert on is the number we compute |
| Udaan, ElasticRun, brand DMS | Marketplaces and distribution; some have "suggested order" based on last order | Ours is supplier-neutral and explains itself; can be embedded in theirs |
| Enterprise (Blue Yonder, RELEX, o9) | Full supply chain planning for chains | Different buyer; irrelevant below ₹100 crore revenue |

Moat, honestly: none at launch. It is built over time from (a) the per-store accuracy record, which becomes
the trust asset, (b) a mapping library from every POS export format to the four-file contract, and
(c) demand pooling across stores in a cluster, which only works with many stores. The explanation layer is a
design choice competitors can copy, but most will not, because their models cannot produce one.

## 6. Go-to-market in order

1. **Pilot with 5 stores and 3 D2C brands** (weeks 1 to 8): shadow then assisted, metrics in `PRD.md` §13.
2. **Publish the pilot numbers** as the case study. The audience is D2C founders and ops leads on LinkedIn
   and in founder groups; the artefact is "we cut stockout days 50% with a CSV".
3. **Shopify app store listing** with the CSV flow intact and a one-click export preset.
4. **One distributor partnership** in one city, reps carry the list, distributor pays per store.
5. **Only then** build the first live integration, chosen by which export format caused the most support tickets.

## 7. What has to be true (and how we find out)

| Assumption | Test | Kill criterion |
|---|---|---|
| Owners will record stockouts if asked at order time | Pilot UI with one-tap "ran out" | < 40% of stockout days recorded after 4 weeks |
| Acceptance of the list crosses 70% | Pilot order logs | < 50% at week 8 with no upward trend |
| The engine's benchmark lift shows up in real stores | Pilot stockout SKU-days and waste | no store improves ≥ 30% on either |
| D2C brands pay ₹5,000/month for it | 10 paid conversations before building integrations | fewer than 3 of 10 pay |
| Distributors see order value per visit rise | One distributor, 200 stores, A/B by route | < 5% lift |

## 8. Scaling the system

V1 is one Python process with in-memory state, which is the right size for a pilot and wrong for a product.
The path, each step triggered by a real limit rather than in advance:

1. **Multi-tenant storage.** Postgres with a tenant id on every table; uploads become datasets with versions
   so a store can see "what changed since last week". Trigger: second paying customer.
2. **Scheduled planning.** A worker runs plans nightly per store and emails or WhatsApps the list.
   Trigger: customers asking for the list instead of opening the app.
3. **Integration layer.** Export presets first (pure parsing), then pull connectors (Shopify, Tally) behind
   the same four-file contract so the engine never changes. Trigger: support tickets about file formats.
4. **Pooled forecasting.** Category and cluster priors for cold-start SKUs, hierarchical shrinkage when a
   distributor has hundreds of stores. Trigger: distributor contract.
5. **Policy upgrades.** Poisson quantiles for slow movers, promo calendar, order consolidation. Each is a
   change in `engine/` with the backtest as the regression test. Trigger: the forecast eval or a pilot metric.
6. **Order routing.** Send the order to the supplier from the app; status and receipts flow back into
   `on_order`. Trigger: distributor partnership.

The engine stays a library of pure functions throughout. That is the architectural bet: the decision logic
is the asset, so it must be testable without a database, a queue or a key.

## 9. Risks that end the company

- Distributors build "suggested order" themselves and give it away. Likely for the simple version; the
  counter is to be the better engine they embed rather than the app they compete with.
- Sales data in the long tail of kirana stores is too dirty to be useful without a POS, and the POS vendors
  own that relationship. Then the business is D2C only, which is smaller but real.
- Stockout flags never get recorded, so the core advantage (censoring) is theoretical. The inference fallback
  in V1.1 is the hedge; the pilot tells us within eight weeks.
