"""Minimal client for blocket.se (Sweden) car listings.

blocket.se and finn.no (Norway, ../finn-no/finn_client.py) run the same
Schibsted "mobility" marketplace platform -- same URL layout
(/mobility/search/car), same response shape, and even the same numeric
make/series "variant" taxonomy codes (e.g. BMW = "0.749" on both sites,
1-Serie = "1.749.7967" on both). This module is finn_client.py's approach
adapted for blocket.se's domain/currency/mileage-unit-label; see that file's
docstring for the full mechanism (embedded base64-encoded dehydrated
react-query JSON in a <script type="application/json"> tag with no id,
fetched with plain HTTP -- no headless browser needed).
"""
from __future__ import annotations

import base64
import binascii
import json
import re
import statistics
import time
import unicodedata

import httpx

BASE_URL = "https://www.blocket.se"
SEARCH_PATH = "/mobility/search/car"
CURRENCY = "SEK"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)
PAGE_SIZE = 49

_SCRIPT_JSON_RE = re.compile(
    r'<script type="application/json"[^>]*>(.*?)</script>', re.S
)


class BlocketError(RuntimeError):
    pass


def _normalize(value: str) -> str:
    """Fold accents/case/punctuation and the "-serie" vs English "-series"
    naming difference so e.g. "1 Series" matches blocket's "1-Serie"."""
    value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()
    value = value.lower().replace("series", "serie")
    return re.sub(r"[^a-z0-9]", "", value)


def _fetch_search_data(params: dict, client: httpx.Client) -> dict:
    resp = client.get(
        f"{BASE_URL}{SEARCH_PATH}",
        params=params,
        headers={"User-Agent": USER_AGENT},
        follow_redirects=True,
    )
    if resp.status_code in (403, 429):
        raise BlocketError(
            f"blocket.se returned {resp.status_code} (blocked/rate-limited) for params={params}"
        )
    resp.raise_for_status()

    best_data = None
    for raw in _SCRIPT_JSON_RE.findall(resp.text):
        raw = raw.strip()
        if len(raw) < 1000:
            continue
        try:
            decoded = base64.b64decode(raw, validate=True)
            payload = json.loads(decoded)
        except (binascii.Error, ValueError, json.JSONDecodeError):
            continue
        queries = payload.get("queries")
        if not isinstance(queries, list):
            continue
        for q in queries:
            key0 = (q.get("queryKey") or [{}])[0]
            if key0.get("scope") == "search":
                data = q.get("state", {}).get("data")
                if isinstance(data, dict) and "docs" in data:
                    best_data = data
    if best_data is None:
        raise BlocketError(
            f"Could not find embedded search-result JSON in blocket.se response for params={params} "
            "(page structure may have changed)"
        )
    return best_data


def _taxonomy(client: httpx.Client) -> list[dict]:
    """The full make/series/model tree, from the "variant" filter of an
    unfiltered search (present regardless of applied filters)."""
    data = _fetch_search_data({}, client)
    for f in data.get("filters", []):
        if f.get("name") == "variant":
            return f.get("filter_items", [])
    raise BlocketError("Could not find the 'variant' (make/model) filter in blocket.se's taxonomy response")


def _resolve_make(make: str, taxonomy: list[dict]) -> dict:
    target = _normalize(make)
    for item in taxonomy:
        if _normalize(item["display_name"]) == target:
            return item
    for item in taxonomy:
        if target in _normalize(item["display_name"]):
            return item
    available = ", ".join(i["display_name"] for i in taxonomy[:25])
    raise BlocketError(
        f"make '{make}' not found in blocket.se's make list. Examples: {available}... "
        f"Use list_makes_models to see the full list."
    )


def _flatten(items: list[dict], depth: int = 0) -> list[tuple[int, dict]]:
    out = []
    for item in items:
        out.append((depth, item))
        out.extend(_flatten(item.get("filter_items", []), depth + 1))
    return out


def _resolve_model(make_item: dict, model: str) -> dict:
    target = _normalize(model)
    flat = _flatten(make_item.get("filter_items", []))
    # Prefer the deepest (most specific, e.g. a leaf trim like "120d") exact match.
    exact = [(d, i) for d, i in flat if _normalize(i["display_name"]) == target]
    if exact:
        return sorted(exact, key=lambda x: -x[0])[0][1]
    partial = [(d, i) for d, i in flat if target in _normalize(i["display_name"])]
    if partial:
        return sorted(partial, key=lambda x: -x[0])[0][1]
    available = ", ".join(i["display_name"] for _, i in flat[:25])
    raise BlocketError(
        f"model '{model}' not found under make '{make_item['display_name']}' on blocket.se. "
        f"Available include: {available}{'...' if len(flat) > 25 else ''}. "
        f"Use list_makes_models to see the full list."
    )


def _resolve_variant_code(make: str, model: str | None, client: httpx.Client) -> tuple[str, dict, dict | None]:
    taxonomy = _taxonomy(client)
    make_item = _resolve_make(make, taxonomy)
    if model is None:
        return make_item["value"], make_item, None
    model_item = _resolve_model(make_item, model)
    return model_item["value"], make_item, model_item


def list_makes_models(make: str, model: str | None = None) -> dict:
    """Resolve a make (and optionally model) against blocket.se's real taxonomy tree."""
    with httpx.Client(timeout=20) as client:
        taxonomy = _taxonomy(client)
        make_item = _resolve_make(make, taxonomy)
        result = {
            "make_display_name": make_item["display_name"],
            "make_variant_code": make_item["value"],
            "available_series": [
                {"name": s["display_name"], "variant_code": s["value"]}
                for s in make_item.get("filter_items", [])
            ],
        }
        if model is not None:
            try:
                model_item = _resolve_model(make_item, model)
                result["model_display_name"] = model_item["display_name"]
                result["model_variant_code"] = model_item["value"]
                result["valid"] = True
            except BlocketError as e:
                result["valid"] = False
                result["error"] = str(e)
        else:
            result["valid"] = True
        return result


