# Country registration fees (reference)

> **Approximate — rates change.** These are indicative categories to explain to the user, not authoritative figures to compute a final price from. Verify current rates before anyone relies on this for an actual purchase decision. This is the one part of the workflow that isn't queried live via MCP, so it should be revisited periodically.
>
> Every fee below applies on **first local registration**, regardless of whether the car was bought domestically or imported from another EU country — it is a separate question from the customs-duty/VAT logic in the skill (which only depends on used-vs-new/near-new status).

## Germany (DE)
- **Zulassung** (registration) — flat administrative fee, roughly €30–€60 depending on the Zulassungsstelle (local registration office).
- **Kfz-Steuer** (motor vehicle tax) — annual, not one-off; based on engine displacement and CO2/emissions class.
- No BPM/NoVA-style large one-off emissions tax like NL/AT.

## Italy (IT)
- **IPT** (Imposta Provinciale di Trascrizione) — provincial registration tax, varies by province and engine power (kW), typically a few hundred euros for a mid-size car.
- **Bollo auto** — annual ownership tax (not one-off), based on power (kW) and emissions class, varies by region.
- Import from another EU country additionally requires a technical inspection / conformity check at the Motorizzazione if the vehicle doesn't already have an EU certificate of conformity on file.

## France (FR)
- **Carte grise** (certificat d'immatriculation) — one-off registration certificate fee, scales with fiscal horsepower (chevaux fiscaux) and varies by region.
- **Malus écologique** — one-off, CO2-based penalty on registration; can be substantial for higher-emission vehicles, minimal/zero for low-emission ones. Directly usable against `cars-data`'s `co2_g_km` field.

## Netherlands (NL)
- **BPM** (Belasting van Personenauto's en Motorrijwielen) — one-off CO2-based registration tax, often the **largest single line item** in a Dutch import scenario. Applies to used imports too, pro-rated by the vehicle's age/depreciation table, not just new cars.
- Annual **motorrijtuigenbelasting** (road tax) also applies but is ongoing, not a one-off import cost.

## Austria (AT)
- **NoVA** (Normverbrauchsabgabe) — one-off CO2/consumption-based registration tax, conceptually similar to NL's BPM. Applies to both new and imported used vehicles, with a bonus/malus adjustment based on emissions.
- Flat **Zulassungsgebühr** (registration fee) on top, a smaller administrative charge.

## Spain (ES)
- **Impuesto de Matriculación** (registration tax) — one-off, CO2-based, with several bands; many low-emission vehicles fall into a 0% band, higher-emission vehicles pay a percentage of the vehicle's value.
- Regional **tasa de tráfico** (traffic/registration administrative fee) also applies, smaller amount.

## Poland (PL)
- **Akcyza** (excise duty) — one-off, due on **first Polish registration of a vehicle not previously registered in Poland**, which — unlike the other 6 markets — applies to used EU imports too, not just new cars. Rate: 3.1% of vehicle value for engines ≤2000cc, 18.6% for engines >2000cc. Directly usable against `cars-data`'s `power_hp`/displacement if available, or otomoto's `engine_capacity_cc` field.
- **Opłata recyklingowa** (recycling fee) — small flat one-off fee (order of a few hundred PLN) on first registration of an imported vehicle.
- Call this akcyza point out explicitly for PL rows: it's an extra cost step the used-car "no duty/VAT" rule in this skill does **not** cover, since it's a national registration excise, not VAT.

## Portugal (PT)
- **ISV** (Imposto sobre Veículos) — one-off registration tax, calculated from two components: engine displacement and CO2/environmental. Applies to used EU imports too — not exempt — but gets an **age-based discount of 10%–80%** (larger discount for older cars) versus the full new-car rate; since 2025 the discount applies equally to both the displacement and CO2 components. Directly usable against `cars-data`'s `co2_g_km` field for the environmental component.
- 100% electric vehicles are exempt from ISV (and the annual **IUC** road tax).
- Call this out explicitly for PT rows: like Poland's akcyza, this is an extra cost the used-car "no duty/VAT" rule in this skill does **not** cover, since ISV is a national registration tax, not VAT — but unlike akcyza it does at least scale down with vehicle age.

## Czechia (CZ)
- **Registration administrative fee** — flat, small (order of a few hundred to ~800 CZK, roughly €30) regardless of engine size — same class of fee as Germany's Zulassung, not a CO2/value-based tax.
- No BPM/akcyza/ISV/NoVA/malus-style one-off emissions or value-based tax. Used EU imports pay no additional Czech VAT/duty beyond the standard intra-EU used-car rule — Czechia doesn't have Poland's or Portugal's exception here.
- **Silniční daň** (road tax) applies only to vehicles used for business purposes, not private ownership — not relevant for a typical private import scenario.

## Norway (NO)
- **Not an EU member** (EEA/EFTA only) — this is the critical difference from every other market in this skill. Norway sits outside the EU VAT area, so the skill's default "used, private, intra-EU sale = no duty/no VAT" rule **does not apply** to any NO row, whether Norway is the home country or the import source/destination. Treat every NO leg as requiring Norwegian import **moms (VAT, 25%)** on the vehicle's assessed value, regardless of used/new status — this is not an exception to flag alongside the default rule (like Poland/Portugal below), it's a full opt-out from it.
- EEA rules of origin typically zero-rate **customs duty** on cars manufactured in the EU/EEA, but this doesn't extend to VAT.
- **Engangsavgift** (one-off registration tax, due on first Norwegian registration) — historically weight/CO2/NOx-based for combustion vehicles, and typically the largest single cost line for an ICE import; battery-electric vehicles have had substantial exemptions/reductions in recent years (verify current EV treatment, as this has been actively reformed). Cross-reference `cars-data`'s `co2_g_km` for the CO2 component and note that a used import gets an age-based deduction off the full new-vehicle rate, similar in spirit to NL's BPM.
- Call this out prominently for any NO row: both the VAT-area exception and engangsavgift compound (unlike PL/PT, where only the registration tax breaks the default rule) — a NO import calculation genuinely needs live/authoritative figures before anyone relies on it, more so than the other markets here.

## Sweden (SE)
- EU member — the default "used, private, intra-EU sale = no duty/no VAT" rule applies normally, no exception needed (unlike Poland/Portugal/Norway).
- **No large one-off CO2/value-based registration tax** (no BPM/NoVA/malus/ISV/akcyza equivalent) — registration with Transportstyrelsen is a small flat administrative fee, putting Sweden in the same low-registration-friction class as Germany/Czechia.
- **Fordonsskatt** (annual vehicle tax, CO2-based via the "bonus malus" system) applies but is ongoing, not a one-off import cost — don't add it to the one-off registration estimate.

## How the skill should use this file
For the home country and each import candidate, look up the relevant one-off registration tax category, note whether it's CO2-linked (and if so, cross-reference the variant's `co2_g_km` from `cars-data` to say whether it lands in a low/high band — without inventing a precise number), and always state the figure is indicative. Never present a number from this file as if it were fetched live.
