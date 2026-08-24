"""Retry policy with bounded retries for LLM calls."""

from __future__ import annotations

import asyncio
import logging
import random
from typing import Any, Callable, TypeVar

from app.llm.schemas import LLMError, LLMRateLimitError, LLMServerError, LLMTimeoutError

logger = logging.getLogger(__name__)

T = TypeVar("T")


class RetryPolicy:
    """Bounded retry policy for LLM API calls.

    Retries on:
    - Timeout (up to max_retries)
    - Rate limit 429 (with exponential backoff + jitter)
    - Server error 5xx (up to max_retries)

    Does NOT retry on:
    - Bad request 4xx (except 429)
    - Malformed response
    - Auth errors
    """

    def __init__(
        self,
        max_retries: int = 3,
        base_delay: float = 1.0,
        max_delay: float = 30.0,
    ) -> None:
        self.max_retries = max_retries
        self.base_delay = base_delay
        self.max_delay = max_delay

    async def execute(
        self,
        func: Callable[..., Any],
        *args: Any,
        **kwargs: Any,
    ) -> Any:
        """Execute a function with bounded retries.

        Retries only on retryable errors (timeout, 429, 5xx).
        """
        last_error: Exception | None = None

        for attempt in range(self.max_retries + 1):
            try:
                return await func(*args, **kwargs)
            except LLMTimeoutError as e:
                last_error = e
                delay = self._get_delay(attempt)
                logger.warning(
                    "LLM timeout (attempt %d/%d), retrying in %.1fs",
                    attempt + 1,
                    self.max_retries + 1,
                    delay,
                )
                await asyncio.sleep(delay)
            except LLMRateLimitError as e:
                last_error = e
                delay = self._get_delay(attempt, factor=2.0)
                logger.warning(
                    "LLM rate limited (attempt %d/%d), retrying in %.1fs",
                    attempt + 1,
                    self.max_retries + 1,
                    delay,
                )
                await asyncio.sleep(delay)
            except LLMServerError as e:
                last_error = e
                delay = self._get_delay(attempt)
                logger.warning(
                    "LLM server error (attempt %d/%d), retrying in %.1fs",
                    attempt + 1,
                    self.max_retries + 1,
                    delay,
                )
                await asyncio.sleep(delay)
            except LLMError:
                # Non-retryable LLM error (bad request, malformed, auth)
                raise
            except Exception as e:
                # Unknown error — don't retry
                raise LLMError(f"Unexpected error: {e}") from e

        # All retries exhausted
        raise LLMError(
            f"All {self.max_retries + 1} attempts failed. Last error: {last_error}"
        ) from last_error

    def _get_delay(self, attempt: int, factor: float = 1.0) -> float:
        """Calculate delay with exponential backoff + jitter."""
        delay = min(self.base_delay * (2**attempt) * factor, self.max_delay)
        # Add jitter (±25%)
        jitter = delay * 0.25 * (2 * random.random() - 1)
        return max(0.1, delay + jitter)
