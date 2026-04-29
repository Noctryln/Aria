import json
import os
import subprocess
import threading
import time
from typing import Any

from aria.core.paths import LAUNCH_DIR


class AriaMinecraftMixin:
    def _mc_init_state(self):
        if not hasattr(self, "_mc_proc"):
            self._mc_proc = None
            self._mc_lock = threading.Lock()
            self._mc_seq = 0
            self._mc_pending: dict[int, dict[str, Any]] = {}
            self._mc_events: list[dict[str, Any]] = []

    def _mc_start_bridge(self):
        self._mc_init_state()
        if self._mc_proc and self._mc_proc.poll() is None:
            return
        script = os.path.join(LAUNCH_DIR, "aria", "integrations", "minecraft_bridge.js")
        self._mc_proc = subprocess.Popen(
            ["node", script],
            cwd=LAUNCH_DIR,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )
        threading.Thread(target=self._mc_read_stdout, daemon=True).start()
        threading.Thread(target=self._mc_read_stderr, daemon=True).start()

    def _mc_read_stdout(self):
        while self._mc_proc and self._mc_proc.stdout:
            line = self._mc_proc.stdout.readline()
            if not line:
                break
            try:
                payload = json.loads(line.strip())
            except Exception:
                continue
            typ = payload.get("type")
            if typ == "response":
                rid = payload.get("id")
                pending = self._mc_pending.get(rid)
                if pending is not None:
                    pending["resp"] = payload
                    pending["event"].set()
            elif typ == "event":
                self._mc_events.append(payload)
                if len(self._mc_events) > 500:
                    self._mc_events = self._mc_events[-500:]

    def _mc_read_stderr(self):
        while self._mc_proc and self._mc_proc.stderr:
            line = self._mc_proc.stderr.readline()
            if not line:
                break

    def _mc_call(self, action: str, data: dict | None = None, timeout: float = 8.0):
        self._mc_start_bridge()
        if not self._mc_proc or not self._mc_proc.stdin:
            return {"ok": False, "error": "bridge_not_running"}
        self._mc_seq += 1
        req_id = self._mc_seq
        evt = threading.Event()
        self._mc_pending[req_id] = {"event": evt, "resp": None}
        req = {"id": req_id, "action": action, "data": data or {}}
        with self._mc_lock:
            self._mc_proc.stdin.write(json.dumps(req, ensure_ascii=False) + "\n")
            self._mc_proc.stdin.flush()
        if not evt.wait(timeout):
            self._mc_pending.pop(req_id, None)
            return {"ok": False, "error": "timeout"}
        resp = self._mc_pending.pop(req_id, {}).get("resp") or {}
        return resp.get("data", {"ok": False, "error": "no_data"})
