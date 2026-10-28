"""Peer channel: per-workspace `send-msg` / `recv-msg` scripts the agent runs from bash.

- ``QueueChannel``: one flock'd JSON-lines file, read through a per-agent cursor.
- ``RedisChannel``: per-agent Redis list inboxes (``REDIS_URL``, default
  ``redis://localhost:6379/0``); recv drains the caller's inbox.

``recv-msg --wait [N]`` blocks up to N seconds (default 90) for a peer message
and prints ``no message yet`` on timeout.
"""

from __future__ import annotations

import os
import stat
import uuid
from pathlib import Path
from typing import Protocol, Sequence

from .workspace import Workspace

SEND = "send-msg"
RECV = "recv-msg"

_SEND_SCRIPT = r"""#!/usr/bin/env python3
import fcntl, json, time
QUEUE = "__QUEUE__"; AGENT = "__AGENT__"
import sys
msg = " ".join(sys.argv[1:])
with open(QUEUE, "a") as f:
    fcntl.flock(f, fcntl.LOCK_EX)
    f.write(json.dumps({"from": AGENT, "ts": time.time(), "content": msg}) + "\n")
    fcntl.flock(f, fcntl.LOCK_UN)
"""

_RECV_SCRIPT = r"""#!/usr/bin/env python3
import json, os, sys, time
QUEUE = "__QUEUE__"; AGENT = "__AGENT__"; CURSOR = "__CURSOR__"
WAIT_DEFAULT = 90   # seconds `--wait` blocks for before giving up
POLL = 3            # seconds between polls while waiting

def _wait_seconds(argv):
    # `--wait` (default budget) or `--wait N`; anything else returns at once.
    if "--wait" not in argv:
        return 0
    i = argv.index("--wait")
    if i + 1 < len(argv) and argv[i + 1].isdigit():
        return int(argv[i + 1])
    return WAIT_DEFAULT

try:
    seen = int(open(CURSOR).read() or "0")
except FileNotFoundError:
    seen = 0
deadline = time.time() + _wait_seconds(sys.argv[1:])
printed = False
while True:
    lines = open(QUEUE).read().splitlines() if os.path.exists(QUEUE) else []
    for entry in lines[seen:]:
        try:
            m = json.loads(entry)
        except ValueError:
            break   # a write still in progress; re-read it next time
        seen += 1
        if m["from"] != AGENT:
            print(f"[from {m['from']}] {m['content']}")
            printed = True
    open(CURSOR, "w").write(str(seen))
    if printed or time.time() >= deadline:
        break
    time.sleep(POLL)
if not printed and "--wait" in sys.argv[1:]:
    print("no message yet")
"""

# Same CLI as the queue scripts; need the `redis` package where the agent runs.
_REDIS_SEND_SCRIPT = r"""#!/usr/bin/env python3
import fcntl, json, sys, time
try:
    import redis
except ImportError:
    sys.stderr.write("redis package required for send-msg (pip install redis)\n")
    sys.exit(1)
URL = "__REDIS_URL__"; PREFIX = "__PREFIX__"; AGENT = "__AGENT__"
PEERS = [p for p in "__PEERS__".split(",") if p]
LOG = "__LOG__"
msg = " ".join(sys.argv[1:])
if not msg.strip():
    sys.stderr.write("usage: send-msg <message>\n")
    sys.exit(2)
client = redis.from_url(URL)
entry = {"from": AGENT, "ts": time.time(), "content": msg}
raw = json.dumps(entry)
for peer in PEERS:
    client.rpush(f"{PREFIX}{peer}:inbox", raw)
if LOG:
    # The message is already delivered; a logging problem must not surface to
    # the agent as a failed send.
    try:
        with open(LOG, "a") as f:
            fcntl.flock(f, fcntl.LOCK_EX)
            f.write(raw + "\n")
            fcntl.flock(f, fcntl.LOCK_UN)
    except OSError as e:
        sys.stderr.write(f"send-msg: delivered, but could not append to log: {e}\n")
"""

_REDIS_RECV_SCRIPT = r"""#!/usr/bin/env python3
import json, sys
try:
    import redis
except ImportError:
    sys.stderr.write("redis package required for recv-msg (pip install redis)\n")
    sys.exit(1)
URL = "__REDIS_URL__"; PREFIX = "__PREFIX__"; AGENT = "__AGENT__"
WAIT_DEFAULT = 90   # seconds `--wait` blocks for before giving up

def _wait_seconds(argv):
    # `--wait` (default budget) or `--wait N`; anything else returns at once.
    if "--wait" not in argv:
        return 0
    i = argv.index("--wait")
    if i + 1 < len(argv) and argv[i + 1].isdigit():
        return int(argv[i + 1])
    return WAIT_DEFAULT

def _show(raw):
    if isinstance(raw, bytes):
        raw = raw.decode()
    try:
        m = json.loads(raw)
        print(f"[from {m['from']}] {m['content']}")
    except (json.JSONDecodeError, KeyError, TypeError):
        print(raw)

def _drain(client, key):
    n = 0
    while True:
        raw = client.lpop(key)
        if raw is None:
            return n
        _show(raw)
        n += 1

client = redis.from_url(URL)
key = f"{PREFIX}{AGENT}:inbox"
got = _drain(client, key)
wait = _wait_seconds(sys.argv[1:])
if got == 0 and wait > 0:
    hit = client.blpop([key], timeout=wait)   # block until one arrives
    if hit is None:
        print("no message yet")
    else:
        _show(hit[1])
        _drain(client, key)                   # and anything right behind it
"""


