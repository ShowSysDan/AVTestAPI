"""Thin client for the ArtsVision REST API (read + experimental write).

Read behaviour mirrors what the LabVision poller does:
  POST {base}/getdata  with an ``entities``/``filters`` envelope and an
  ``apikey`` header. The response is wrapped as ``{"Status": 0, "Data": [...]}``
  where each Data entry is an entity block containing ``Rows``; every row is
  ``{"Data": {<field>: <value>...}, "Entities": null, "RowState": 0}``.

Write behaviour is the part this project exists to test. ArtsVision does not
publish a write endpoint, but the per-row ``RowState`` marker is the classic
ADO-style change-tracking field, so the working hypothesis is a ``setdata``
style save that accepts rows whose RowState flags them modified. The endpoint
name and the "modified" RowState value are both configurable so the request
can be adjusted to match whatever the server actually expects.
"""

import requests

import config
import db


class AVError(Exception):
    """Raised when the API returns a non-success payload or transport fails."""


def _settings():
    return db.get_settings()


def _headers(settings):
    return {
        "apikey": settings.get("api_key", ""),
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


def _url(settings, endpoint):
    base = settings.get("api_base_url", "").rstrip("/")
    return f"{base}/{endpoint.lstrip('/')}"


def _ssl_verify(settings):
    return settings.get("ssl_verify", "1") == "1"


def _post(endpoint_key, payload):
    """POST ``payload`` to the configured endpoint; return (response, settings)."""
    settings = _settings()
    endpoint = settings.get(endpoint_key)
    if not settings.get("api_key"):
        raise AVError("No API key configured. Set one on the Settings page first.")
    url = _url(settings, endpoint)
    try:
        resp = requests.post(
            url,
            json=payload,
            headers=_headers(settings),
            verify=_ssl_verify(settings),
            timeout=config.REQUEST_TIMEOUT,
        )
    except requests.RequestException as exc:
        raise AVError(f"Request to {url} failed: {exc}") from exc
    return resp, settings, endpoint


# --- Reading -----------------------------------------------------------------

def _build_read_payload(settings, filters, rows_count=200):
    return {
        "xml": False,
        "flatten": False,
        "entities": [
            {
                "entity": settings.get("default_entity", "Event"),
                "firstRowIndex": 0,
                "rowsCount": rows_count,
                "columns": [],
                "filters": filters,
                "orderby": [],
                "include": [],
            }
        ],
    }


def _extract_rows(body):
    """Pull the flat list of row Data dicts out of a getdata response body.

    The API always wraps responses as {"Status": 0|3, "Data": ...}. Status 3
    means Data is an error message string.
    """
    if isinstance(body, list):
        # Some deployments return the ApiDataEntity[] array directly.
        data = body
    elif isinstance(body, dict):
        status = body.get("Status")
        if status == 3:
            raise AVError(f"ArtsVision error: {body.get('Data')}")
        data = body.get("Data", body)
    else:
        raise AVError(f"Unexpected response (not JSON object/array): {body!r:.200}")
    rows = []
    if isinstance(data, list):
        for block in data:
            for row in (block or {}).get("Rows", []) or []:
                rows.append(row.get("Data", {}))
    return rows


def get_events(date_from, date_to, status=None):
    """Fetch events between two MM/DD/YYYY dates (from inclusive, to exclusive)."""
    settings = _settings()
    filters = [
        {"field": "Date", "operator": "GreaterOrEqual", "value": date_from},
        {"field": "Date", "operator": "Less", "value": date_to},
    ]
    if status:
        filters.append({"field": "Event Status", "operator": "Equal", "value": status})
    payload = _build_read_payload(settings, filters)
    resp, _, _ = _post("read_endpoint", payload)
    try:
        body = resp.json()
    except ValueError as exc:
        raise AVError(f"Non-JSON response ({resp.status_code}): {resp.text[:500]}") from exc
    return _extract_rows(body)


def get_event(event_id):
    """Fetch a single event by its Id. Returns the field dict or None."""
    settings = _settings()
    filters = [{"field": "Id", "operator": "Equal", "value": int(event_id)}]
    payload = _build_read_payload(settings, filters, rows_count=1)
    resp, _, _ = _post("read_endpoint", payload)
    try:
        body = resp.json()
    except ValueError as exc:
        raise AVError(f"Non-JSON response ({resp.status_code}): {resp.text[:500]}") from exc
    rows = _extract_rows(body)
    return rows[0] if rows else None


def get_entity_names():
    """Call GetEntityNames — a cheap, read-only way to verify the API key."""
    settings = _settings()
    if not settings.get("api_key"):
        raise AVError("No API key configured. Set one on the Settings page first.")
    url = _url(settings, "getentitynames")
    try:
        resp = requests.get(
            url,
            headers=_headers(settings),
            verify=_ssl_verify(settings),
            timeout=config.REQUEST_TIMEOUT,
        )
    except requests.RequestException as exc:
        raise AVError(f"Request to {url} failed: {exc}") from exc
    try:
        body = resp.json()
    except ValueError as exc:
        raise AVError(f"Non-JSON response ({resp.status_code}): {resp.text[:300]}") from exc
    if isinstance(body, dict):
        if body.get("Status") == 3:
            raise AVError(f"ArtsVision error: {body.get('Data')}")
        return body.get("Data", [])
    return body


# --- Writing (experimental) --------------------------------------------------

def build_write_payload(settings, event_id, changes):
    """Build the SaveData body for a single modified Event row.

    SaveData accepts one ApiDataEntity: {Entity, Rows: [ApiDataRow, ...]}.
    Each row is {RowState, Data, Entities}. ``changes`` is a {field: new_value}
    dict of only the fields that changed; the primary key (Id) is always
    included so the server can locate the row. RowState 1 = Modified.
    """
    row_state = int(settings.get("write_row_state", "1"))
    data = {"Id": int(event_id)}
    data.update(changes)
    return {
        "Entity": settings.get("default_entity", "Event"),
        "Rows": [
            {"RowState": row_state, "Data": data, "Entities": None}
        ],
    }


def write_event(event_id, changes):
    """POST a modified Event row back to the configured write endpoint.

    Returns a dict describing the attempt (endpoint, request, status, body, ok)
    so the caller can display and log the full round-trip. Never raises for a
    non-2xx HTTP status — the whole point is to observe what AV sends back.
    """
    settings = _settings()
    payload = build_write_payload(settings, event_id, changes)
    endpoint = settings.get("write_endpoint")
    result = {
        "endpoint": _url(settings, endpoint),
        "request": payload,
        "status": None,
        "body": None,
        "ok": False,
    }
    try:
        resp, _, _ = _post("write_endpoint", payload)
    except AVError as exc:
        result["body"] = str(exc)
        return result

    result["status"] = resp.status_code
    try:
        body = resp.json()
        result["body"] = body
        # Treat HTTP 2xx AND (Status 0 or absent) as success.
        api_status = body.get("Status") if isinstance(body, dict) else None
        result["ok"] = resp.ok and api_status in (0, None)
    except ValueError:
        result["body"] = resp.text
        result["ok"] = resp.ok
    return result
