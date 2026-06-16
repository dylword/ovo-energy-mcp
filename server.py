"""OVO Energy MCP server.

Wraps the community `ovoenergy` Python client (timmo001/ovoenergy) and exposes
its data as MCP tools over Streamable HTTP, so an n8n "MCP Client Tool" node can
call them.

Auth: the server holds a single set of OVO credentials in env vars
(OVO_USERNAME / OVO_PASSWORD) — this is meant to run as *your* personal server.
The OVO session/token is cached and refreshed automatically.

These OVO endpoints are unofficial/internal and can break without notice.
"""

from __future__ import annotations

import os
from dataclasses import asdict, is_dataclass
from datetime import date, timedelta
from typing import Any

import aiohttp
from mcp.server.fastmcp import FastMCP

from ovoenergy import OVOEnergy

OVO_USERNAME = os.environ.get("OVO_USERNAME", "")
OVO_PASSWORD = os.environ.get("OVO_PASSWORD", "")

# Endpoint for account balance (internal GraphQL). The exact query is not
# published; confirm it from your browser's devtools (Network tab) when logged
# in to my.ovoenergy.com, then override via env if needed.
OVO_BALANCE_URL = os.environ.get(
    "OVO_BALANCE_URL", "https://smartpaymapi.ovoenergy.com/bast/api/graphql"
)
OVO_BALANCE_QUERY = os.environ.get(
    "OVO_BALANCE_QUERY",
    "query { account { balance { amount currencyUnit } } }",
)

mcp = FastMCP(
    name="ovo-energy",
    host=os.environ.get("HOST", "0.0.0.0"),
    port=int(os.environ.get("PORT", "8080")),
)

# --- Shared OVO client -------------------------------------------------------

_session: aiohttp.ClientSession | None = None
_client: OVOEnergy | None = None


def _to_dict(obj: Any) -> Any:
    """Best-effort conversion of dataclass results to plain JSON-able dicts."""
    if is_dataclass(obj) and not isinstance(obj, type):
        return asdict(obj)
    if isinstance(obj, list):
        return [_to_dict(i) for i in obj]
    return obj


async def _get_client() -> OVOEnergy:
    """Return an authenticated OVOEnergy client, (re)authenticating as needed."""
    global _session, _client

    if not OVO_USERNAME or not OVO_PASSWORD:
        raise RuntimeError("OVO_USERNAME / OVO_PASSWORD env vars are not set")

    if _session is None or _session.closed:
        _session = aiohttp.ClientSession()
        _client = None

    if _client is None:
        _client = OVOEnergy(client_session=_session)

    # Authenticate on first use or when the OAuth token has expired.
    if getattr(_client, "account_id", None) is None or _client.oauth_expired:
        if not await _client.authenticate(OVO_USERNAME, OVO_PASSWORD):
            raise RuntimeError("OVO authentication failed — check credentials")
        await _client.bootstrap_accounts()

    return _client


def _yesterday() -> str:
    return (date.today() - timedelta(days=1)).isoformat()


def _this_month() -> str:
    return date.today().strftime("%Y-%m")


# --- Tools -------------------------------------------------------------------


@mcp.tool()
async def ovo_half_hourly_usage(day: str | None = None) -> dict:
    """Half-hourly electricity & gas usage (and cost) for a single day.

    Args:
        day: Date as YYYY-MM-DD. Defaults to yesterday (latest available — OVO
             data lags ~1 day).
    """
    client = await _get_client()
    result = await client.get_half_hourly_usage(day or _yesterday())
    return {"date": day or _yesterday(), "usage": _to_dict(result)}


@mcp.tool()
async def ovo_daily_usage(month: str | None = None) -> dict:
    """Daily electricity & gas usage (and cost) across a whole month.

    Args:
        month: Month as YYYY-MM. Defaults to the current month.
    """
    client = await _get_client()
    result = await client.get_daily_usage(month or _this_month())
    return {"month": month or _this_month(), "usage": _to_dict(result)}


@mcp.tool()
async def ovo_accounts() -> dict:
    """List the OVO accounts on this login and the active account id."""
    client = await _get_client()
    return {
        "active_account_id": getattr(client, "account_id", None),
        "customer_id": str(getattr(client, "customer_id", "")),
    }


@mcp.tool()
async def ovo_carbon_footprint() -> dict:
    """Carbon footprint data for the account."""
    client = await _get_client()
    return _to_dict(await client.get_footprint())


@mcp.tool()
async def ovo_carbon_intensity() -> dict:
    """Current grid carbon intensity."""
    client = await _get_client()
    return _to_dict(await client.get_carbon_intensity())


def _sum_fuel(entries: Any) -> dict:
    """Sum consumption (kWh) and cost across a list of daily usage entries."""
    total_kwh = 0.0
    total_cost = 0.0
    currency = None
    count = 0
    for entry in entries or []:
        entry = _to_dict(entry)
        if not isinstance(entry, dict):
            continue
        consumption = entry.get("consumption")
        if isinstance(consumption, (int, float)):
            total_kwh += float(consumption)
        cost = entry.get("cost") or {}
        amount = cost.get("amount") if isinstance(cost, dict) else None
        if amount is not None:
            try:
                total_cost += float(amount)
            except (TypeError, ValueError):
                pass
            currency = currency or cost.get("currencyUnit") or cost.get("currency")
        count += 1
    return {
        "days": count,
        "consumption_kwh": round(total_kwh, 3),
        "cost": round(total_cost, 2),
        "currency": currency,
    }


@mcp.tool()
async def ovo_spend_summary(month: str | None = None) -> dict:
    """Aggregated spend & consumption for a month — electricity, gas, and total.

    Convenient single-call total for feeding a sheet or a chat summary, instead
    of summing the per-day rows from `ovo_daily_usage` yourself.

    Args:
        month: Month as YYYY-MM. Defaults to the current month.
    """
    month = month or _this_month()
    client = await _get_client()
    usage = _to_dict(await client.get_daily_usage(month))

    electricity = _sum_fuel(usage.get("electricity") if isinstance(usage, dict) else None)
    gas = _sum_fuel(usage.get("gas") if isinstance(usage, dict) else None)
    currency = electricity["currency"] or gas["currency"]
    total_cost = round(electricity["cost"] + gas["cost"], 2)

    return {
        "month": month,
        "electricity": electricity,
        "gas": gas,
        "total": {
            "consumption_kwh": round(
                electricity["consumption_kwh"] + gas["consumption_kwh"], 3
            ),
            "cost": total_cost,
            "currency": currency,
        },
    }


@mcp.tool()
async def ovo_account_balance() -> dict:
    """Account balance / billing position.

    NOTE: not part of the underlying library — uses OVO's internal GraphQL
    endpoint with the authenticated session cookies. If this returns an error,
    confirm the query/URL from browser devtools and set OVO_BALANCE_QUERY /
    OVO_BALANCE_URL env vars.
    """
    client = await _get_client()
    assert _session is not None
    async with _session.post(
        OVO_BALANCE_URL,
        json={"query": OVO_BALANCE_QUERY},
        headers={"Content-Type": "application/json"},
    ) as resp:
        text = await resp.text()
        try:
            data = await resp.json()
        except Exception:
            data = {"raw": text}
        return {"status": resp.status, "data": data}


if __name__ == "__main__":
    mcp.run(transport="streamable-http")
