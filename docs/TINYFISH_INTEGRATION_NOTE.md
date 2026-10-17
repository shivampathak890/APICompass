# TinyFish API Official Integration Note & Contract Verification

**Date Verified:** October 18, 2026  
**Primary Source:** Official TinyFish Developer Documentation (`https://tinyfish.ai/docs`)  
**Scope:** Search API (`https://api.search.tinyfish.ai`) and Fetch API (`https://api.fetch.tinyfish.ai`)

---

## 1. Verified Official API Contracts

### A. TinyFish Fetch API

* **Endpoint URL:** `https://api.fetch.tinyfish.ai`
* **HTTP Method:** `POST`
* **Authentication:** Required HTTP header `X-API-Key: <your-api-key>`
* **Content-Type:** `application/json`
* **Accept:** `application/json`

#### Request Schema
```json
{
  "urls": ["https://docs.stripe.com/api/charges/create"],
  "format": "markdown",
  "purpose": "Extract Stripe Charge creation parameter contracts",
  "links": false,
  "image_links": false,
  "iframe_links": false,
  "ttl": 3600,
  "per_url_timeout_ms": 45000
}
```

| Field | Type | Presence | Default | Description |
| :--- | :--- | :--- | :--- | :--- |
| `urls` | `string[]` | **Required** | *None* | Array of HTTP/HTTPS URLs (Max 10 URLs/request). Blocks private/internal IPs, localhost, and cloud metadata. |
| `format` | `string` | Optional | `"markdown"` | Output format: `"markdown"`, `"html"`, or `"json"`. |
| `purpose` | `string` | Optional | *None* | Short statement (max 2000 chars) explaining task context to guide extraction quality. |
| `links` | `boolean` | Optional | `false` | When `true`, extracts all `<a href>` URLs into a `links` array. |
| `image_links` | `boolean` | Optional | `false` | When `true`, extracts all `<img src>` URLs into an `image_links` array. |
| `iframe_links` | `boolean` | Optional | `false` | When `true`, includes `src` URLs of `<iframe>` elements. |
| `ttl` | `integer` | Optional | *Omitted* | Cache freshness tolerance in seconds (`0` forces fresh live fetch). |
| `per_url_timeout_ms` | `integer` | Optional | `45000` | Max execution timeout per URL in milliseconds. |

#### Response Schema (HTTP 200 OK)
```json
{
  "results": [
    {
      "id": "fetch_01j...",
      "url": "https://docs.stripe.com/api/charges/create",
      "final_url": "https://docs.stripe.com/api/charges/create",
      "title": "Create a charge | Stripe Docs",
      "description": "...",
      "language": "en",
      "format": "markdown",
      "text": "# Create a charge\n\nTo charge a credit card...",
      "status": "completed"
    }
  ],
  "errors": []
}
```

* `results` (`array`): Array of fetched page objects.
  * `id` (`string`): Unique extraction task ID.
  * `url` (`string`): Requested target URL.
  * `final_url` (`string`): Canonical URL after following redirects (critical for SSRF validation).
  * `title` (`string | null`): Page or section title.
  * `text` (`string`): Clean extracted text in the requested format.
  * `status` (`string`): `"completed"` or `"failed"`.
* `errors` (`array`): List of failed URLs with error codes and descriptions if scraping failed.

---

### B. TinyFish Search API

* **Endpoint URL:** `https://api.search.tinyfish.ai`
* **HTTP Method:** `GET`
* **Authentication:** Required HTTP header `X-API-Key: <your-api-key>`

#### Query Parameters

| Parameter | Type | Presence | Default | Description |
| :--- | :--- | :--- | :--- | :--- |
| `query` | `string` | **Required** | *None* | Search query string (e.g. `stripe payment intent create`). |
| `include_domains` | `string` | Optional | *None* | Comma-separated domain allowlist (e.g. `docs.stripe.com,stripe.com`). |
| `exclude_domains` | `string` | Optional | *None* | Comma-separated domain blocklist. |
| `purpose` | `string` | Optional | *None* | Context statement (max 2000 chars) to improve semantic ranking. |
| `location` | `string` | Optional | `"US"` | 2-letter country code for geo-targeted search results. |
| `language` | `string` | Optional | `"en"` | 2-letter language code. |
| `recency_minutes` | `integer` | Optional | *None* | Freshness window in minutes (1 to 5256000). |
| `domain_type` | `string` | Optional | `"web"` | Search type: `"web"`, `"news"`, or `"research_paper"`. |
| `page` | `integer` | Optional | `0` | Pagination page number (0 to 10). |

