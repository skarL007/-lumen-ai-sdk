"""
Semantic Conventions — OTel GenAI + OpenInference + LumenAI Master.

Three-layer attribute schema for maximum portability and rich context.
"""

# ─── Layer 1: OTel GenAI Semantic Conventions (portability) ───────────────────

class GenAIAttributes:
    """Standard OTel GenAI attributes (OTEL SEMCONV v1.30+)."""
    OPERATION_NAME = "gen_ai.operation.name"          # chat | completion | embedding
    PROVIDER_NAME = "gen_ai.provider.name"            # anthropic | openai | ollama
    REQUEST_MODEL = "gen_ai.request.model"            # claude-sonnet-4-6
    RESPONSE_MODEL = "gen_ai.response.model"          # actual model used
    USAGE_INPUT_TOKENS = "gen_ai.usage.input_tokens"
    USAGE_OUTPUT_TOKENS = "gen_ai.usage.output_tokens"
    USAGE_CACHE_READ = "gen_ai.usage.cache_read.input_tokens"
    CONVERSATION_ID = "gen_ai.conversation.id"
    AGENT_ID = "gen_ai.agent.id"
    AGENT_NAME = "gen_ai.agent.name"
    AGENT_VERSION = "gen_ai.agent.version"
    TOOL_NAME = "gen_ai.tool.name"
    TOOL_CALL_ID = "gen_ai.tool.call.id"
    SYSTEM = "gen_ai.system"


# ─── Layer 2: OpenInference Attributes (rich semantics) ──────────────────────

class OpenInferenceAttributes:
    """OpenInference span attributes (Arize Phoenix compatible)."""
    SPAN_KIND = "openinference.span.kind"             # LLM | AGENT | TOOL | CHAIN
    TOKEN_COUNT_PROMPT = "llm.token_count.prompt"
    TOKEN_COUNT_COMPLETION = "llm.token_count.completion"
    COST_TOTAL = "llm.cost.total"
    COST_PROMPT = "llm.cost.prompt"
    COST_COMPLETION = "llm.cost.completion"
    MODEL_NAME = "llm.model_name"


class SpanKind:
    """OpenInference span kinds."""
    LLM = "LLM"
    AGENT = "AGENT"
    TOOL = "TOOL"
    CHAIN = "CHAIN"
    EMBEDDING = "EMBEDDING"
    RETRIEVER = "RETRIEVER"
    RERANKER = "RERANKER"


# ─── Layer 3: LumenAI Master Attributes (business context) ────────────────────

class LumenAIAttributes:
    """LumenAI Master custom attributes for multi-tenant agent observability."""
    TENANT_ID = "LumenAI.tenant_id"
    SESSION_ID = "LumenAI.session_id"
    AGENT_ID = "LumenAI.agent_id"
    PARENT_TOOL_USE_ID = "LumenAI.parent_tool_use_id"
    RUN_ID = "LumenAI.run_id"
    WORKFLOW_ID = "LumenAI.workflow_id"
    RETRY_COUNT = "LumenAI.retry_count"
    DEPTH = "LumenAI.depth"
    STEP_INDEX = "LumenAI.step_index"
    COST_USD = "LumenAI.cost_usd"


# ─── Model Pricing Table (per 1M tokens) ─────────────────────────────────────

PRICING_TABLE: dict[str, dict[str, float]] = {
    # ── Anthropic ────────────────────────────────────────────────────────
    "claude-opus-4-6":              {"input": 15.00, "output": 75.00, "cache_read": 1.50},
    "claude-sonnet-4-6":            {"input": 3.00,  "output": 15.00, "cache_read": 0.30},
    "claude-haiku-4-5":             {"input": 0.25,  "output": 1.25,  "cache_read": 0.025},
    "anthropic/claude-opus-4-6":    {"input": 15.00, "output": 75.00, "cache_read": 1.50},
    "anthropic/claude-sonnet-4-6":  {"input": 3.00,  "output": 15.00, "cache_read": 0.30},
    "anthropic/claude-haiku-4-5":   {"input": 0.25,  "output": 1.25,  "cache_read": 0.025},
    # ── OpenAI ───────────────────────────────────────────────────────────
    "gpt-4o":                       {"input": 2.50,  "output": 10.00, "cache_read": 1.25},
    "gpt-4o-mini":                  {"input": 0.15,  "output": 0.60,  "cache_read": 0.075},
    "gpt-4.1":                      {"input": 2.00,  "output": 8.00,  "cache_read": 0.50},
    "gpt-4.1-mini":                 {"input": 0.40,  "output": 1.60,  "cache_read": 0.10},
    "gpt-4.1-nano":                 {"input": 0.10,  "output": 0.40,  "cache_read": 0.025},
    "o3-mini":                      {"input": 1.10,  "output": 4.40,  "cache_read": 0.55},
    "openai/text-embedding-3-small": {"input": 0.02, "output": 0.0,   "cache_read": 0.0},
    # ── DeepSeek ─────────────────────────────────────────────────────────
    "deepseek/deepseek-v3.2":       {"input": 0.26,  "output": 0.40,  "cache_read": 0.026},
    "deepseek/deepseek-r1":         {"input": 0.70,  "output": 2.50,  "cache_read": 0.07},
    # ── Google ───────────────────────────────────────────────────────────
    "google/gemini-2.5-pro":        {"input": 1.25,  "output": 10.00, "cache_read": 0.125},
    "google/gemini-2.5-flash":      {"input": 0.15,  "output": 0.60,  "cache_read": 0.0375},
    "google/gemini-2.5-flash-lite": {"input": 0.10,  "output": 0.40,  "cache_read": 0.01},
    # ── Mistral ──────────────────────────────────────────────────────────
    "mistral/mistral-large":        {"input": 2.00,  "output": 6.00,  "cache_read": 0.20},
    "mistral/mistral-small":        {"input": 0.10,  "output": 0.30,  "cache_read": 0.01},
    # ── Meta (via OpenRouter/Together) ───────────────────────────────────
    "meta-llama/llama-4-maverick":  {"input": 0.20,  "output": 0.60,  "cache_read": 0.02},
    "meta-llama/llama-4-scout":     {"input": 0.15,  "output": 0.40,  "cache_read": 0.015},
    # ── Local (free) ─────────────────────────────────────────────────────
    "ollama/gemma3:12b":            {"input": 0.0,   "output": 0.0,   "cache_read": 0.0},
    "ollama/gemma3:1b":             {"input": 0.0,   "output": 0.0,   "cache_read": 0.0},
    "ollama/nomic-embed-text":      {"input": 0.0,   "output": 0.0,   "cache_read": 0.0},
}


def compute_cost(model: str, input_tokens: int, output_tokens: int,
                 cache_read_tokens: int = 0) -> float:
    """Compute USD cost for a span given model and token counts."""
    pricing = PRICING_TABLE.get(model)
    if not pricing:
        # Try partial match (e.g. "anthropic/claude-sonnet-4-6" → "claude-sonnet-4-6")
        for key, val in PRICING_TABLE.items():
            if key in model or model.endswith(key):
                pricing = val
                break
    if not pricing:
        return 0.0

    cost = (
        (input_tokens * pricing["input"] / 1_000_000)
        + (output_tokens * pricing["output"] / 1_000_000)
        + (cache_read_tokens * pricing["cache_read"] / 1_000_000)
    )
    return round(cost, 8)
