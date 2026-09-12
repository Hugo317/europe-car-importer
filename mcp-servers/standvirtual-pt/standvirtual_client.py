"""Minimal client for standvirtual.com (Portugal) search results.

standvirtual.com is OLX Group's Portuguese site, running the exact same
Next.js/urql platform as otomoto.pl (Poland) -- same embedded
<script id="__NEXT_DATA__"> -> props.pageProps.urqlState -> advertSearch
GraphQL cache shape. This module is otomoto_client.py adapted for
standvirtual's URL path ("/carros/..." not "/osobowe/..."), its year filter
key ("first_registration_year" not "year"), and its native EUR pricing (no
currency conversion needed, unlike Poland's PLN).
"""
from __future__ import annotations

import json
import re
import statistics
import time
import unicodedata

import httpx

BASE_URL = "https://www.standvirtual.com"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)
PAGE_SIZE = 32
YEAR_FILTER_KEY = "filter_float_first_registration_year"


def slugify(value: str) -> str:
    """Best-effort standvirtual URL-slug conversion (e.g. "Series 1" -> "serie-1"
    is NOT guaranteed -- PT model names sometimes differ from EN/otomoto slugs;
    verify with list_makes_models for anything non-obvious).
    """
    value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()
    value = value.strip().lower()
    value = re.sub(r"[^a-z0-9]+", "-", value)
    return value.strip("-")


class StandvirtualError(RuntimeError):
    pass


def _fetch_next_data(url: str, client: httpx.Client) -> dict:
    resp = client.get(url, headers={"User-Agent": USER_AGENT}, follow_redirects=True)
    if resp.status_code in (403, 429):
        raise StandvirtualError(
            f"standvirtual.com returned {resp.status_code} (blocked/rate-limited) for {url}"
        )
    resp.raise_for_status()
    match = re.search(
        r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', resp.text, re.S
    )
    if not match:
        raise StandvirtualError(f"__NEXT_DATA__ not found in response for {url}")
    return json.loads(match.group(1))


def _extract_advert_search(next_data: dict) -> dict | None:
    urql_state = next_data.get("props", {}).get("pageProps", {}).get("urqlState", {})
    for entry in urql_state.values():
        raw = entry.get("data")
        if not raw:
            continue
        try:
            parsed = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            continue
        if isinstance(parsed, dict) and "advertSearch" in parsed:
            return parsed["advertSearch"]
    return None


def _node_to_listing(node: dict) -> dict:
    params = {p["key"]: p.get("value") for p in node.get("parameters", [])}
    display = {p["key"]: p.get("displayValue") for p in node.get("parameters", [])}
    price = node.get("price", {}).get("amount", {}) or {}
    location = node.get("location") or {}
    year_raw = params.get("first_registration_year", "")
    mileage_raw = params.get("mileage", "")
    power_raw = params.get("engine_power", "")
    return {
        "id": node.get("id"),
        "title": node.get("title"),
        "url": node.get("url"),
        "price_eur": price.get("units"),
        "currency": price.get("currencyCode", "EUR"),
        "year": int(year_raw) if year_raw.isdigit() else None,
        "mileage_km": int(mileage_raw) if mileage_raw.isdigit() else None,
        "power_hp": int(power_raw) if power_raw.isdigit() else None,
        "fuel_type": display.get("fuel_type"),
        "gearbox": display.get("gearbox"),
        "version": display.get("version"),
        "city": (location.get("city") or {}).get("name"),
        "region": (location.get("region") or {}).get("name"),
        "seller_name": (node.get("sellerLink") or {}).get("name"),
    }


def _search_page(
    make_slug: str,
    model_slug: str | None,
    year_from: int | None,
    year_to: int | None,
    page: int,
    client: httpx.Client,
) -> dict:
    path = f"/carros/{make_slug}" + (f"/{model_slug}" if model_slug else "")
    query: dict[str, str] = {}
    if year_from:
        query[f"search[{YEAR_FILTER_KEY}:from]"] = str(year_from)
    if year_to:
        query[f"search[{YEAR_FILTER_KEY}:to]"] = str(year_to)
    if page > 1:
        query["page"] = str(page)
    url = f"{BASE_URL}{path}"
    if query:
        url += "?" + "&".join(f"{k}={v}" for k, v in query.items())

    next_data = _fetch_next_data(url, client)
    advert_search = _extract_advert_search(next_data)
    if advert_search is None:
        raise StandvirtualError(f"No advertSearch block found for {url}")

    if model_slug is not None:
        applied_names = {f["name"] for f in advert_search.get("appliedFilters", [])}
        if "filter_enum_model" not in applied_names:
            # standvirtual silently drops an unrecognized model slug and falls
            # back to the whole make instead of erroring. This is especially
            # easy to hit here: for makes like BMW, standvirtual's "model" is
            # the specific trim number (e.g. "116", "120"), not a series/family
            # name (e.g. "serie-1" / "1-series" both resolve to nothing).
            raise StandvirtualError(
                f"model slug '{model_slug}' was not recognized by standvirtual.com "
                f"for make '{make_slug}' (it was silently dropped, so results would "
                f"actually be for the whole make). For makes like BMW, try the "
                f"specific trim number (e.g. '116', '120') instead of a series name "
                f"-- verify with list_makes_models first."
            )
    return advert_search


