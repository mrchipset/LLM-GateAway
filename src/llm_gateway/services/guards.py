"""Request guards that bound cost and memory before anything expensive happens.

These are not a content policy. They bound the blast radius of one request: a single
oversized prompt could otherwise overshoot a monthly budget by a large multiple, because
budgets are checked before the call and settled afterwards.

Token limits are expressed in characters. The gateway has no provider tokenizer, so a
character budget is an explicit approximation; the error names the limit that was hit so
the client can act on it.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from llm_gateway.config import Settings
from llm_gateway.errors import ApiError, ApiErrorCode
from llm_gateway.logging import get_logger
from llm_gateway.metrics import current_metrics
from llm_gateway.schemas.chat import ChatCompletionRequest

logger = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class RequestLimits:
    max_messages: int
    max_prompt_chars: int
    max_tokens_limit: int
    max_tools: int


def limits_from_settings(settings: Settings) -> RequestLimits:
    return RequestLimits(
        max_messages=settings.max_messages,
        max_prompt_chars=settings.max_prompt_chars,
        max_tokens_limit=settings.max_tokens_limit,
        max_tools=settings.max_tools,
    )


def _exceeded(*, message: str, param: str) -> ApiError:
    current_metrics().rejections.add(1, {"reason": "request_limit"})
    return ApiError(
        status_code=400,
        code=ApiErrorCode.REQUEST_LIMIT_EXCEEDED,
        message=message,
        error_type="invalid_request_error",
        param=param,
    )


def prompt_size(message: object) -> int:
    """Wire size of one message, including tool calls and provider-specific extras."""
    try:
        return len(json.dumps(message, ensure_ascii=False, default=str))
    except (TypeError, ValueError):
        return 0


def enforce_chat_request_limits(
    request: ChatCompletionRequest,
    *,
    limits: RequestLimits,
) -> None:
    if len(request.messages) > limits.max_messages:
        logger.warning(
            "request_limit_exceeded",
            extra={"limit": "messages", "count": len(request.messages)},
        )
        raise _exceeded(
            message=f"At most {limits.max_messages} messages are allowed",
            param="messages",
        )

    total_chars = sum(
        prompt_size(message.model_dump(mode="json", exclude_none=True))
        for message in request.messages
    )
    if total_chars > limits.max_prompt_chars:
        logger.warning(
            "request_limit_exceeded",
            extra={"limit": "prompt_chars", "count": total_chars},
        )
        raise _exceeded(
            message=(
                f"The messages exceed the {limits.max_prompt_chars} character budget; "
                "shorten the conversation or send only the latest turn"
            ),
            param="messages",
        )

    requested = request.max_completion_tokens or request.max_tokens
    if requested is not None and requested > limits.max_tokens_limit:
        logger.warning(
            "request_limit_exceeded",
            extra={"limit": "max_tokens", "count": requested},
        )
        raise _exceeded(
            message=f"max_tokens must be at most {limits.max_tokens_limit}",
            param="max_completion_tokens" if request.max_completion_tokens else "max_tokens",
        )

    if request.tools is not None and len(request.tools) > limits.max_tools:
        logger.warning(
            "request_limit_exceeded",
            extra={"limit": "tools", "count": len(request.tools)},
        )
        raise _exceeded(
            message=f"At most {limits.max_tools} tools are allowed",
            param="tools",
        )