#### Response Schema (HTTP 200 OK)
```json
{
  "query": "stripe payment intent create",
  "results": [
    {
      "position": 1,
      "site_name": "docs.stripe.com",
      "title": "Payment Intents API | Stripe Docs",
      "snippet": "Use the Payment Intents API to build dynamic payment flows...",
      "url": "https://docs.stripe.com/api/payment_intents/create"
    }
  ],
  "total_results": 12,
  "page": 0
}
```

---

## 2. Documented Operational Characteristics

1. **Rate Limits:**
   * Standard tier defaults to **150 URLs/minute** for Fetch and **30 queries/minute** for Search per API key.
   * Free daily allowance: up to 1,000 URLs/day.
2. **Error Responses:**
   * `401 Unauthorized`: Missing or invalid `X-API-Key`.
   * `429 Too Many Requests`: Rate limit exceeded.
   * Private / Local IP targets (e.g. `127.0.0.1`, `169.254.169.254`): Rejected automatically by the TinyFish gateway.
3. **Execution Model:**
   * Synchronous HTTP request-response model with internal Chromium headless rendering.
   * Upstream timeout configurable via `per_url_timeout_ms` (default 45s).

---

## 3. Comparison with Current APICompass Implementation

| Aspect | Official Contract | Current APICompass Implementation | Discrepancy Status |
| :--- | :--- | :--- | :--- |
| **Search Request** | `GET https://api.search.tinyfish.ai` | **Never called** anywhere in codebase | **MISSING FEATURE**: `search_base_url` is configured in `settings` but uninvoked. |
| **Search Query Params** | `query`, `include_domains` | N/A | **GAP**: No search query builder exists. |
| **Fetch Endpoint** | `POST https://api.fetch.tinyfish.ai` | `POST https://api.fetch.tinyfish.ai` | **MATCH**: Correct endpoint and method. |
| **Authentication** | Header `X-API-Key: <key>` | Header `X-API-Key: <key>` | **MATCH**: Correct header and key injection. |
| **Fetch Request Body** | `{"urls": [...], "format": "markdown"}` | `{"urls": [url]}` | **MINOR GAP**: Omits `format="markdown"` and `ttl`. |
| **Fetch Response `final_url`** | `page.final_url` provided for redirects | Uses input `url`; ignores `final_url` | **SECURITY GAP**: Redirect destination escapes SSRF check. |
| **Fetch Response `errors`** | Top-level `errors` array | Assumes `results[0]` exists if 200 | **RESILIENCE GAP**: Ignores upstream scrape error items. |
| **Adjudicator Status Check** | Returns `status="success"` | Adjudicators check `status in ("live", "mock")` | **CRITICAL BUG**: Live evidence is dropped by adjudicators. |

---

## 4. Exact Implementation Changes Required

1. **Fix Evidence Status Vocabulary:**
   * In `backend/app/services/evidence/adjudicator.py`, `stream_adjudicator.py`, and `project_adjudicator.py`:
     Change condition from `if res.status in ("live", "mock")` to `if res.status in ("live", "success", "mock")`.
2. **Implement `search_urls` on `TinyFishLiveRetriever`:**
   * Add method `search_urls(query: str, ecosystem: str = "stripe", limit: int = 3) -> List[str]`.
   * Call `GET https://api.search.tinyfish.ai` with `params={"query": query, "include_domains": "docs.stripe.com,stripe.com"}`.
   * Pass each returned hit URL through `validate_destination_url` before returning.
3. **Wire Search Fallback in `registry.resolve_documentation_target`:**
   * When `query` does not match the static `STRIPE_SYMBOL_URL_MAP`, trigger TinyFish Search to discover official documentation dynamically.
4. **Pass `"format": "markdown"` & Validate `final_url`:**
   * In `fetch_url()`, include `"format": "markdown"` in request payload.
   * Validate `page_data.get("final_url")` through `validate_destination_url` to defend against redirect SSRF escapes.