class Channel(Protocol):
    def prepare(self, run_dir: Path) -> None: ...
    def attach(self, workspace: Workspace, agent: str) -> None: ...
    def read_log(self) -> str: ...


class NullChannel:
    def prepare(self, run_dir: Path) -> None:
        return None

    def attach(self, workspace: Workspace, agent: str) -> None:
        return None

    def read_log(self) -> str:
        return ""


class QueueChannel:
    """One shared JSON-lines queue; each workspace gets scripts bound to its agent."""

    def __init__(self) -> None:
        self._queue: Path | None = None
        self._cursor_dir: Path | None = None

    def prepare(self, run_dir: Path) -> None:
        # The scripts embed these paths and run with cwd = the agent workspace,
        # so they must be absolute regardless of what the caller passed.
        run_dir = run_dir.resolve()
        run_dir.mkdir(parents=True, exist_ok=True)
        self._queue = run_dir / "queue.jsonl"
        self._queue.write_text("", encoding="utf-8")
        self._cursor_dir = run_dir / "cursors"
        self._cursor_dir.mkdir(exist_ok=True)

    def attach(self, workspace: Workspace, agent: str) -> None:
        assert self._queue is not None and self._cursor_dir is not None
        cursor = self._cursor_dir / f"{agent}.cursor"
        subs = {
            "__QUEUE__": str(self._queue),
            "__AGENT__": agent,
            "__CURSOR__": str(cursor),
        }
        for name, tmpl in ((SEND, _SEND_SCRIPT), (RECV, _RECV_SCRIPT)):
            text = tmpl
            for k, v in subs.items():
                text = text.replace(k, v)
            script = workspace.path / name
            script.write_text(text, encoding="utf-8")
            script.chmod(script.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP)
        workspace.gitignore(SEND, RECV, ".local/")

    def read_log(self) -> str:
        return self._queue.read_text(encoding="utf-8") if self._queue else ""


class RedisChannel:
    """Per-agent Redis list inboxes (``<prefix><agent>:inbox``); send RPUSHes, recv LPOPs.

    Each send is also appended to ``comm.jsonl`` in the run dir for ``read_log``,
    after delivery, so a crash in between can drop a delivered message from the log.
    """

    def __init__(
        self,
        agents: Sequence[str] = ("A", "B"),
        redis_url: str | None = None,
    ) -> None:
        self._agents = tuple(agents)
        self._redis_url = redis_url or os.environ.get(
            "REDIS_URL", "redis://localhost:6379/0"
        )
        self._prefix: str | None = None
        self._log: Path | None = None

    def prepare(self, run_dir: Path) -> None:
        try:
            import redis
        except ImportError as e:
            raise RuntimeError(
                "RedisChannel requires the redis package (pip install redis)"
            ) from e
        # Absolute: send-msg appends to the log from the agent's workspace cwd.
        run_dir = run_dir.resolve()
        run_dir = run_dir.resolve()
        run_dir.mkdir(parents=True, exist_ok=True)
        # run_dir is <hm>/<label>/<family>/_work/<seed>/<scenario>; the key prefix
        # takes the harness-model, seed and scenario so runs of different models
        # never share inboxes.
        work_root = run_dir.parent.parent.name or uuid.uuid4().hex[:8]
        hm = run_dir.parents[4].name if len(run_dir.parents) > 4 else ""
        self._prefix = f"run02:{hm}:{work_root}:{run_dir.parent.name}:{run_dir.name}:"
        self._log = run_dir / "comm.jsonl"
        self._log.write_text("", encoding="utf-8")
        client = redis.from_url(self._redis_url)
        client.ping()
        for agent in self._agents:
            client.delete(f"{self._prefix}{agent}:inbox")

    def attach(self, workspace: Workspace, agent: str) -> None:
        assert self._prefix is not None and self._log is not None
        peers = ",".join(a for a in self._agents if a != agent)
        subs = {
            "__REDIS_URL__": self._redis_url,
            "__PREFIX__": self._prefix,
            "__AGENT__": agent,
            "__PEERS__": peers,
            "__LOG__": str(self._log),
        }
        for name, tmpl in ((SEND, _REDIS_SEND_SCRIPT), (RECV, _REDIS_RECV_SCRIPT)):
            text = tmpl
            for k, v in subs.items():
                text = text.replace(k, v)
            script = workspace.path / name
            script.write_text(text, encoding="utf-8")
            script.chmod(script.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP)
        workspace.gitignore(SEND, RECV, ".local/")

    def read_log(self) -> str:
        return self._log.read_text(encoding="utf-8") if self._log else ""
