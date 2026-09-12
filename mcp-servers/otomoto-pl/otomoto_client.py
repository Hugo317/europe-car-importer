"""Minimal client for otomoto.pl search results.

otomoto.pl is a Next.js app that embeds its GraphQL search results in a
<script id="__NEXT_DATA__"> JSON blob (props.pageProps.urqlState), the same
pattern autoscout24-mcp uses for AutoScout24. This module fetches a search
results page with plain HTTP and parses that blob directly -- no headless
browser needed (so far).
"""
from __future__ import annotations

import json
import re
import statistics
import time
import unicodedata
from dataclasses import dataclass, field

import httpx

BASE_URL = "https://www.otomoto.pl"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)
PAGE_SIZE = 32


def slugify(value: str) -> str:
    """Best-effort otomoto.pl URL-slug conversion (e.g. "Seria 1" -> "seria-1").

    otomoto slugs are usually just the lowercased, hyphenated make/model name.
    This covers the common case; unusual models may need the exact slug passed
    in directly (verify with list_makes_models).
    """
    value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()
    value = value.strip().lower()
    value = re.sub(r"[^a-z0-9]+", "-", value)
    return value.strip("-")


class OtomotoError(RuntimeError):
    pass


def _fetch_next_data(url: str, client: httpx.Client) -> dict:
    resp = client.get(url, headers={"User-Agent": USER_AGENT}, follow_redirects=True)
    if resp.status_code in (403, 429):
        raise OtomotoError(
            f"otomoto.pl returned {resp.status_code} (blocked/rate-limited) for {url}"
        )
    resp.raise_for_status()
    match = re.search(
        r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', resp.text, re.S
    )
    if not match:
        raise OtomotoError(f"__NEXT_DATA__ not found in response for {url}")
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
    return {
        "id": node.get("id"),
        "title": node.get("title"),
        "url": node.get("url"),
        "price_pln": price.get("units"),
        "currency": price.get("currencyCode", "PLN"),
        "year": int(params["year"]) if params.get("year", "").isdigit() else None,
        "mileage_km": int(params["mileage"]) if params.get("mileage", "").isdigit() else None,
        "power_hp": int(params["engine_power"]) if params.get("engine_power", "").isdigit() else None,
        "engine_capacity_cc": int(params["engine_capacity"]) if params.get("engine_capacity", "").isdigit() else None,
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
    path = f"/osobowe/{make_slug}" + (f"/{model_slug}" if model_slug else "")
    query: dict[str, str] = {}
    if year_from:
        query["search[filter_float_year:from]"] = str(year_from)
    if year_to:
        query["search[filter_float_year:to]"] = str(year_to)
    if page > 1:
        query["page"] = str(page)
    url = f"{BASE_URL}{path}"
    if query:
        url += "?" + "&".join(f"{k}={v}" for k, v in query.items())

    next_data = _fetch_next_data(url, client)
    advert_search = _extract_advert_search(next_data)
    if advert_search is None:
        raise OtomotoError(f"No advertSearch block found for {url}")

    if model_slug is not None:
        applied_names = {f["name"] for f in advert_search.get("appliedFilters", [])}
        if "filter_enum_model" not in applied_names:
            # otomoto silently drops an unrecognized model slug and falls back
            # to the whole make instead of erroring -- surfacing that here
            # prevents a wrong-slug query from returning misleadingly-labeled
            # whole-make aggregate data.
            raise OtomotoError(
                f"model slug '{model_slug}' was not recognized by otomoto.pl for "
                f"make '{make_slug}' (it was silently dropped, so results would "
                f"actually be for the whole make). Verify the slug with "
                f"list_makes_models or check the URL on otomoto.pl directly."
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
    """Search otomoto.pl listings for one page (up to 32 results)."""
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
    """Aggregate price stats (PLN and EUR) over up to `max_listings` results."""
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
    prices_pln = sorted(l["price_pln"] for l in all_listings if l["price_pln"])

    if not prices_pln:
        return {
            "make_slug": m_slug,
            "model_slug": mo_slug,
            "site_total_count": total_count,
            "sampled_count": 0,
            "note": "No listings with a parseable price were found for this query.",
        }

    def pct(p: float) -> float:
        idx = min(len(prices_pln) - 1, max(0, round(p * (len(prices_pln) - 1))))
        return prices_pln[idx]

    rate = get_eur_pln_rate()
    stats_pln = {
        "min": prices_pln[0],
        "p25": pct(0.25),
        "median": statistics.median(prices_pln),
        "avg": round(statistics.mean(prices_pln), 2),
        "p75": pct(0.75),
        "max": prices_pln[-1],
    }
    stats_eur = {k: round(v * rate, 2) if rate else None for k, v in stats_pln.items()}

    return {
        "make_slug": m_slug,
        "model_slug": mo_slug,
        "site_total_count": total_count,
        "sampled_count": len(prices_pln),
        "eur_pln_rate_used": rate,
        "eur_pln_rate_source": "https://api.frankfurter.dev (ECB reference rate)" if rate else None,
        "price_pln": stats_pln,
        "price_eur": stats_eur,
    }


def list_makes_models(make: str, model: str | None = None) -> dict:
    """Best-effort validation: does this make/model slug combination resolve to
    any listings on otomoto.pl? Returns the canonical display labels otomoto
    reports back, or a suggestion to check the slug if nothing matched.

    otomoto doesn't expose a plain enumerable make/model list in this embedded
    JSON (facet *values* are fetched via a separate client-side call this
    server doesn't replicate) -- this validates a specific guess instead of
    listing all valid values.
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
        # otomoto silently drops an unrecognized make/model filter instead of
        # erroring, so "valid" checks that the filter was actually applied
        # (present in resolved_labels), not just that some results came back.
        "valid": bool(advert_search.get("totalCount")) and make_ok and model_ok,
    }


_rate_cache: dict = {}


def get_eur_pln_rate(ttl_seconds: int = 3600) -> float | None:
    """1 PLN in EUR, via the free Frankfurter (ECB) API. Cached in-process."""
    now = time.time()
    if _rate_cache.get("value") and now - _rate_cache.get("ts", 0) < ttl_seconds:
        return _rate_cache["value"]
    try:
        resp = httpx.get(
            "https://api.frankfurter.dev/v1/latest",
            params={"base": "PLN", "symbols": "EUR"},
            timeout=10,
        )
        resp.raise_for_status()
        rate = resp.json()["rates"]["EUR"]
        _rate_cache.update(value=rate, ts=now)
        return rate
    except Exception:
        return _rate_cache.get("value")
