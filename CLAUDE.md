# car_appraisal

Local-vs-import car price comparison, backed by two MCP servers configured in `.mcp.json`:
- `cars-data` — vehicle specs (no pricing).
- `as24-de` / `as24-it` / `as24-fr` / `as24-nl` / `as24-at` / `as24-es` — AutoScout24 listing prices, one server per market.

The comparison workflow (variant enumeration, EU duty/VAT rules, registration-fee lookup, shipping estimate, output format) is defined in `.claude/skills/car-import-appraisal/SKILL.md`. See `README.md` for setup and known limitations.
