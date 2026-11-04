"""One-command load run: stub upstream + gateway + seed + k6 (when installed).

The numbers are only meaningful with PostgreSQL and a pre-seeded month of usage.
Memory storage gives a functional smoke test, not a baseline.

Example:
  uv run python scripts/loadtest/run_loadtest.py --rate 40 --duration 60s --stream

PostgreSQL:
  $env:GATEWAY_DATABASE_URL = "postgresql+asyncpg://gateway:gateway@127.0.0.1:5432/gateway"
  uv run python scripts/loadtest/run_loadtest.py --storage postgres --rate 100 --duration 120s
  uv run python scripts/loadtest/warm_usage.py --rows 200000
"""

from __future__ import annotations

import argparse
import asyncio
import os
import secrets
import shutil
import socket
import subprocess
import sys
import time

import httpx

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _free_port(preferred: int) -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        if probe.connect_ex(("127.0.0.1", preferred)) != 0:
            return preferred
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


def _wait_ready(base_url: str, path: str, timeout_seconds: float = 20.0) -> None:
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        try:
            if httpx.get(f"{base_url}{path}", timeout=2.0).status_code == 200:
                return
        except httpx.HTTPError:
            pass
        time.sleep(0.25)
    raise SystemExit(f"service at {base_url} did not become ready")


def _run_seed(env: dict[str, str]) -> dict[str, str]:
    result = subprocess.run(
        [sys.executable, os.path.join(ROOT, "scripts", "loadtest", "seed.py")],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )
    if result.returncode != 0:
        sys.stderr.write(result.stdout)
        sys.stderr.write(result.stderr)
        raise SystemExit("seed failed")
    exports: dict[str, str] = {}
    for line in result.stdout.splitlines():
        if line.startswith("export ") and "=" in line:
            name, _, value = line[len("export ") :].partition("=")
            exports[name.strip()] = value.strip()
    if "GATEWAY_KEY" not in exports:
        raise SystemExit(f"seed did not return a key:\n{result.stdout}")
    return exports


def _smoke(gateway_url: str, key: str, model: str) -> None:
    response = httpx.post(
        f"{gateway_url}/v1/chat/completions",
        headers={"Authorization": f"Bearer {key}"},
        json={"model": model, "messages": [{"role": "user", "content": "hello"}]},
        timeout=30.0,
    )
    if response.status_code != 200:
        raise SystemExit(f"smoke request failed: {response.status_code} {response.text}")
    print("smoke: ok")


def _python_smoke_load(
    gateway_url: str,
    key: str,
    model: str,
    *,
    rate: int,
    seconds: float,
    stream: bool,
) -> None:
    """Tiny built-in load just to prove the path and populate metrics.

    Not a benchmark: the client shares the host and is Python. Use k6 for numbers.
    """

    async def run() -> None:
        latencies: list[float] = []
        errors = 0
        concurrency = max(1, rate)
        semaphore = asyncio.Semaphore(concurrency)

        async with httpx.AsyncClient(base_url=gateway_url, timeout=60.0) as client:

            async def one() -> None:
                nonlocal errors
                async with semaphore:
                    started = time.perf_counter()
                    try:
                        response = await client.post(
                            "/v1/chat/completions",
                            headers={"Authorization": f"Bearer {key}"},
                            json={
                                "model": model,
                                "messages": [{"role": "user", "content": "load"}],
                                "stream": stream,
                            },
                        )
                        if response.status_code != 200:
                            errors += 1
                    except httpx.HTTPError:
                        errors += 1
                    latencies.append((time.perf_counter() - started) * 1000)

            start = time.perf_counter()
            tasks: list[asyncio.Task[None]] = []
            for index in range(int(rate * seconds)):
                delay = start + index / rate - time.perf_counter()
                if delay > 0:
                    await asyncio.sleep(delay)
                tasks.append(asyncio.create_task(one()))
            await asyncio.gather(*tasks)

        latencies.sort()
        p95 = latencies[max(int(len(latencies) * 0.95) - 1, 0)] if latencies else 0.0
        print(
            "python smoke load (not a benchmark): "
            f"{len(latencies)} requests, {errors} errors, p95 {p95:.0f} ms"
        )

    asyncio.run(run())


