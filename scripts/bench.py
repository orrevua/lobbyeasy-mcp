"""Latency of tool calls through the full MCP stack (validation, middleware, audit,
serialization), per backend. Prints a markdown table for the README.

    uv run python scripts/bench.py            # memory + postgres (if reachable)
"""

from __future__ import annotations

import statistics
import time

import anyio
import psycopg
from mcp import Client

from lobbyeasy_mcp.config import Settings
from lobbyeasy_mcp.fixtures import DEMO_DAY
from lobbyeasy_mcp.server import build_server

CALLS = [
    ("list_pending_packages", {"limit": 20}),
    ("search_packages", {"filters": {"resident_name": "souza"}, "limit": 5}),
    ("find_residents", {"apartment": "A-101"}),
    ("get_apartment_summary", {"apartment": "B-101"}),
    ("get_daily_stats", {"day": DEMO_DAY}),
]
N = 50


async def bench(settings: Settings) -> dict[str, tuple[float, float]]:
    out = {}
    # Generous rate limit so the benchmark measures latency, not the limiter.
    settings = settings.model_copy(
        update={"rate_limit_capacity": 10_000, "rate_limit_refill_per_second": 1000}
    )
    async with Client(build_server(settings)) as client:
        for name, args in CALLS:
            await client.call_tool(name, args)  # warm-up
            samples = []
            for _ in range(N):
                t0 = time.perf_counter()
                result = await client.call_tool(name, args)
                samples.append((time.perf_counter() - t0) * 1000)
                assert not result.is_error, result.content[0].text
            samples.sort()
            out[name] = (statistics.median(samples), samples[int(0.95 * N) - 1])
    return out


async def main() -> None:
    backends = {"memory": Settings(_env_file=None)}  # type: ignore[call-arg]
    pg = Settings(_env_file=None, backend="postgres")  # type: ignore[call-arg]
    try:
        psycopg.connect(pg.database_url, connect_timeout=2).close()
        backends["postgres (local)"] = pg
    except psycopg.Error:
        print("(postgres unreachable, skipped)")
    results = {label: await bench(s) for label, s in backends.items()}
    labels = list(results)
    print(f"| tool | {' | '.join(f'{label} p50 / p95 (ms)' for label in labels)} |")
    print("|---|" + "---|" * len(labels))
    for name, _ in CALLS:
        cells = [f"{results[label][name][0]:.2f} / {results[label][name][1]:.2f}" for label in labels]
        print(f"| `{name}` | {' | '.join(cells)} |")


if __name__ == "__main__":
    anyio.run(main)
