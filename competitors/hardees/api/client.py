"""
competitors/hardees/api/client.py
---------------------------------------------------------------------
A dependency-light, direct-HTTPS client for Hardee's Saudi's public
guest-session API (saudi.hardees.me). Built ENTIRELY from the live,
verified findings in ../research/api-map/api-map.md and api-map.json -
every payload shape below has a corresponding endpoint entry there with
its own `source_evidence`/`verificationNote`. Nothing here is guessed.

Why no browser (Playwright) is needed here, unlike ../tools/*.js:
see api-map.md "Direct API feasibility" - the edge WAF only checks for
browser-shaped `user-agent`/`origin`/`referer` headers (not an actual
browser fingerprint), and the application layer only requires a
`deviceid` header with ANY client-chosen value, live-confirmed with a
raw Node `https` client and zero cookie jar
(research/shared/sample-requests/direct-http-probe-transcript.md). This
client reproduces exactly that: a `requests.Session` with those headers
and a locally-generated `deviceid`, calling `guestLogin` once per
instance to match the documented bootstrap sequence, then the read-only
catalog endpoints on demand.

Security: `deviceid` is generated fresh per `HardeesApiClient` instance
(one per Streamlit session - see ../dashboard/page.py) with
`secrets.token_hex`, held only in memory, and marked `repr=False` so it
never appears if a caller accidentally logs/prints the client object.
This client never logs in, never touches an OTP/cart/checkout endpoint,
and never writes any response to disk itself - see
../services/sanitize.py for how responses are redacted before display.
---------------------------------------------------------------------
"""
from __future__ import annotations

import secrets
import time
from dataclasses import dataclass, field
from typing import Any

import requests

BASE_URL = "https://saudi.hardees.me"
DEFAULT_TIMEOUT = 15  # seconds - generous but bounded; a hung request must not hang the UI forever
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)


class HardeesApiError(RuntimeError):
    """Raised for any non-2xx-business-outcome response, or a network-level
    failure. Carries `status_code` (the HTTP transport status - see
    api-map.md's quirk about validateLocation using HTTP 500 for a normal
    "not deliverable" business outcome, which callers needing that
    distinction should catch specifically) and `body` (the parsed JSON
    response body, if any - already includes the site's own `type`/
    `message` fields, which are safe to show the user as-is)."""

    def __init__(self, message: str, status_code: int | None = None, body: Any = None):
        super().__init__(message)
        self.status_code = status_code
        self.body = body