def _doc_to_listing(doc: dict) -> dict:
    price = doc.get("price") or {}
    mileage = doc.get("mileage")
    mileage_unit = doc.get("mileage_unit")
    mileage_km = mileage
    if mileage is not None and mileage_unit == "SCANDINAVIAN_MILE":
        mileage_km = mileage * 10
    return {
        "id": doc.get("id"),
        "title": doc.get("heading") or doc.get("facade_title"),
        "url": doc.get("canonical_url"),
        "price": price.get("amount"),
        "currency": price.get("currency_code", CURRENCY),
        "year": doc.get("year"),
        "mileage_km": mileage_km,
        "fuel_type": doc.get("fuel"),
        "gearbox": doc.get("transmission"),
        "make": doc.get("make"),
        "series": doc.get("series"),
        "model": doc.get("model"),
        "model_specification": doc.get("model_specification"),
        "location": doc.get("location"),
        "seller_name": doc.get("organisation_name"),
        "dealer_segment": doc.get("dealer_segment"),
    }


def _search_params(variant_code: str, year_from: int | None, year_to: int | None, page: int) -> dict:
    params: dict[str, str] = {"variant": variant_code}
    if year_from:
        params["year_from"] = str(year_from)
    if year_to:
        params["year_to"] = str(year_to)
    if page > 1:
        params["page"] = str(page)
    return params


def search_listings(
    make: str,
    model: str | None = None,
    year_from: int | None = None,
    year_to: int | None = None,
    page: int = 1,
) -> dict:
    """Search blocket.se (Sweden) car listings for one page (up to ~49 results)."""
    with httpx.Client(timeout=20) as client:
        variant_code, make_item, model_item = _resolve_variant_code(make, model, client)
        params = _search_params(variant_code, year_from, year_to, page)
        data = _fetch_search_data(params, client)
    metadata = data.get("metadata", {})
    return {
        "make_display_name": make_item["display_name"],
        "model_display_name": model_item["display_name"] if model_item else None,
        "variant_code": variant_code,
        "total_count": metadata.get("result_size", {}).get("match_count"),
        "page": page,
        "page_size": PAGE_SIZE,
        "listings": [_doc_to_listing(d) for d in data.get("docs", [])],
    }


def price_analysis(
    make: str,
    model: str | None = None,
    year_from: int | None = None,
    year_to: int | None = None,
    max_listings: int = 100,
) -> dict:
    """Aggregate price stats (SEK and EUR) over up to `max_listings` blocket.se results."""
    max_pages = max(1, (max_listings + PAGE_SIZE - 1) // PAGE_SIZE)
    all_listings: list[dict] = []
    total_count = None
    make_item = model_item = None
    variant_code = None

    with httpx.Client(timeout=20) as client:
        variant_code, make_item, model_item = _resolve_variant_code(make, model, client)
        for page in range(1, max_pages + 1):
            params = _search_params(variant_code, year_from, year_to, page)
            data = _fetch_search_data(params, client)
            total_count = data.get("metadata", {}).get("result_size", {}).get("match_count")
            docs = data.get("docs", [])
            if not docs:
                break
            all_listings.extend(_doc_to_listing(d) for d in docs)
            if len(all_listings) >= max_listings or len(docs) < PAGE_SIZE:
                break
            time.sleep(0.3)  # be polite between paginated requests

    all_listings = all_listings[:max_listings]
    prices_sek = sorted(l["price"] for l in all_listings if l["price"])

    base = {
        "make_display_name": make_item["display_name"],
        "model_display_name": model_item["display_name"] if model_item else None,
        "variant_code": variant_code,
        "site_total_count": total_count,
    }
    if not prices_sek:
        return {**base, "sampled_count": 0, "note": "No listings with a parseable price were found for this query."}

    def pct(p: float) -> float:
        idx = min(len(prices_sek) - 1, max(0, round(p * (len(prices_sek) - 1))))
        return prices_sek[idx]

    rate = get_eur_sek_rate()
    stats_sek = {
        "min": prices_sek[0],
        "p25": pct(0.25),
        "median": statistics.median(prices_sek),
        "avg": round(statistics.mean(prices_sek), 2),
        "p75": pct(0.75),
        "max": prices_sek[-1],
    }
    stats_eur = {k: round(v * rate, 2) if rate else None for k, v in stats_sek.items()}

    return {
        **base,
        "sampled_count": len(prices_sek),
        "eur_sek_rate_used": rate,
        "eur_sek_rate_source": "https://api.frankfurter.dev (ECB reference rate)" if rate else None,
        "price_sek": stats_sek,
        "price_eur": stats_eur,
    }


_rate_cache: dict = {}


def get_eur_sek_rate(ttl_seconds: int = 3600) -> float | None:
    """1 SEK in EUR, via the free Frankfurter (ECB) API. Cached in-process."""
    now = time.time()
    if _rate_cache.get("value") and now - _rate_cache.get("ts", 0) < ttl_seconds:
        return _rate_cache["value"]
    try:
        resp = httpx.get(
            "https://api.frankfurter.dev/v1/latest",
            params={"base": "SEK", "symbols": "EUR"},
            timeout=10,
        )
        resp.raise_for_status()
        rate = resp.json()["rates"]["EUR"]
        _rate_cache.update(value=rate, ts=now)
        return rate
    except Exception:
        return _rate_cache.get("value")