def search_listings(
    make: str,
    model: str | None = None,
    year_from: int | None = None,
    year_to: int | None = None,
    page: int = 1,
    make_slug: str | None = None,
    model_slug: str | None = None,
) -> dict:
    """Search standvirtual.com listings for one page (up to 32 results)."""
    m_slug = make_slug or slugify(make)
    mo_slug = model_slug or (slugify(model) if model else None)
    with httpx.Client(timeout=20) as client:
        advert_search = _search_page(m_slug, mo_slug, year_from, year_to, page, client)
    listings = [_node_to_listing(edge["node"]) for edge in advert_search.get("edges", [])]
    applied = {
        f["name"]: f.get("labels") for f in advert_search.get("appliedFilters", [])
    }
    return {
        "make_slug": m_slug,
        "model_slug": mo_slug,
        "total_count": advert_search.get("totalCount"),
        "page": page,
        "page_size": PAGE_SIZE,
        "applied_filter_labels": applied,
        "listings": listings,
    }


def price_analysis(
    make: str,
    model: str | None = None,
    year_from: int | None = None,
    year_to: int | None = None,
    max_listings: int = 100,
    make_slug: str | None = None,
    model_slug: str | None = None,
) -> dict:
    """Aggregate price stats (EUR, native currency) over up to `max_listings` results."""
    m_slug = make_slug or slugify(make)
    mo_slug = model_slug or (slugify(model) if model else None)
    max_pages = max(1, (max_listings + PAGE_SIZE - 1) // PAGE_SIZE)

    all_listings: list[dict] = []
    total_count = None
    with httpx.Client(timeout=20) as client:
        for page in range(1, max_pages + 1):
            advert_search = _search_page(m_slug, mo_slug, year_from, year_to, page, client)
            total_count = advert_search.get("totalCount")
            edges = advert_search.get("edges", [])
            if not edges:
                break
            all_listings.extend(_node_to_listing(e["node"]) for e in edges)
            if len(all_listings) >= max_listings or len(edges) < PAGE_SIZE:
                break
            time.sleep(0.3)  # be polite between paginated requests

    all_listings = all_listings[:max_listings]
    prices_eur = sorted(l["price_eur"] for l in all_listings if l["price_eur"])

    if not prices_eur:
        return {
            "make_slug": m_slug,
            "model_slug": mo_slug,
            "site_total_count": total_count,
            "sampled_count": 0,
            "note": "No listings with a parseable price were found for this query.",
        }

    def pct(p: float) -> float:
        idx = min(len(prices_eur) - 1, max(0, round(p * (len(prices_eur) - 1))))
        return prices_eur[idx]

    stats_eur = {
        "min": prices_eur[0],
        "p25": pct(0.25),
        "median": statistics.median(prices_eur),
        "avg": round(statistics.mean(prices_eur), 2),
        "p75": pct(0.75),
        "max": prices_eur[-1],
    }

    return {
        "make_slug": m_slug,
        "model_slug": mo_slug,
        "site_total_count": total_count,
        "sampled_count": len(prices_eur),
        "price_eur": stats_eur,
    }


def list_makes_models(make: str, model: str | None = None) -> dict:
    """Best-effort validation: does this make/model slug combination resolve to
    any listings on standvirtual.com? See otomoto_client.list_makes_models for
    the same caveat -- this validates a specific guess, it doesn't enumerate
    all valid values.
    """
    m_slug = slugify(make)
    mo_slug = slugify(model) if model else None
    with httpx.Client(timeout=20) as client:
        advert_search = _search_page(m_slug, mo_slug, None, None, 1, client)
    applied = advert_search.get("appliedFilters", [])
    labels = {f["name"]: f.get("labels") for f in applied}
    make_ok = "filter_enum_make" in labels
    model_ok = (mo_slug is None) or ("filter_enum_model" in labels)
    return {
        "make_slug": m_slug,
        "model_slug": mo_slug,
        "total_count": advert_search.get("totalCount"),
        "resolved_labels": labels,
        "valid": bool(advert_search.get("totalCount")) and make_ok and model_ok,
    }
