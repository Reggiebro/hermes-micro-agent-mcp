#!/usr/bin/env python3
"""Hermes Micro-Agent as an MCP server.

Why this exists
---------------
An x402 endpoint is only reachable if an agent can *find* it. The x402
directories are thin, but MCP registries (Smithery, mcp.so, Glama, PulseMCP,
mcp.run) are where agents actually look for tools — mcp.so even has a
"Pay-per-use data and tools for AI agents" category, which is this exact model.

This exposes the same 20 paid micro-tasks over MCP, so an agent that discovers
us in a registry can call them directly. It is additive: the HTTP /task
endpoint and its 402 gate are untouched, and this server never executes a paid
task without payment — it reports the price and how to pay.

Free tools (price, tasks, verify) let an agent price a call before paying. That
is the entry point and it is what makes discovery worth anything.

Run: python mcp_server.py        (stdio, for registry hosting)
"""

import json
import os
import re
import sys
import urllib.error
import urllib.request
from typing import Any

# ── import the task implementations from the existing service ──────────────
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from hermes_server import PRICES, do_task, IMPLEMENTED  # noqa: E402

try:
    from mcp.server.fastmcp import FastMCP
    from mcp.server.transport_security import TransportSecuritySettings
except ImportError:  # pragma: no cover
    print("mcp package required: pip install 'mcp>=1.9'", file=sys.stderr)
    raise

RECEIVER = os.environ.get(
    "NODE_WALLET_ADDRESS",
    "0x078fE079A9440631Bc6AD722D7143dC382b4ea4f")
BASE = os.environ.get("AGENT_BASE_URL", "https://92.5.95.177.sslip.io")
USDC_BASE = "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913"

mcp = FastMCP("hermes-micro-agent")


def _rpc(method: str, params: dict) -> dict:
    """Free JSON-RPC helper — pricing and verification need no payment."""
    payload = json.dumps({"jsonrpc": "2.0", "id": 1, "method": method,
                          "params": params}).encode()
    req = urllib.request.Request(f"{BASE}/rpc", data=payload, method="POST")
    req.add_header("Content-Type", "application/json")
    req.add_header("User-Agent", "hermes-mcp/1.0")
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return json.loads(r.read().decode()).get("result", {})
    except Exception as e:
        return {"error": str(e)}


@mcp.tool()
def tasks() -> dict:
    """List every available micro-task and its price in USDC.

    Free to call. Use this to see what the agent can do before paying.
    """
    return {
        "service": "Hermes Micro-Agent",
        "public_api": BASE,
        "receiver": RECEIVER,
        "network": "Base",
        "asset": USDC_BASE,
        "tasks": {name: f"${PRICES[name]:.2f}" for name in sorted(PRICES)},
        "count": len(PRICES),
    }


@mcp.tool()
def price(task: str) -> dict:
    """Price one micro-task in USDC, plus the payment instructions.

    Free to call. The response is exactly what a buyer needs to pay.
    """
    if task not in PRICES:
        return {"error": f"unknown task '{task}'", "available": sorted(PRICES)}
    return {
        "task": task,
        "price_usdc": PRICES[task],
        "receiver": RECEIVER,
        "network": "base",
        "asset": USDC_BASE,
        "how_to_pay": (
            f"1. GET {BASE}/task?task={task} to receive the x402 challenge.\n"
            f"2. Send {PRICES[task]:.2f} USDC on Base to {RECEIVER} "
            f"(maxFeePerGas=0).\n"
            f"3. Resend the request with header X-Payment: <tx_hash>."),
        "api_endpoint": f"{BASE}/task?task={task}",
        "implemented": True,
    }


@mcp.tool()
def verify(tx_hash: str, min_cents: int = 1000) -> dict:
    """Verify a payment on-chain. Free to call.

    Use this after sending USDC and before retrying the paid request.
    """
    return _rpc("verify", {"tx_hash": tx_hash, "min_cents": min_cents})


@mcp.tool()
def execute(task: str, prompt: str, x_payment: str) -> dict:
    """Run one paid micro-task. Requires a real x402 payment first.

    This does NOT execute for free: it forwards to the paid /task endpoint and
    returns the server's answer, which is 402 unless the payment is confirmed.
    A task that is not implemented is refused rather than faked.

    Args:
        task: one of the task names from `tasks`
        prompt: the text to process
        x_payment: the Base transaction hash of your USDC payment
    """
    if task not in PRICES:
        return {"error": f"unknown task '{task}'", "available": sorted(PRICES)}
    if not x_payment:
        return {
            "error": "x_payment (transaction hash) is required",
            "how_to_pay": price(task)["how_to_pay"],
        }

    body = json.dumps({"task": task, "prompt": prompt}).encode()
    req = urllib.request.Request(f"{BASE}/task", data=body, method="POST")
    req.add_header("Content-Type", "application/json")
    req.add_header("X-Payment", x_payment)
    req.add_header("User-Agent", "hermes-mcp/1.0")
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        try:
            return json.loads(e.read().decode())
        except Exception:
            return {"error": f"HTTP {e.code}"}
    except Exception as e:
        return {"error": str(e)}


@mcp.tool()
def health() -> dict:
    """Service status. Free to call."""
    try:
        req = urllib.request.Request(f"{BASE}/health")
        req.add_header("User-Agent", "hermes-mcp/1.0")
        with urllib.request.urlopen(req, timeout=15) as r:
            return json.loads(r.read().decode())
    except Exception as e:
        return {"ok": False, "error": str(e)}


if __name__ == "__main__":
    # stdio by default (registry-hosted). Set MCP_TRANSPORT=streamable-http for a
    # public URL, which is what registries need to list us.
    transport = os.environ.get("MCP_TRANSPORT", "stdio")
    if transport == "streamable-http":
        mcp.settings.host = os.environ.get("MCP_HOST", "127.0.0.1")
        mcp.settings.port = int(os.environ.get("MCP_PORT", "8020"))

        # DNS-rebinding protection compares the Host header against
        # allowed_hosts and rejects anything else with "Invalid Host header".
        # nginx forwards the public host, so that host must be on the list or
        # every request through the proxy is refused. Set it explicitly rather
        # than disabling the protection: the same rule protects against a
        # rebinding attack if this port is ever exposed directly.
        public_host = os.environ.get("MCP_PUBLIC_HOST",
                                     "92.5.95.177.sslip.io")
        allowed = {h for h in (os.environ.get("MCP_ALLOWED_HOSTS", "").split(",")
                               if os.environ.get("MCP_ALLOWED_HOSTS") else []) if h}
        allowed.add(public_host)
        allowed.add(f"{public_host}:443")
        mcp.settings.transport_security = TransportSecuritySettings(
            enable_dns_rebinding_protection=True,
            allowed_hosts=sorted(allowed),
        )

        mcp.run(transport="streamable-http")
    else:
        mcp.run()