@dataclass
class HardeesApiClient:
    """One instance per Streamlit session (see dashboard/page.py's
    `st.session_state` usage) - never shared across browser tabs/users,
    never persisted to disk, discarded when the Streamlit session ends.

    `min_interval_seconds` provides a simple, optional per-instance rate
    floor (sleeps just enough before a request if the previous one was too
    recent) - the batch-preview tool (../ui/batch_panel.py) sets this
    explicitly per the pacing strategy in
    ../research/api-map/unresolved-items.md; interactive single-call UI
    actions leave it at 0 (no artificial delay for a single manual click).
    """

    deviceid: str = field(default_factory=lambda: secrets.token_hex(16), repr=False)
    timeout: int = DEFAULT_TIMEOUT
    min_interval_seconds: float = 0.0
    _session: requests.Session = field(default_factory=requests.Session, repr=False)
    _blob: dict[str, str] | None = field(default=None, repr=False)
    _guest_logged_in: bool = field(default=False, repr=False)
    _last_request_at: float = field(default=0.0, repr=False)
    request_count: int = field(default=0)

    # --- low-level plumbing -------------------------------------------------

    def _headers(self) -> dict[str, str]:
        return {
            "content-type": "application/json",
            "brand": "HRD",
            "country": "KSA",
            "language": "En",
            "version": "v20",
            "devicemodel": "Chrome",
            "is-dark-mode": "0",
            "deviceid": self.deviceid,
            "refreshtoken": "",
            "user-agent": DEFAULT_USER_AGENT,
            "origin": BASE_URL,
            "referer": f"{BASE_URL}/en/home",
        }

    def _pace(self) -> None:
        if self.min_interval_seconds <= 0:
            return
        elapsed = time.monotonic() - self._last_request_at
        remaining = self.min_interval_seconds - elapsed
        if remaining > 0:
            time.sleep(remaining)

    def _request(self, method: str, path: str, json_body: Any = None, *, get: bool = False) -> dict:
        self._pace()
        url = f"{BASE_URL}{path}"
        try:
            resp = self._session.request(
                method, url, json=None if get else (json_body or {}), headers=self._headers(), timeout=self.timeout,
            )
        except requests.RequestException as e:
            raise HardeesApiError(f"Network error calling {path}: {e}") from None
        finally:
            self._last_request_at = time.monotonic()
            self.request_count += 1

        body: Any = None
        try:
            body = resp.json()
        except ValueError:
            body = None

        if resp.status_code == 403 and body is None:
            # The documented WAF block - a plain HTML 403 with no JSON body.
            raise HardeesApiError(
                f"{path}: blocked by the edge WAF (HTTP 403, no JSON body) - see api-map.md 'Browser bootstrap requirements'",
                status_code=403,
            )
        if body is None:
            raise HardeesApiError(f"{path}: non-JSON response (HTTP {resp.status_code})", status_code=resp.status_code)
        # Business-level failure: the site's own `statusCode`/`httpCode` fields
        # are the real outcome, per api-map.md's validateLocation quirk (HTTP
        # 500 transport status can still mean "normal, expected result").
        # Callers that need the not-deliverable case handled gracefully (e.g.
        # validate_location) catch HardeesApiError themselves; everything
        # else here just surfaces the site's own message.
        site_status = body.get("statusCode") if isinstance(body, dict) else None
        if site_status is not None and site_status not in (200,):
            raise HardeesApiError(
                body.get("message") or f"{path}: statusCode={site_status}",
                status_code=resp.status_code,
                body=body,
            )
        return body

    def ensure_session(self) -> None:
        """Calls guestLogin() once per instance, matching the documented
        bootstrap sequence (api-map.md "What a future collector should
        call, in order", step 1) rather than relying on the unverified
        assumption that skipping it would also work. Idempotent - safe to
        call before every higher-level method."""
        if self._guest_logged_in:
            return
        self._request("POST", "/api/guestLogin", {})
        self._guest_logged_in = True

    def _ensure_blob(self) -> dict[str, str]:
        """getAppConfig's blobBaseUrl.{jsonBase,SASToken} are required as
        `path`/`subPath` payload fields on getStoreList/getMenu/getHome -
        see api-map.md. Fetched once per instance and cached in memory."""
        self.ensure_session()
        if self._blob is None:
            body = self._request("GET", "/api/getAppConfig", get=True)
            blob = (body.get("data") or {}).get("blobBaseUrl") or {}
            self._blob = {"jsonBase": blob.get("jsonBase", ""), "sasToken": blob.get("SASToken", "")}
        return self._blob

    # --- branch / location ---------------------------------------------------

    def get_store_list(self) -> list[dict]:
        """Full city/branch directory - see api-map.json 'getStoreList'.
        One call returns every city and store in the country; the UI's
        branch selectors are built from this response, not hardcoded."""
        self.ensure_session()
        blob = self._ensure_blob()
        body = self._request(
            "POST", "/api/getStoreList",
            {"payload": {"path": blob["jsonBase"], "country": "ksa", "subPath": blob["sasToken"]}},
        )
        return body.get("data") or []

    def get_new_store(self, lat: float, lng: float) -> dict:
        """Nearest Pickup-capable branch for a coordinate - see
        api-map.json 'getNewStore'. Not used by the branch dropdowns
        (which resolve by explicit City/Store selection instead - also a
        documented, valid path per api-map.md 'Branch selection'), but
        exposed here for completeness / future use."""
        self.ensure_session()
        body = self._request("POST", "/api/getNewStore", {"lat": lat, "lng": lng})
        return body.get("data") or {}

    def validate_location(self, lat: float, lng: float, screen: str = "LOCATION", address_sub_type: str = "DELIVERY") -> dict:
        """Delivery serviceability + full store object for a coordinate -
        see api-map.json 'validateLocation'. Raises HardeesApiError with
        `body["type"]` set to one of OUTSIDE_DELIVERY_AREA_CONFIRM_LOC /
        OUTSIDE_DELIVERY_AREA / LOCATION_NOT_FOUND when not deliverable -
        callers should catch this and show the message, not crash."""
        self.ensure_session()
        body = self._request(
            "POST", "/api/validateLocation",
            {"lat": lat, "lng": lng, "screen": screen, "addressSubType": address_sub_type},
        )
        return body.get("data") or {}

    def get_prep_time(self, store_id: int) -> dict:
        """See api-map.json 'getPrepTime' - kitchen prep time in minutes.
        Documented as possibly a platform-wide constant, not necessarily a
        real per-store computation - see unresolved-items.md item #7."""
        self.ensure_session()
        body = self._request("POST", "/api/getPrepTime", {"payload": {"country": "ksa", "storeId": store_id}})
        return body.get("data") or {}

    # --- menu / catalog --------------------------------------------------------

    def get_menu_config(self, order_type: str, store_id: int | None = None) -> dict:
        """Returns {menuConfigId, clusterId, expiryTime} - see
        api-map.json 'getMenuConfig'. `order_type` must be 'PICKUP' or
        'DELIVERY'; per the documented 'Channel separation mechanism'
        finding, this has been live-confirmed to return the SAME
        menuConfigId/clusterId regardless of order_type for every branch
        tested so far - this client still sends the real value rather than
        hardcoding one, in case a future branch behaves differently."""
        self.ensure_session()
        payload: dict[str, Any] = {"orderType": order_type}
        if store_id is not None:
            payload["storeId"] = store_id
        body = self._request("POST", "/api/getMenuConfig", payload)
        return body.get("data") or {}

    def get_menu(self, menu_config_id: str, cluster_id: str, menu_temp_id: int, service: str) -> dict:
        """Category list - see api-map.json 'getMenu'."""
        self.ensure_session()
        blob = self._ensure_blob()
        body = self._request(
            "POST", "/api/getMenu",
            {"payload": {
                "path": "", "brand": "hrd", "country": "ksa", "defMenu": 1,
                "menu": menu_temp_id, "locale": "En", "service": service,
                "menuConfigId": menu_config_id, "subPath": blob["sasToken"],
            }},
        )
        return body.get("data") or {}

    def get_products_by_category(self, cluster_id: str, category_id: int | str, config_id: str) -> dict:
        """Every product in one category - see api-map.json
        'getProductsByCategory'. Deliberately takes NO service/channel
        argument: the live-verified payload carries no such field at all -
        see api-map.md 'Channel separation mechanism'."""
        self.ensure_session()
        body = self._request(
            "POST", "/api/getProductsByCategory",
            {"cluster": cluster_id, "id": str(category_id), "Language": "En", "configId": config_id},
        )
        return body.get("data") or {}

    def get_product(
        self, product_id: int, cluster_id: str, category_id: int, service: str, menu_config_id: str,
    ) -> dict:
        """Full product detail (populated steps[].options[]/variants[]) -
        see api-map.json 'getProductInfo' / api-map.md 'Product detail
        endpoint'. IMPORTANT: for a bundle_group wrapper product, callers
        must pass the wrapper's own `selectedItem` field value as
        `product_id`, not the wrapper's own top-level id - see
        services/menu_service.py's `resolve_detail_lookup_id()`, which
        implements this rule so callers of THIS method never have to
        remember it themselves."""
        self.ensure_session()
        body = self._request(
            "POST", "/api/product",
            {
                "id": product_id, "cluster": cluster_id, "categoryId": category_id,
                "service": service, "Language": "En", "menuConfigId": menu_config_id,
            },
        )
        return body.get("data") or {}

    def get_product_bundle_step(
        self, product_id: int, cluster_id: str, category_id: int, service: str, menu_config_id: str, step_id: int = 1,
    ) -> list[dict]:
        """Same steps[] content as get_product(), as a bare list - see
        api-map.json 'getProductBundleStep'. `step_id` is accepted but
        live-confirmed NOT to filter the response in any variant tried -
        every call returns the full steps array regardless."""
        self.ensure_session()
        body = self._request(
            "POST", "/api/product-bundle-step",
            {
                "id": product_id, "cluster": cluster_id, "categoryId": category_id,
                "service": service, "Language": "En", "menuConfigId": menu_config_id, "stepId": step_id,
            },
        )
        data = body.get("data")
        return data if isinstance(data, list) else []

    def get_promotion(self, **payload: Any) -> dict:
        """UNRESOLVED as of the second research session - see
        ../research/api-map/unresolved-items.md item #5 and #3. Every
        payload guessed so far returns a structured
        DEFAULT_VALIDATION_ERROR. Exposed here (rather than omitted) so
        the Streamlit page's getPromotion research panel (if/when added)
        and ../tools/ scripts share one implementation - passes through
        whatever keyword arguments the caller supplies as the raw JSON
        body, making no assumption about the correct shape."""
        self.ensure_session()
        body = self._request("POST", "/api/getPromotion", dict(payload))
        return body.get("data") or {}
