---
name: car-import-appraisal
description: Compare buying a car locally vs importing it from Germany, Italy, France, Netherlands, Austria, Spain, Poland, Portugal, Czechia, Norway, or Sweden. Use when the user asks whether it's cheaper to buy/import a specific car (make/model, optionally a year range) given their home country, e.g. "is it cheaper to import a BMW 120d into Italy" or "I'm in Germany, is a 2018 Golf GTI cheaper somewhere else in Europe".
allowed-tools: Agent, mcp__cars-data__search_cars, mcp__cars-data__get_specs, mcp__cars-data__compare_variants, mcp__cars-data__filter_cars, mcp__as24-de__search_listings, mcp__as24-de__price_analysis, mcp__as24-de__list_makes_models, mcp__as24-it__search_listings, mcp__as24-it__price_analysis, mcp__as24-it__list_makes_models, mcp__as24-fr__search_listings, mcp__as24-fr__price_analysis, mcp__as24-fr__list_makes_models, mcp__as24-nl__search_listings, mcp__as24-nl__price_analysis, mcp__as24-nl__list_makes_models, mcp__as24-at__search_listings, mcp__as24-at__price_analysis, mcp__as24-at__list_makes_models, mcp__as24-es__search_listings, mcp__as24-es__price_analysis, mcp__as24-es__list_makes_models, mcp__otomoto-pl__search_listings, mcp__otomoto-pl__price_analysis, mcp__otomoto-pl__list_makes_models, mcp__standvirtual-pt__search_listings, mcp__standvirtual-pt__price_analysis, mcp__standvirtual-pt__list_makes_models, mcp__sauto-cz__search_listings, mcp__sauto-cz__price_analysis, mcp__sauto-cz__list_makes_models, mcp__finn-no__search_listings, mcp__finn-no__price_analysis, mcp__finn-no__list_makes_models, mcp__blocket-se__search_listings, mcp__blocket-se__price_analysis, mcp__blocket-se__list_makes_models
---

# Car import appraisal

