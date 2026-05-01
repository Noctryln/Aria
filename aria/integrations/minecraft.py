import json
import os
import subprocess
import threading
import time
from typing import Any


class AriaMinecraftMixin:
    def _mc_init_state(self):
        if not hasattr(self, "_mc_proc"):
            self._mc_proc = None
            self._mc_lock = threading.Lock()
            self._mc_seq = 0
            self._mc_pending: dict[int, dict[str, Any]] = {}
            self._mc_events: list[dict[str, Any]] = []
            self._mc_last_stderr = ""

    def _mc_start_bridge(self):
        self._mc_init_state()
        with self._mc_lock:
            if self._mc_proc and self._mc_proc.poll() is None:
                return
            script = os.path.join(os.path.dirname(__file__), "mc", "index.js")
            script = os.path.abspath(script)
            self._mc_proc = subprocess.Popen(
                ["node", script],
                cwd=os.path.dirname(script),
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
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
                
                # Real-time event callback for UI/Agent to react immediately
                if hasattr(self, "_on_mc_event"):
                    try:
                        self._on_mc_event(payload)
                    except Exception:
                        pass

    def _mc_read_stderr(self):
        while self._mc_proc and self._mc_proc.stderr:
            line = self._mc_proc.stderr.readline()
            if not line:
                break
            self._mc_last_stderr = (self._mc_last_stderr + line)[-4000:]

    def _mc_call(self, action: str, data: dict | None = None, timeout: float = 60.0):
        self._mc_start_bridge()
        
        # Adjust timeout for specific actions
        if action == 'act':
            timeout = 1800.0 # 30 minutes for long actions
        elif action == 'observe':
            timeout = 120.0
            
        # Auto-restart if process died
        if not self._mc_proc or self._mc_proc.poll() is not None:
            self._mc_start_bridge()
            time.sleep(0.5)
            
        if not self._mc_proc or not self._mc_proc.stdin:
            return {"ok": False, "error": "bridge_not_running"}
            
        if self._mc_proc.poll() is not None:
             # Final attempt to restart
            self._mc_start_bridge()
            if self._mc_proc.poll() is not None:
                return {
                    "ok": False,
                    "error": "bridge_process_exited",
                    "stderr_tail": self._mc_last_stderr[-1200:],
                }
        
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
            if self._mc_proc and self._mc_proc.poll() is not None:
                return {
                    "ok": False,
                    "error": "timeout_bridge_exited",
                    "stderr_tail": self._mc_last_stderr[-1200:],
                }
            return {"ok": False, "error": "timeout"}
        resp = self._mc_pending.pop(req_id, {}).get("resp") or {}
        return resp.get("data", {"ok": False, "error": "no_data"})