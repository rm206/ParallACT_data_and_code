"""CooperBench merge resolver (a LoRA on Qwen2.5-Coder-0.5B-Instruct, via peft).

Resolves one conflict hunk at a time from the marked region plus a few lines of
context, splicing each resolution back into the file.
"""

from __future__ import annotations

import re
import threading

BASE_MODEL = "Qwen/Qwen2.5-Coder-0.5B-Instruct"
ADAPTER = "CooperBench/Qwen2.5-Coder-0.5B-Merge-Resolver"
CONTEXT_LINES = 5
MAX_NEW_TOKENS = 1024
_PREAMBLE = (
    "You are an expert at resolving code merge conflicts.\n\n"
    "Given a merge conflict, resolve it by merging BOTH features whenever possible.\n"
    "Preserve all functionality from both branches.\n\n"
    "Output ONLY the resolved code without conflict markers.\n\n"
)

_model = None
_tok = None
# grade.py grades bundles on threads; concurrent loading or generation corrupts
# the shared model.
_lock = threading.Lock()

_CONFLICT = re.compile(r"^<{7}.*$", re.M)


def _load():
    global _model, _tok
    if _model is not None:
        return
    with _lock:
        if _model is None:
            _load_locked()


def _load_locked():
    global _model, _tok
    import torch
    from peft import PeftModel
    from transformers import AutoModelForCausalLM, AutoTokenizer

    base = AutoModelForCausalLM.from_pretrained(BASE_MODEL, dtype=torch.float32)
    model = PeftModel.from_pretrained(base, ADAPTER)
    model.eval()
    tok = AutoTokenizer.from_pretrained(BASE_MODEL)
    if tok.pad_token_id is None:
        tok.pad_token = tok.eos_token
    _tok, _model = tok, model  # publish only once fully built


def _resolve_snippet(snippet: str) -> str:
    _load()
    import torch

    messages = [{"role": "user", "content": _PREAMBLE + snippet}]
    enc = _tok.apply_chat_template(
        messages, add_generation_prompt=True, return_tensors="pt", return_dict=True
    )
    inputs = enc["input_ids"]
    attn = enc.get("attention_mask")
    if attn is None:
        attn = torch.ones_like(inputs)
    with _lock, torch.no_grad():
        out = _model.generate(
            input_ids=inputs,
            attention_mask=attn,
            max_new_tokens=MAX_NEW_TOKENS,
            do_sample=False,
            pad_token_id=_tok.eos_token_id,
        )
    return _tok.decode(out[0][inputs.shape[1] :], skip_special_tokens=True)


def _find_conflict(lines: list[str]) -> tuple[int, int] | None:
    """Return (start_idx, end_idx_inclusive) of the first <<<<<<< .. >>>>>>> block."""
    start = next((i for i, l in enumerate(lines) if l.startswith("<<<<<<<")), None)
    if start is None:
        return None
    end = next(
        (i for i in range(start + 1, len(lines)) if lines[i].startswith(">>>>>>>")),
        None,
    )
    return None if end is None else (start, end)


def resolve_file(text: str) -> str:
    """Resolve every conflict in a file's text, re-scanning after each splice."""
    guard = 0
    while "<<<<<<<" in text:
        guard += 1
        if guard > 200:
            raise RuntimeError("too many conflicts / non-converging resolution")
        lines = text.split("\n")
        span = _find_conflict(lines)
        if span is None:
            break
        cstart, cend = span
        rstart = max(0, cstart - CONTEXT_LINES)
        rend = min(len(lines), cend + 1 + CONTEXT_LINES)
        snippet = "\n".join(lines[rstart:rend])
        resolved = _resolve_snippet(snippet).rstrip("\n")
        new_lines = lines[:rstart] + resolved.split("\n") + lines[rend:]
        text = "\n".join(new_lines)
    return text


def available() -> bool:
    try:
        import peft  # noqa: F401
        import torch  # noqa: F401
        import transformers  # noqa: F401

        return True
    except ImportError:
        return False
