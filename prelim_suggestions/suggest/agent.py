"""Exploration agent: a bounded native tool-calling loop over one repo checkout.

The model gets the read-only repo tools plus a `finish` tool whose argument is
the assessment. From `force_finish_at` on, tool_choice is pinned to `finish` so
every run ends with a verdict. `reasoning_content` is never fed back.
"""

from __future__ import annotations

import collections
import json
from pathlib import Path

from swebench_pro.tools import RepoTools

from . import schema
from .llm import Client

# Tool schemas in OpenAI function-calling shape.
_REPO_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "list_dir",
            "description": "List files and folders at a path in the repo (noisy dirs like .git/node_modules are skipped).",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "repo-relative dir path; default '.'",
                    }
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Read up to max_lines lines of a file starting at start_line.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "repo-relative file path",
                    },
                    "start_line": {
                        "type": "integer",
                        "description": "1-based; default 1",
                    },
                    "max_lines": {
                        "type": "integer",
                        "description": "default 200, hard cap 400",
                    },
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "grep",
            "description": "Regex search across the repo (ripgrep if available).",
            "parameters": {
                "type": "object",
                "properties": {
                    "pattern": {"type": "string", "description": "regex"},
                    "path": {
                        "type": "string",
                        "description": "subtree to search; default '.'",
                    },
                    "max_matches": {
                        "type": "integer",
                        "description": "default 50, cap 200",
                    },
                },
                "required": ["pattern"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "find_files",
            "description": "Find files whose name matches a glob (e.g. '*.go').",
            "parameters": {
                "type": "object",
                "properties": {
                    "name_glob": {"type": "string", "description": "filename glob"},
                    "max_results": {
                        "type": "integer",
                        "description": "default 100, cap 500",
                    },
                },
                "required": ["name_glob"],
            },
        },
    },
]

_FINISH_TOOL = {
    "type": "function",
    "function": {
        "name": "finish",
        "description": (
            "Submit the final assessment and end exploration. Pass the "
            "`assessment` object exactly as specified in the system prompt "
            "(contradictory, complementary, notes)."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "assessment": {
                    "type": "object",
                    "description": "The assessment object: {contradictory:{...}, complementary:{...}, notes:str}. See the system prompt for the full field list.",
                    "properties": {
                        "contradictory": {"type": "object"},
                        "complementary": {"type": "object"},
                        "notes": {"type": "string"},
                    },
                }
            },
            "required": ["assessment"],
        },
    },
}

TOOLS = _REPO_TOOLS + [_FINISH_TOOL]
_FORCE_FINISH = {"type": "function", "function": {"name": "finish"}}


def load_prompts(prompts_dir: Path) -> tuple[str, str]:
    system = (prompts_dir / "explore_system.md").read_text(encoding="utf-8")
    template = (prompts_dir / "task_template.md").read_text(encoding="utf-8")
    return system, template


def _clip(s, n: int) -> str:
    s = "" if s is None else str(s)
    return s if len(s) <= n else s[:n] + f"\n... [truncated {len(s) - n} chars]"


def build_task_message(row: dict, template: str) -> str:
    return template.format(
        repo=row.get("repo", ""),
        repo_language=row.get("repo_language", ""),
        instance_id=row.get("instance_id", ""),
        base_commit=row.get("base_commit", ""),
        problem_statement=_clip(row.get("problem_statement"), 6000),
        requirements=_clip(row.get("requirements"), 6000),
        interface=_clip(row.get("interface"), 3000),
        fail_to_pass=_clip(row.get("fail_to_pass"), 2000),
        patch=_clip(row.get("patch"), 14000),
        test_patch=_clip(row.get("test_patch"), 8000),
    )


def _parse_args(raw) -> dict:
    """Parse tool-call arguments (normally a JSON string); return {} if malformed."""
    if isinstance(raw, dict):
        return raw
    if not raw:
        return {}
    try:
        obj = json.loads(raw)
        return obj if isinstance(obj, dict) else {}
    except (json.JSONDecodeError, TypeError):
        return {}


def run_agent(
    row: dict,
    checkout: Path,
    client: Client,
    system: str,
    template: str,
    max_steps: int = 40,
    force_finish_at: int = 30,
    verbose: bool = False,
) -> dict:
    repo_tools = RepoTools(checkout)
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": build_task_message(row, template)},
    ]
    transcript: list[dict] = []
    assessment = None
    status = "incomplete"
    steps_used = 0
    seen: collections.Counter = collections.Counter()

    for step in range(1, max_steps + 1):
        steps_used = step
        forced = step >= min(force_finish_at, max_steps)
        if forced:
            messages.append(
                {
                    "role": "user",
                    "content": "You have explored enough. Call the `finish` tool now with your "
                    "assessment. If unsure, set viable=false with low confidence and "
                    "explain why in notes — an honest low-confidence finish is required.",
                }
            )
        msg = client.chat(
            messages, tools=TOOLS, tool_choice=_FORCE_FINISH if forced else "auto"
        )
        calls = msg.get("tool_calls") or []
        asst: dict = {"role": "assistant", "content": msg.get("content") or ""}
        if calls:
            asst["tool_calls"] = calls
        messages.append(asst)

        if not calls:
            transcript.append({"step": step, "action": None})
            messages.append(
                {
                    "role": "user",
                    "content": "Respond by calling exactly one tool (list_dir / read_file / grep / "
                    "find_files), or `finish` when decided. Do not answer in prose.",
                }
            )
            continue

        finished = False
        for call in calls:
            cid = call.get("id")
            fn = call.get("function", {}) or {}
            name = fn.get("name", "")
            targs = _parse_args(fn.get("arguments"))

            if name == "finish":
                a = targs.get("assessment")
                if not isinstance(a, dict):
                    a = (
                        targs
                        if ("contradictory" in targs or "complementary" in targs)
                        else {}
                    )
                assessment = schema.normalize(a)
                status = "ok"
                transcript.append({"step": step, "action": {"tool": "finish"}})
                messages.append(
                    {"role": "tool", "tool_call_id": cid, "name": name, "content": "ok"}
                )
                finished = True
                break

            obs = repo_tools.dispatch(name, targs)
            if verbose:
                print(f"    step {step}: {name}({targs}) -> {len(obs)} chars")
            transcript.append(
                {
                    "step": step,
                    "action": {"tool": name, "args": targs},
                    "obs_len": len(obs),
                }
            )
            sig = (name, json.dumps(targs, sort_keys=True, default=str))
            seen[sig] += 1
            footer = ""
            if seen[sig] >= 2:
                footer = (
                    "\n[NOTE: you already ran this exact call; its result will "
                    "not change. Do something different, or call finish.]"
                )
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": cid,
                    "name": name,
                    "content": obs + footer,
                }
            )
        if finished:
            break

    if assessment is None:
        assessment = schema.normalize({})
        status = "incomplete"

    return {
        "status": status,
        "steps_used": steps_used,
        "assessment": assessment,
        "transcript": transcript,
    }
