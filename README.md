# Hermes Micro-Agent — MCP server

An MCP server that exposes 20 paid AI and data micro-tasks over the
[x402](https://x402.org) payments protocol. Agents can price a call for free,
then pay in USDC on Base and receive a verified result.

**Public endpoint (streamable HTTP):** https://92.5.95.177.sslip.io/mcp

## Tools

| Tool | Paid? | What it does |
|---|---|---|
| `tasks` | free | list every task and its price in USDC |
| `price` | free | price one task, with exact payment instructions |
| `verify` | free | check a payment landed on-chain |
| `health` | free | service status |
| `execute` | **paid** | run a task; requires a real x402 payment |

## How payment works

`execute` never runs for free. It forwards to the paid `/task` endpoint, which
answers `402 Payment Required` with the amount and our receiver address. The
caller sends USDC on Base, then resends with the transaction hash in the
`X-Payment` header. We verify the transfer on-chain before doing any work.

Tasks that are not implemented are refused, never faked.

## Tasks

Text: summarize, extract, keywords, sentiment, translate, rewrite, proofread
Code: python_debug, code_lint, code_explain, code_refactor, code_review
Data: json_minify, json_query, csv_to_json, hash, base64, convert
Media: describe_image, probe_media

Prices: $0.10–$0.25 USDC per call.

## Connect

```json
{
  "mcpServers": {
    "hermes-micro-agent": {
      "url": "https://92.5.95.177.sslip.io/mcp"
    }
  }
}
```

## HTTP API

The same service is also a plain HTTP API with an OpenAPI spec:

- `GET /tasks` — price list
- `GET /task?task=<name>` — receive the x402 challenge
- `POST /task` — execute (requires `X-Payment`)
- `POST /rpc` — free JSON-RPC: `price`, `discover`, `verify`, `echo`
- `GET /.well-known/x402` — x402 manifest
- `GET /openapi.json` — OpenAPI spec
