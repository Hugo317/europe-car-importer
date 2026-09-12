"""MCP stdio server exposing standvirtual.com (Portugal) car listing search/pricing.

Same tool surface as otomoto-pl (search_listings, price_analysis,
list_makes_models). See standvirtual_client.py for the scraping/parsing logic.
"""
from mcp.server.fastmcp import FastMCP

import standvirtual_client as sv

mcp = FastMCP("standvirtual-pt")


@mcp.tool()
def search_listings(
    make: str,
    model: str | None = None,
    year_from: int | None = None,
    year_to: int | None = None,
    page: int = 1,
) -> dict:
    """Search standvirtual.com (Portugal) car listings, one page (up to 32 results).

    Args:
        make: Make name or standvirtual slug, e.g. "bmw".
        model: Model name or standvirtual slug, e.g. "serie-1". Omit to search the whole make.
        year_from: Minimum first-registration year (inclusive).
        year_to: Maximum first-registration year (inclusive).
        page: 1-indexed page number.
    """
    try:
        return sv.search_listings(make, model, year_from, year_to, page)
    except sv.StandvirtualError as e:
        return {"error": str(e)}


@mcp.tool()
def price_analysis(
    make: str,
    model: str | None = None,
    year_from: int | None = None,
    year_to: int | None = None,
    max_listings: int = 100,
) -> dict:
    """Aggregate price stats (min/p25/median/avg/p75/max, in EUR) over up to
    `max_listings` standvirtual.com listings.

    Args:
        make: Make name or standvirtual slug, e.g. "bmw".
        model: Model name or standvirtual slug, e.g. "serie-1". Omit to search the whole make.
        year_from: Minimum first-registration year (inclusive).
        year_to: Maximum first-registration year (inclusive).
        max_listings: Cap on how many listings to sample (paginates 32 at a time).
    """
    try:
        return sv.price_analysis(make, model, year_from, year_to, max_listings)
    except sv.StandvirtualError as e:
        return {"error": str(e)}


@mcp.tool()
def list_makes_models(make: str, model: str | None = None) -> dict:
    """Validate a make/model (name or slug) against standvirtual.com.

    Checks one specific make/model guess and reports whether it resolved,
    plus the canonical display labels standvirtual reports back.

    Args:
        make: Make name or standvirtual slug, e.g. "bmw".
        model: Model name or standvirtual slug, e.g. "serie-1". Omit to check the make only.
    """
    try:
        return sv.list_makes_models(make, model)
    except sv.StandvirtualError as e:
        return {"error": str(e)}


if __name__ == "__main__":
    mcp.run()
