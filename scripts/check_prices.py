"""
Compare LumenAI's built-in price table with LiteLLM's community price list.

    python scripts/check_prices.py                 # downloads the current list
    python scripts/check_prices.py --file prices.json

Every price in PRICING_TABLE was checked against the provider's own pricing
page; LiteLLM is an independent, frequently updated second source. A difference
means one of the two is stale: re-check the provider's page before changing the
table. Exits 1 when any price differs, so it can run before a release.
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "packages" / "lumen-ai-core" / "src"))

from lumen_ai.providers import LITELLM_PRICES_URL  # noqa: E402
from lumen_ai.schema.semconv import PRICING_TABLE  # noqa: E402

FIELDS = {
    "input": "input_cost_per_token",
    "output": "output_cost_per_token",
    "cache_read": "cache_read_input_token_cost",
    "cache_write": "cache_creation_input_token_cost",
}
# Our provider prefixes that LiteLLM spells differently.
PREFIX_ALIASES = {"google/": "gemini/"}

# Differences already checked against the provider's own pages, where LiteLLM's
# list is the stale side. Keyed by (our key, field); the value says why.
ACKNOWLEDGED = {
    (key, field): "Mistral's pricing page and model card list $1.36 / $0.14 / $4.18 (2026-10-28)"
    for key in ("mistral-large-4",)
    for field in ("input", "output", "cache_read")
}


def candidates(key: str) -> list[str]:
    """LiteLLM keys that may hold the same model as one of our keys.

    A family key such as ``mistral-small`` means the current model, so
    ``mistral/mistral-small-latest`` is tried before an older exact entry.
    """
    names = [key + "-latest", key]
    for ours, theirs in PREFIX_ALIASES.items():
        if key.startswith(ours):
            names.append(theirs + key[len(ours):])
    bare = key.rsplit("/", 1)[-1]
    for prefix in ("", "anthropic/", "openai/", "gemini/", "deepseek/", "mistral/"):
        names += [prefix + bare + "-latest", prefix + bare]
    return list(dict.fromkeys(names))


def compare(table: dict, litellm: dict) -> tuple[list[tuple], list[str]]:
    """(differences, keys with no LiteLLM counterpart). Rates in USD per 1M tokens."""
    differences: list[tuple] = []
    missing: list[str] = []
    for key, ours in sorted(table.items()):
        if all(value == 0 for value in ours.values()):
            continue  # local models (Ollama): free by definition
        match = next((litellm[name] for name in candidates(key) if isinstance(litellm.get(name), dict)), None)
        if match is None:
            missing.append(key)
            continue
        for field, their_field in FIELDS.items():
            theirs = match.get(their_field)
            if field not in ours or not isinstance(theirs, (int, float)) or isinstance(theirs, bool):
                continue
            theirs_per_million = round(float(theirs) * 1_000_000, 6)
            if field == "cache_read" and ours["cache_read"] == ours["input"]:
                continue  # we repeat the input rate when a model has no cache discount
            if abs(theirs_per_million - ours[field]) > 1e-6 * max(1.0, ours[field]):
                differences.append((key, field, ours[field], theirs_per_million))
    return differences, missing


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--file", help="a local copy of LiteLLM's model_prices_and_context_window.json")
    parser.add_argument("--url", default=LITELLM_PRICES_URL)
    args = parser.parse_args(argv)

    if args.file:
        litellm = json.loads(Path(args.file).read_text(encoding="utf-8"))
    else:
        with urllib.request.urlopen(args.url, timeout=60) as response:
            litellm = json.loads(response.read().decode("utf-8"))

    differences, missing = compare(PRICING_TABLE, litellm)
    acknowledged = [d for d in differences if (d[0], d[1]) in ACKNOWLEDGED]
    differences = [d for d in differences if (d[0], d[1]) not in ACKNOWLEDGED]
    priced = sum(1 for prices in PRICING_TABLE.values() if any(prices.values()))
    print(f"{priced} paid models in PRICING_TABLE, {len(litellm)} entries in LiteLLM's list.")
    if missing:
        print(f"\nNot in LiteLLM's list ({len(missing)}), check the provider's page by hand:")
        for key in missing:
            print(f"  {key}")
    if acknowledged:
        print(f"\nKnown differences, LumenAI kept ({len(acknowledged)}):")
        for key, field, ours, theirs in acknowledged:
            print(f"  {key} {field}: {ours:g} vs LiteLLM {theirs:g}. {ACKNOWLEDGED[(key, field)]}")
    if differences:
        print(f"\nPrices that differ ({len(differences)}), USD per 1M tokens:")
        print(f"  {'model':34} {'field':12} {'LumenAI':>10} {'LiteLLM':>10}")
        for key, field, ours, theirs in differences:
            print(f"  {key:34} {field:12} {ours:>10g} {theirs:>10g}")
        return 1
    print("\nNo price differs from LiteLLM's list.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
