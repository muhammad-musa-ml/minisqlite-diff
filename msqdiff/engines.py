"""The two engines under comparison.

`Oracle` is real SQLite through Python's sqlite3 module. `Runner` is
cursor/minisqlite behind msq-runner (see runner/src/main.rs), started either from
a native binary (MSQ_RUNNER=path) or from the Docker image built by the Dockerfile.
"""

from __future__ import annotations

import json
import os
import queue
import re
import shutil
import sqlite3
import subprocess
import threading

from .model import Result, from_json, from_python


class Oracle:
    """Real SQLite, one in-memory database per case."""

    def __init__(self, path: str = ":memory:") -> None:
        self.path = path
        self.reset()

    def close(self) -> None:
        con = getattr(self, "con", None)
        if con is not None:
            con.close()
            self.con = None

    def reset(self) -> None:
        self.close()
        self.con = sqlite3.connect(self.path, isolation_level=None, check_same_thread=False)
        # minisqlite's Text holds a Rust String, so bytes that are not UTF-8 are out of
        # scope; decode leniently instead of letting Python raise on a result.
        self.con.text_factory = lambda b: b.decode("utf-8", "replace")

    @staticmethod
    def version() -> str:
        return sqlite3.sqlite_version

    def run(self, op: str, sql: str) -> Result:
        try:
            cur = self.con.cursor()
            cur.execute(sql)
            if op == "Q":
                cols = [d[0] for d in cur.description] if cur.description else []
                rows = [[from_python(c) for c in r] for r in cur.fetchall()]
                return Result("rows", cols=cols, rows=rows)
            cur.fetchall()
            return Result("ok")
        except sqlite3.Error as e:
            code = getattr(e, "sqlite_errorcode", 0) or 0
            return Result("err", message=str(e), code=code & 0xFF)
        except (ValueError, OverflowError) as e:  # e.g. a value Python cannot hold
            return Result("err", message=f"python: {e}", code=-2)


class Runner:
    """minisqlite, driven over a pipe."""

    def __init__(self, timeout: float = 20.0) -> None:
        self.timeout = timeout
        self.proc: subprocess.Popen | None = None
        self.lines: queue.Queue[str | None] = queue.Queue()
        self._start()

    @staticmethod
    def command() -> list[str]:
        native = os.environ.get("MSQ_RUNNER")
        if native:
            return [native]
        if not shutil.which("docker"):
            raise RuntimeError("set MSQ_RUNNER to a built msq-runner binary, or install Docker")
        image = os.environ.get("MSQ_IMAGE", "msq-runner:local")
        return ["docker", "run", "--rm", "-i", image]

    def _start(self) -> None:
        self.lines = queue.Queue()
        self.proc = subprocess.Popen(
            self.command(),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
            bufsize=1,
        )
        q = self.lines
        out = self.proc.stdout

        def pump() -> None:
            try:
                for line in out:
                    q.put(line)
            finally:
                q.put(None)

        threading.Thread(target=pump, daemon=True).start()

    def close(self) -> None:
        if self.proc and self.proc.poll() is None:
            self.proc.kill()
        self.proc = None

    def _send(self, line: str) -> dict | None:
        """Send one command; return the decoded reply, or None on hang or death."""
        assert self.proc and self.proc.stdin
        try:
            self.proc.stdin.write(line + "\n")
            self.proc.stdin.flush()
        except (BrokenPipeError, OSError):
            return None
        try:
            reply = self.lines.get(timeout=self.timeout)
        except queue.Empty:
            return None
        if reply is None:
            return None
        return json.loads(reply)

    def reset(self) -> None:
        if self._send("RESET") is None:
            self.close()
            self._start()

    def run(self, op: str, sql: str) -> Result:
        reply = self._send(f"{op} {sql.encode('utf-8').hex()}")
        if reply is None:
            self.close()
            self._start()
            return Result("hang", message=f"no reply within {self.timeout}s (or process died); restarted")
        if "panic" in reply:
            return Result("panic", message=reply["panic"])
        if "err" in reply:
            # minisqlite's Display adds a kind prefix; SQLite's messages carry none.
            msg = re.sub(r"^(sql|constraint|format|io) error: ", "", reply["err"])
            return Result("err", message=msg, code=reply.get("code", 0))
        if "cols" in reply:
            return Result("rows", cols=reply["cols"], rows=[[from_json(c) for c in r] for r in reply["rows"]])
        return Result("ok")