Answer "is it cheaper to buy this car locally or import it?" using seven data sources:
- `cars-data` MCP: global vehicle specs (no pricing). Use to enumerate the variants/generations that match the requested car and year range.
- `as24-<cc>` MCPs (one per market: `de`, `it`, `fr`, `nl`, `at`, `es`): AutoScout24 listings/pricing, one MCP server per country (the underlying tool only supports a single market per process, so each country is a separate server). Prices are natively in EUR (all Eurozone).
- `otomoto-pl`: otomoto.pl listings/pricing for Poland — a separate, custom-built scraper (not AutoScout24, which doesn't cover PL). Prices are natively in **PLN**; `price_analysis` also returns a EUR-converted figure using a live ECB reference rate, and reports which rate was used — surface that rate to the user rather than treating the EUR figure as exact.
- `standvirtual-pt`: standvirtual.com listings/pricing for Portugal — same underlying platform as `otomoto-pl` (OLX Group), also custom-built. Prices are natively in EUR (no conversion needed). **Quirk**: for makes like BMW, standvirtual's "model" filter is the specific trim number (e.g. `"116"`, `"120"`), not a series/family name (`"1-series"`/`"serie-1"` will silently fail) — use the representative variant name from `cars-data`'s `get_specs` (e.g. `"120d"`) as the model, and verify with `list_makes_models` first.
- `sauto-cz`: sauto.cz listings/pricing for Czechia — a third custom-built server, backed by sauto.cz's genuine JSON REST API (not scraped embedded JSON like the other two custom servers). Prices are natively in **CZK**; `price_analysis` also returns a EUR-converted figure via a live ECB reference rate, same caveat as otomoto-pl's PLN figure. Its `list_makes_models` is more reliable than otomoto-pl/standvirtual-pt's — it returns sauto's actual enumerable model list for a make (via the site's own filter codebook), not a best-effort slug guess, so prefer calling it first to get the exact model name/slug before searching.
- `finn-no`: finn.no listings/pricing for Norway — a fourth custom-built server, scraping the same kind of embedded JSON as otomoto-pl/standvirtual-pt but with a real enumerable make/series/model taxonomy (like sauto-cz's codebook, not a slug guess) — call `list_makes_models` first if the model name is ambiguous. Prices are natively in **NOK**; `price_analysis` also returns a EUR-converted figure via a live ECB reference rate. **Norway is not an EU market** — see step 4, its duty/VAT treatment is fundamentally different from every other market here, not just an exception to the default rule.
- `blocket-se`: blocket.se listings/pricing for Sweden — a fifth custom-built server, same underlying Schibsted "mobility" platform as `finn-no` (even the same make/model taxonomy codes) adapted for blocket.se's domain/currency. Prices are natively in **SEK**; `price_analysis` also returns a EUR-converted figure via a live ECB reference rate. Sweden is a normal EU market — no VAT/duty exception needed, but see `references/registration-fees.md` for its (minimal) registration-fee profile.

## 1. Parse the request

Extract: make + model (and trim if given), a year range (if the user doesn't give one, ask or default to a wide range like 2005–current), and home country.

If the home country isn't one of `de/it/fr/nl/at/es/pl/pt/cz/no/se`: say plainly that pricing data only covers those 11 markets, and ask whether to proceed comparing across those 11 without a true "local" baseline, or stop here. Don't fabricate a local price.

## 2. Enumerate variants (cars-data)

Call `search_cars` with `query="<make> <model>"` and `limit=50`. Dedupe results by `generation_id`. Keep only generations whose `[year_from, year_to]` overlaps the requested year range. For each surviving generation, call `get_specs` on one representative `variant_id` to get `power_hp`, `co2_g_km`, and `price_new_eur`.

Note: `list_generations` requires a `model_id` that isn't reliably obtainable from other tool outputs — don't depend on it. `search_cars` + dedupe is the primary path.

**Guardrail**: work generation-by-generation, not trim-by-trim, to keep the number of downstream pricing calls bounded (11 markets × N generations, not 11 × every trim).

## 3. Price per market (parallel subagents)

Once variants are enumerated (step 2), price all 11 markets (home country + the other 10) in parallel: launch one `general-purpose` subagent per market via the `Agent` tool, all as parallel tool calls in a single message (they're independent — no data dependencies between them). Wait for every subagent to report back before moving to step 4; don't proceed on partial results.

Each subagent starts with zero context, so its prompt must be self-contained. Give each one:

- The make/model and the list of surviving generations with their `[year_from, year_to]` ranges (from step 2).
- The exact MCP tool names it's allowed to use — only that one market's tools (e.g. for Germany: `mcp__as24-de__search_listings`, `mcp__as24-de__price_analysis`, `mcp__as24-de__list_makes_models`). Don't let a subagent touch another market's tools.
- Instruction to call that market's `price_analysis` once per generation with `make`, `model`, and the generation's year range — prefer it (aggregate min/p25/median/avg/p75/max over up to 100 listings) over `search_listings`; use `search_listings` only to pull one or two concrete example listings if useful.
- The market-specific quirks that apply to it, copied from below so the subagent doesn't have to rediscover them:
  - `as24-*` (de/it/fr/nl/at/es): prices natively EUR, no conversion needed.
  - `otomoto-pl`: prices natively PLN; pass make/model as plain names. **Errors** rather than silently falling back to whole-make data if the model isn't recognized — retry with `list_makes_models` or a corrected name before reporting the market unavailable. Report `eur_pln_rate_used` alongside the converted EUR figure (a live spot rate, not fixed).
  - `standvirtual-pt`: prices natively EUR; same error-on-unrecognized-model behavior as otomoto-pl. **Quirk**: its "model" filter is the trim number, not the series/family name (e.g. `"120"`, not `"1-series"`/`"serie-1"`, which silently fails) — use the representative variant name from `cars-data`'s `get_specs` (passed in the brief) as the model, and verify with `list_makes_models` first.
  - `sauto-cz`: prices natively CZK; same error-on-unrecognized-model behavior. Its `list_makes_models` is reliable (real codebook, not a slug guess) — call it first to get the exact model name/slug before searching. Report `eur_czk_rate_used` alongside the converted EUR figure.
  - `finn-no`: prices natively NOK; same error-on-unrecognized-model behavior. Call `list_makes_models` first if the model name is ambiguous — it resolves down to specific trim names (e.g. "120d"), not just the series. Report `eur_nok_rate_used` alongside the converted EUR figure. (Norway's non-EU duty/VAT treatment is handled downstream in step 4 — not this subagent's concern.)
  - `blocket-se`: prices natively SEK; same error-on-unrecognized-model behavior and codebook reliability as finn-no. Report `eur_sek_rate_used` alongside the converted EUR figure.
- The exact shape to report back in, one entry per generation: `{country, generation label/years, currency, native price stats (min/p25/median/avg/p75/max, listing count), EUR price (converted, with the conversion rate used if applicable), status: ok | error | blocked}`. If a tool errors or returns a blocked/challenge response after the retry above, the subagent must report that status explicitly rather than omitting the market — the underlying scrapers can get rate-limited (see README troubleshooting).

Collect all 11 reports before continuing. This step's job for the orchestrator is to write the per-market briefs, launch them together, and merge the structured results — not to call market pricing tools directly.

## 4. EU duty/VAT status

For each generation, determine used vs new/near-new: **used** = age > 6 months **and** mileage > 6,000 km (typical listing mileage is enough to judge this; don't over-engineer). For a private-individual, intra-EU sale of a **used** car: no customs duty, no destination-country VAT (already paid at original EU sale) — state this explicitly per row. For **new/near-new**: flag that destination-country VAT applies on the purchase price and must be added — call this out as the common trap.

**Poland exception**: this VAT-free-if-used rule does not exempt a PL-bound import from Poland's akcyza (excise duty, see step 5) — akcyza is due on first Polish registration regardless of used/new status. Don't let a "used = no extra cost" read carry over to the PL row.

**Portugal exception**: similarly, a PT-bound import is still subject to Portugal's ISV (registration tax, see step 5) even when used — EU used imports get an age-based discount (10%–80%, larger discount for older cars) rather than a full exemption. Don't let "used = no extra cost" carry over to the PT row either.

**Norway exception (not just an exception — a different rule entirely)**: Norway is EEA/EFTA, **not an EU member**, so it sits outside the EU VAT area. The whole premise of this step — "used, private, intra-EU sale ⇒ no duty, no destination VAT" — doesn't hold for any NO row, home or import. Any car entering Norway (regardless of used/new status) is subject to Norwegian import VAT (moms, 25%) on its assessed value, plus the one-off **engangsavgift** registration tax (see `references/registration-fees.md`) on first Norwegian registration. Don't apply the "used = no extra cost" framing to NO at all — state the VAT and engangsavgift exposure explicitly instead of describing it as an exception to the default.

## 5. Registration/fee estimate

Look up the destination country's entry in `references/registration-fees.md` for the relevant one-off registration tax category. If it's CO2-linked (NL's BPM, AT's NoVA, FR's malus, ES's Impuesto de Matriculación), reference the generation's `co2_g_km` from cars-data to say roughly which band it falls in — don't invent a precise euro figure, describe it as indicative.

## 6. Shipping estimate

Neither MCP provides this. Use a rough, clearly-labeled distance-based heuristic (a car-transporter shipping quote is typically on the order of low hundreds of euros within continental Europe, scaling with distance) and note that a real transporter quote will be more accurate. Home-country row shipping = 0 by definition.

## 7. Output

Produce one Markdown table, one row per (generation × country) combination actually evaluated:

| Country | Generation / years | Median price | Duty/VAT status | Registration estimate | Shipping estimate | Total landed cost | Δ vs home |
|---|---|---|---|---|---|---|---|

Follow with a one-line verdict naming the cheapest option and the approximate saving (or stating the home country is already cheapest). Then a caveats footer, always included:

- AutoScout24, otomoto.pl, standvirtual.com, finn.no, and blocket.se data are all scraped, may be rate-limited, blocked, or stale for a given market; sauto.cz uses a real API but is still unofficial/undocumented and could change without notice.
- `cars-data` spec confidence/`last_synced_at` should be surfaced if a field looks low-confidence or old.
- Registration fees and shipping are indicative estimates, not quotes — verify before making a purchase decision.
- Poland's PLN→EUR, Czechia's CZK→EUR, Norway's NOK→EUR, and Sweden's SEK→EUR conversions all use a live spot rate at query time, not a fixed one — note it can drift from the rate at actual purchase/payment time.
- Norway is not an EU market — its VAT/engangsavgift exposure (step 4) applies regardless of used/new status, unlike every other market here.

## 8. Dashboard

After the table and verdict, always also publish a dashboard as an Artifact — don't stop at text/table output. Load the `dataviz` skill (and `artifact-design`) before building it. The dashboard should visualize the same rows as the table, at minimum:

- A bar chart of total landed cost per (country × generation), with the home-country bar visually distinguished, so the cheapest option is obvious at a glance.
- A cost breakdown (stacked bar or similar) per row: median price, registration estimate, shipping estimate — so the user can see what's driving the total, not just the total.
- The verdict and caveats surfaced as text on the dashboard itself, not only in the chat reply.

If a market errored or was blocked, show it as a visibly excluded/greyed entry rather than omitting it silently. Publish this as one artifact per appraisal; on a re-run for the same request, update the same artifact rather than creating a new one.
