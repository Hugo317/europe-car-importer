"""MCP stdio server exposing otomoto.pl (Poland) car listing search/pricing.

Mirrors the subset of autoscout24-mcp's tool surface that the
car-import-appraisal skill actually calls: search_listings, price_analysis,
list_makes_models. See otomoto_client.py for the scraping/parsing logic.
"""
from mcp.server.fastmcp import FastMCP

import otomoto_client as oc

mcp = FastMCP("otomoto-pl")


@mcp.tool()
def search_listings(
    make: str,
    model: str | None = None,
    year_from: int | None = None,
    year_to: int | None = None,
    page: int = 1,
) -> dict:
    """Search otomoto.pl (Poland) car listings, one page (up to 32 results).

    Args:
        make: Make name or otomoto slug, e.g. "bmw".
        model: Model name or otomoto slug, e.g. "seria-1". Omit to search the whole make.
        year_from: Minimum model year (inclusive).
        year_to: Maximum model year (inclusive).
        page: 1-indexed page number.
    """
    try:
        return oc.search_listings(make, model, year_from, year_to, page)
    except oc.OtomotoError as e:
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
    `max_listings` otomoto.pl listings, in both PLN and EUR (via a live
    ECB reference rate).

    Args:
        make: Make name or otomoto slug, e.g. "bmw".
        model: Model name or otomoto slug, e.g. "seria-1". Omit to search the whole make.
        year_from: Minimum model year (inclusive).
        year_to: Maximum model year (inclusive).
        max_listings: Cap on how many listings to sample (paginates 32 at a time).
    """
    try:
        return oc.price_analysis(make, model, year_from, year_to, max_listings)
    except oc.OtomotoError as e:
        return {"error": str(e)}


@mcp.tool()
def list_makes_models(make: str, model: str | None = None) -> dict:
    """Validate a make/model (name or slug) against otomoto.pl.

    otomoto doesn't expose a full enumerable make/model list the way this
    server can query cheaply, so this checks one specific make/model guess
    and reports whether it resolved, plus the canonical display labels
    otomoto reports back (useful for confirming spelling/slug).

    Args:
        make: Make name or otomoto slug, e.g. "bmw".
        model: Model name or otomoto slug, e.g. "seria-1". Omit to check the make only.
    """
    try:
        return oc.list_makes_models(make, model)
    except oc.OtomotoError as e:
        return {"error": str(e)}


if __name__ == "__main__":
    mcp.run()
