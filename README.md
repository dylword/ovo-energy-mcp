# OVO Energy MCP server

An MCP server that exposes OVO Energy data as tools for **n8n** (via the
*MCP Client Tool* node). Wraps the community
[`timmo001/ovoenergy`](https://github.com/timmo001/ovoenergy) Python client.

> ⚠️ OVO's APIs are unofficial/internal. They can change or break without
> notice, and data lags ~1 day (not real-time).

## Tools

| Tool | What it returns |
|------|-----------------|
| `ovo_half_hourly_usage(day?)` | Half-hourly usage + cost for a day (default: yesterday) |
| `ovo_daily_usage(month?)` | Daily usage + cost across a month (default: current month) |
| `ovo_spend_summary(month?)` | Aggregated electricity/gas/total kWh + cost for a month |
| `ovo_accounts()` | Active account id + customer id |
| `ovo_carbon_footprint()` | Carbon footprint |
| `ovo_carbon_intensity()` | Grid carbon intensity |
| `ovo_account_balance()` | Account balance / billing (see note below) |

### Billing note
The underlying library has **no balance method** (open upstream issue). The
`ovo_account_balance` tool calls OVO's internal GraphQL endpoint using the
authenticated session. If it errors, log in to my.ovoenergy.com, open browser
devtools → Network, find the balance request, and set these env vars to match:

- `OVO_BALANCE_URL`
- `OVO_BALANCE_QUERY`

Daily/half-hourly **cost** is already included in the usage tools, so you get
spend data without the balance endpoint.

## Env vars

| Var | Required | Default |
|-----|----------|---------|
| `OVO_USERNAME` | yes | — |
| `OVO_PASSWORD` | yes | — |
| `PORT` | no | `8080` (Railway sets this) |
| `OVO_BALANCE_URL` | no | OVO GraphQL endpoint |
| `OVO_BALANCE_QUERY` | no | best-effort query |

## Run locally

```bash
pip install -r requirements.txt
export OVO_USERNAME="you@example.com"
export OVO_PASSWORD="..."
python server.py
# MCP Streamable HTTP endpoint: http://localhost:8080/mcp
```

## Deploy on Railway

1. Push this folder to a repo (or `railway up` from here).
2. New service from the repo → it builds the Dockerfile.
3. Set `OVO_USERNAME` and `OVO_PASSWORD` in the service variables.
4. Generate a public domain. Your MCP endpoint is `https://<domain>/mcp`.

## Connect from n8n

1. Add an **MCP Client Tool** node (or use it inside an AI Agent node).
2. Connection type: **HTTP Streamable**.
3. Endpoint URL: `https://<your-railway-domain>/mcp`
4. The OVO tools above appear and can be called from your workflow / agent.
