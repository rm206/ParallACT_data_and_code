"""Assessment schema: an independent task pair per family.

taskA is the original SWE-bench Pro task, kept whole; taskB is a separate,
independently motivated task that collides with A on the same region
(contradictory) or must agree with A on a shared interface (complementary).
The field definitions the model reads are in prompts/explore_system.md; this
module only enforces shape and fills defaults.
"""

from __future__ import annotations

from typing import Any

CONTRADICTORY_KEYS = [
    "viable",  # bool: can this become a sound contradictory seed
    "confidence",  # int 0-5 (see explore_system.md)
    "simple_explanation",  # plain language, language-agnostic
    "shared_region",  # file/function both tasks must edit
    "taskA",  # the original standalone task, kept whole
    "taskB",  # a separate, independently-motivated task
    "independence_rationale",  # why B reads as its own ticket, not a half of A
    "conflict",  # why A's and B's edits cannot both stand
    "reconciliation_sketch",  # how a single reconciled change satisfies both
    "test_strategy",  # how the combined A+B suite scores the merge
]

COMPLEMENTARY_KEYS = [
    "viable",
    "confidence",
    "simple_explanation",
    "interface_contract",  # the shared contract both tasks must agree on
    "taskA",  # one independently-motivated task (has value alone)
    "taskB",  # the other independently-motivated task
    "independence_rationale",  # each is its own ticket; A has value beyond serving B
    "integration_point",  # where the two meet
    "integration_test_sketch",  # the single test that passes only when both agree
]


def _blank_family(keys: list[str]) -> dict:
    d: dict[str, Any] = {k: "" for k in keys}
    d["viable"] = False
    d["confidence"] = 0
    return d


def _coerce_confidence(v: Any) -> int:
    try:
        n = int(round(float(v)))
    except (TypeError, ValueError):
        return 0
    return max(0, min(5, n))


def _coerce_family(raw: Any, keys: list[str]) -> dict:
    out = _blank_family(keys)
    if isinstance(raw, dict):
        for k in keys:
            if k in raw and raw[k] is not None:
                out[k] = raw[k]
    out["viable"] = bool(out.get("viable"))
    out["confidence"] = _coerce_confidence(out.get("confidence"))
    return out


def normalize(raw: Any) -> dict:
    """Coerce whatever the model returned into the canonical assessment shape."""
    raw = raw if isinstance(raw, dict) else {}
    return {
        "contradictory": _coerce_family(raw.get("contradictory"), CONTRADICTORY_KEYS),
        "complementary": _coerce_family(raw.get("complementary"), COMPLEMENTARY_KEYS),
        "notes": raw.get("notes", "") if isinstance(raw.get("notes"), str) else "",
    }
