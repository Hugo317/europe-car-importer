"""MCP stdio server exposing blocket.se (Sweden) car listing search/pricing.

Mirrors the subset of autoscout24-mcp's tool surface that the
car-import-appraisal skill actually calls: search_listings, price_analysis,
list_makes_models. See blocket_client.py for the scraping/parsing logic.
"""
from mcp.server.fastmcp import FastMCP

import blocket_client as bc

mcp = FastMCP("blocket-se")


@mcp.tool()
def search_listings(
    make: str,
    model: str | None = None,
    year_from: int | None = None,
    year_to: int | None = None,
    page: int = 1,
) -> dict:
    """Search blocket.se (Sweden) car listings, one page (up to ~49 results).

    Args:
        make: Make name, e.g. "BMW".
        model: Series or specific model/trim name, e.g. "1-Series" or "120d". Omit to search the whole make.
        year_from: Minimum model year (inclusive).
        year_to: Maximum model year (inclusive).
        page: 1-indexed page number.
    """
    try:
        return bc.search_listings(make, model, year_from, year_to, page)
    except bc.BlocketError as e:
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
    `max_listings` blocket.se listings, in both SEK and EUR (via a live
    ECB reference rate).

    Args:
        make: Make name, e.g. "BMW".
        model: Series or specific model/trim name, e.g. "1-Series" or "120d". Omit to search the whole make.
        year_from: Minimum model year (inclusive).
        year_to: Maximum model year (inclusive).
        max_listings: Cap on how many listings to sample (paginates ~49 at a time).
    """
    try:
        return bc.price_analysis(make, model, year_from, year_to, max_listings)
    except bc.BlocketError as e:
        return {"error": str(e)}


@mcp.tool()
def list_makes_models(make: str, model: str | None = None) -> dict:
    """Resolve a make/model against blocket.se's real taxonomy (make/series/model tree).

    Unlike otomoto-pl/standvirtual-pt's best-effort slug guessing, this
    enumerates blocket.se's actual valid series/model list for the make, since
    the full taxonomy tree is embedded in every search response.

    Args:
        make: Make name, e.g. "BMW".
        model: Series or specific model/trim name, e.g. "1-Series" or "120d". Omit to list all series for the make.
    """
    try:
        return bc.list_makes_models(make, model)
    except bc.BlocketError as e:
        return {"error": str(e)}


if __name__ == "__main__":
    mcp.run()