def _print_metrics(port: int) -> None:
    try:
        text = httpx.get(f"http://127.0.0.1:{port}/metrics", timeout=5.0).text
    except httpx.HTTPError as exc:
        print(f"metrics unavailable: {exc}")
        return
    prefixes = (
        "gateway_requests_total",
        "gateway_upstream_requests_total",
        "gateway_upstream_ttft_seconds_count",
        "gateway_upstream_ttft_seconds_sum",
        "gateway_rejections_total",
    )
    print("gateway metrics:")
    for line in text.splitlines():
        if line.startswith(prefixes) and "_bucket" not in line:
            print(f"  {line}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rate", type=int, default=20)
    parser.add_argument("--duration", default="60s")
    parser.add_argument("--stream", action="store_true")
    parser.add_argument("--users", type=int, default=50)
    parser.add_argument("--max-users", type=int, default=500)
    parser.add_argument("--storage", choices=("memory", "postgres"), default="memory")
    parser.add_argument("--ttfb-ms", type=int, default=40)
    parser.add_argument("--token-ms", type=int, default=15)
    parser.add_argument("--tokens", type=int, default=64)
    parser.add_argument("--error-rate", type=float, default=0.0)
    parser.add_argument("--skip-k6", action="store_true")
    parser.add_argument("--plan-tokens", type=int, default=None)
    parser.add_argument("--monthly-cost-budget", default=None)
    parser.add_argument("--price-input-per-million", default=None)
    parser.add_argument("--price-output-per-million", default=None)
    parser.add_argument("--allow-overage", action="store_true")
    parser.add_argument("--clear-billing", action="store_true")
    args = parser.parse_args()

    gateway_port = _free_port(4000)
    stub_port = _free_port(4100)
    gateway_url = f"http://127.0.0.1:{gateway_port}"
    stub_url = f"http://127.0.0.1:{stub_port}"
    metrics_port = _free_port(9464)

    base_env = os.environ.copy()
    base_env.update(
        {
            "GATEWAY_ENVIRONMENT": "test",
            "GATEWAY_MASTER_KEY": secrets.token_urlsafe(32),
            "GATEWAY_BOOTSTRAP_ADMIN_USERNAME": "loadtest-admin",
            "GATEWAY_BOOTSTRAP_ADMIN_PASSWORD": "loadtest-admin-password",
            "GATEWAY_STORAGE_BACKEND": args.storage,
            "GATEWAY_OPENAI_API_KEY": "stub-key",
            "GATEWAY_OPENAI_BASE_URL": f"{stub_url}/v1",
            "GATEWAY_LOG_LEVEL": "WARNING",
            "GATEWAY_METRICS_ENABLED": "true",
            "GATEWAY_METRICS_PORT": str(metrics_port),
            "GATEWAY_TRACING_ENABLED": "false",
        }
    )
    if args.storage == "postgres" and not base_env.get("GATEWAY_DATABASE_URL"):
        raise SystemExit("--storage postgres requires GATEWAY_DATABASE_URL")

    stub_env = base_env | {
        "STUB_PORT": str(stub_port),
        "STUB_TTFB_MS": str(args.ttfb_ms),
        "STUB_TOKEN_MS": str(args.token_ms),
        "STUB_TOKENS": str(args.tokens),
        "STUB_ERROR_RATE": str(args.error_rate),
    }
    stub = subprocess.Popen(
        [sys.executable, os.path.join(ROOT, "scripts", "loadtest", "stub_upstream.py")],
        cwd=ROOT,
        env=stub_env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    gateway = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "llm_gateway.app:create_app",
            "--factory",
            "--host",
            "127.0.0.1",
            "--port",
            str(gateway_port),
        ],
        cwd=ROOT,
        env=base_env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    try:
        _wait_ready(stub_url, "/healthz")
        _wait_ready(gateway_url, "/readyz")
        seed_env = base_env | {
            "GATEWAY_URL": gateway_url,
            "ADMIN_USERNAME": "loadtest-admin",
            "ADMIN_PASSWORD": "loadtest-admin-password",
        }
        if args.plan_tokens is not None:
            seed_env["PLAN_TOKENS"] = str(args.plan_tokens)
        if args.monthly_cost_budget is not None:
            seed_env["MONTHLY_COST_BUDGET"] = args.monthly_cost_budget
        if args.price_input_per_million is not None:
            seed_env["PRICE_INPUT_PER_MILLION"] = args.price_input_per_million
        if args.price_output_per_million is not None:
            seed_env["PRICE_OUTPUT_PER_MILLION"] = args.price_output_per_million
        if args.allow_overage:
            seed_env["ALLOW_OVERAGE"] = "true"
        if args.clear_billing:
            seed_env["CLEAR_BILLING"] = "true"
        exports = _run_seed(seed_env)
        key = exports["GATEWAY_KEY"]
        model = exports["GATEWAY_MODEL"]
        _smoke(gateway_url, key, model)

        print(f"gateway: {gateway_url}  metrics: http://127.0.0.1:{metrics_port}/metrics")
        print(f"model: {model}  stream: {args.stream}")

        if args.skip_k6 or shutil.which("k6") is None:
            print("k6 is not installed; run the same numbers manually with:")
            print(
                "  k6 run scripts/loadtest/k6/chat.js "
                f"-e GATEWAY_URL={gateway_url} -e GATEWAY_KEY={key} "
                f"-e GATEWAY_MODEL={model} -e STREAM={str(args.stream).lower()} "
                f"-e RATE={args.rate} -e DURATION={args.duration}"
            )
            _python_smoke_load(
                gateway_url,
                key,
                model,
                rate=min(args.rate, 20),
                seconds=5.0,
                stream=args.stream,
            )
            _print_metrics(metrics_port)
            return 0

        k6_env = os.environ.copy() | {
            "GATEWAY_URL": gateway_url,
            "GATEWAY_KEY": key,
            "GATEWAY_MODEL": model,
            "STREAM": str(args.stream).lower(),
            "RATE": str(args.rate),
            "DURATION": args.duration,
            "VUS": str(args.users),
            "MAX_VUS": str(args.max_users),
        }
        return subprocess.call(
            ["k6", "run", os.path.join(ROOT, "scripts", "loadtest", "k6", "chat.js")],
            cwd=ROOT,
            env=k6_env,
        )
    finally:
        for process in (gateway, stub):
            process.terminate()
        for process in (gateway, stub):
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()


if __name__ == "__main__":
    sys.exit(main())
