"""Deterministic test pricing for provider token usage."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP


TEST_PRICING_VERSION = "test-pricing-v1"
_MILLION = Decimal("1000000")
_MONEY_QUANTUM = Decimal("0.00000001")


@dataclass(frozen=True, slots=True)
class TokenPricing:
    name: str
    input_per_million: Decimal
    cached_input_per_million: Decimal
    output_per_million: Decimal
    version: str = TEST_PRICING_VERSION


TEST_PRICING: dict[tuple[str, str], TokenPricing] = {
    ("openai", "gpt-4o-mini"): TokenPricing("openai-gpt-4o-mini", Decimal("0.15"), Decimal("0.075"), Decimal("0.60")),
    ("deepseek", "deepseek-chat"): TokenPricing("deepseek-chat", Decimal("0.27"), Decimal("0.07"), Decimal("1.10")),
    ("qwen", "qwen-plus"): TokenPricing("qwen-plus", Decimal("0.80"), Decimal("0.20"), Decimal("2.00")),
    ("anthropic", "claude-3-5-haiku"): TokenPricing("anthropic-claude-3-5-haiku", Decimal("0.80"), Decimal("0.08"), Decimal("4.00")),
}

TEST_DEFAULT_PRICING = TokenPricing("test-default", Decimal("1.00"), Decimal("0.50"), Decimal("1.00"))


def get_token_pricing(provider: str, model: str) -> TokenPricing:
    return TEST_PRICING.get((provider.casefold(), model), TEST_DEFAULT_PRICING)


def calculate_token_cost(
    provider: str,
    model: str,
    *,
    input_tokens: int,
    output_tokens: int,
    cached_input_tokens: int = 0,
    reasoning_tokens: int = 0,
) -> Decimal:
    values = (input_tokens, output_tokens, cached_input_tokens, reasoning_tokens)
    if any(value < 0 for value in values):
        raise ValueError("token 数不能为负数")
    pricing = get_token_pricing(provider, model)
    cached = min(cached_input_tokens, input_tokens)
    uncached = input_tokens - cached
    del reasoning_tokens
    cost = (
        Decimal(uncached) * pricing.input_per_million
        + Decimal(cached) * pricing.cached_input_per_million
        + Decimal(output_tokens) * pricing.output_per_million
    ) / _MILLION
    return cost.quantize(_MONEY_QUANTUM, rounding=ROUND_HALF_UP)


__all__ = ["TEST_DEFAULT_PRICING", "TEST_PRICING", "TEST_PRICING_VERSION", "TokenPricing", "calculate_token_cost", "get_token_pricing"]
