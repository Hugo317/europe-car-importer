"""MCP stdio server exposing sauto.cz (Czech Republic) car listing search/pricing.

Same tool surface as otomoto-pl/standvirtual-pt (search_listings,
price_analysis, list_makes_models), but backed by sauto.cz's genuine JSON
REST API rather than scraped embedded JSON. See sauto_client.py.
"""
from mcp.server.fastmcp import FastMCP

import sauto_client as sc

mcp = FastMCP("sauto-cz")


@mcp.tool()
def search_listings(
    make: str,
    model: str | None = None,
    year_from: int | None = None,
    year_to: int | None = None,
    page: int = 1,
) -> dict:
    """Search sauto.cz (Czech Republic) car listings, one page (up to 40 results).

    Args:
        make: Make name, e.g. "BMW" (matched against sauto's real make list).
        model: Model name, e.g. "Rada 1" / "1 Series" (matched against sauto's
            real model list for that make -- fuzzy on accents/case). Omit to
            search the whole make.
        year_from: Minimum manufacturing year (inclusive).
        year_to: Maximum manufacturing year (inclusive).
        page: 1-indexed page number.
    """
    try:
        return sc.search_listings(make, model, year_from, year_to, page)
    except sc.SautoError as e:
        return {"error": str(e)}


@mcp.tool()
def price_analysis(
    make: str,
    model: str | None = None,
    year_from: int | None = None,
    year_to: int | None = None,
    max_listings: int = 100,
) -> dict:
    """Aggregate price stats (min/p25/median/avg/p75/max) over up to
    `max_listings` sauto.cz listings, in both CZK and EUR (via a live ECB
    reference rate).

    Args:
        make: Make name, e.g. "BMW".
        model: Model name, e.g. "Rada 1". Omit to search the whole make.
        year_from: Minimum manufacturing year (inclusive).
        year_to: Maximum manufacturing year (inclusive).
        max_listings: Cap on how many listings to sample (paginates 40 at a time).
    """
    try:
        return sc.price_analysis(make, model, year_from, year_to, max_listings)
    except sc.SautoError as e:
        return {"error": str(e)}


@mcp.tool()
def list_makes_models(make: str, model: str | None = None) -> dict:
    """Look up a make (and optionally validate a model) against sauto.cz's
    real filter codebook -- returns the actual enumerable model list for the
    make, not a best-effort guess.

    Args:
        make: Make name, e.g. "BMW".
        model: Model name to validate, e.g. "Rada 1". Omit to just list all models for the make.
    """
    try:
        return sc.list_makes_models(make, model)
    except sc.SautoError as e:
        return {"error": str(e)}


if __name__ == "__main__":
    mcp.run()
