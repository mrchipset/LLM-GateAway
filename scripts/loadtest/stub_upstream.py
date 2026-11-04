"""Deterministic OpenAI-compatible upstream for load tests.

This is a stand-in for a real provider. It exists so a load run can vary latency,
streaming shape, and failures deterministically, without provider cost or rate limits.

Environment:
  STUB_HOST / STUB_PORT        bind address (default 127.0.0.1:4100)
  STUB_MODEL                   model name echoed in responses (default stub-model)
  STUB_TTFB_MS                 delay before the first streamed chunk (default 40)
  STUB_TOKEN_MS                delay between content chunks (default 15)
  STUB_TOKENS                  content chunks per response (default 64)
  STUB_ERROR_RATE              0..1 chance of an injected error (default 0)
  STUB_ERROR_STATUS            status code for injected errors (default 500)

Run: uv run python scripts/loadtest/stub_upstream.py
"""

from __future__ import annotations

import asyncio
import json
import os
import random
import time
from collections.abc import AsyncIterator

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse

MODEL = os.environ.get("STUB_MODEL", "stub-model")
TTFB_SECONDS = int(os.environ.get("STUB_TTFB_MS", "40")) / 1000
TOKEN_SECONDS = int(os.environ.get("STUB_TOKEN_MS", "15")) / 1000
TOKENS = int(os.environ.get("STUB_TOKENS", "64"))
ERROR_RATE = float(os.environ.get("STUB_ERROR_RATE", "0"))
ERROR_STATUS = int(os.environ.get("STUB_ERROR_STATUS", "500"))

app = FastAPI(title="LLM-GateAway load stub", docs_url=None, redoc_url=None)


def _prompt_tokens(messages: object) -> int:
    if not isinstance(messages, list):
        return 1
    words = 0
    for message in messages:
        if isinstance(message, dict):
            content = message.get("content")
            if isinstance(content, str):
                words += len(content.split())
    return max(words, 1)


def _frame(payload: dict[str, object]) -> bytes:
    return f"data: {json.dumps(payload)}\n\n".encode()


def _chunk(index: int, delta: dict[str, object], finish_reason: str | None) -> dict[str, object]:
    return {
        "id": "chatcmpl-stub",
        "object": "chat.completion.chunk",
        "created": int(time.time()),
        "model": MODEL,
        "choices": [{"index": 0, "delta": delta, "finish_reason": finish_reason}],
    }


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/v1/chat/completions", response_model=None)
async def chat(request: Request) -> JSONResponse | StreamingResponse:
    body = await request.json()
    body = body if isinstance(body, dict) else {}

    if ERROR_RATE > 0 and random.random() < ERROR_RATE:
        return JSONResponse(
            {"error": {"message": "injected upstream failure", "type": "server_error"}},
            status_code=ERROR_STATUS,
        )

    prompt_tokens = _prompt_tokens(body.get("messages"))
    completion_tokens = min(TOKENS, int(body.get("max_tokens") or TOKENS))
    usage = {
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": prompt_tokens + completion_tokens,
        "prompt_tokens_details": {"cached_tokens": 0},
    }

    if not body.get("stream"):
        await asyncio.sleep(TTFB_SECONDS + TOKEN_SECONDS * completion_tokens)
        return JSONResponse(
            {
                "id": "chatcmpl-stub",
                "object": "chat.completion",
                "created": int(time.time()),
                "model": MODEL,
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": "hello from the stub"},
                        "finish_reason": "stop",
                    }
                ],
                "usage": usage,
            }
        )

    async def frames() -> AsyncIterator[bytes]:
        await asyncio.sleep(TTFB_SECONDS)
        yield _frame(_chunk(0, {"role": "assistant", "content": ""}, None))
        for _ in range(completion_tokens):
            await asyncio.sleep(TOKEN_SECONDS)
            yield _frame(_chunk(0, {"content": "token "}, None))
        yield _frame(
            {
                "id": "chatcmpl-stub",
                "object": "chat.completion.chunk",
                "created": int(time.time()),
                "model": MODEL,
                "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
            }
        )
        usage_chunk = _chunk(0, {}, None)
        usage_chunk["choices"] = []
        usage_chunk["usage"] = usage
        yield _frame(usage_chunk)
        yield b"data: [DONE]\n\n"

    return StreamingResponse(frames(), media_type="text/event-stream")


def main() -> None:
    import uvicorn

    uvicorn.run(
        app,
        host=os.environ.get("STUB_HOST", "127.0.0.1"),
        port=int(os.environ.get("STUB_PORT", "4100")),
        log_level="warning",
    )


if __name__ == "__main__":
    main()
