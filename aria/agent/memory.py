import json
import os
import time

from aria.core.paths import PROJECT_ROOT

SESSION_DIR = os.path.join(PROJECT_ROOT, "session")
SESSION_FILE = os.path.join(SESSION_DIR, "session.json")

def load_sessions() -> list[dict]:
    if not os.path.exists(SESSION_FILE):
        return []
    try:
        with open(SESSION_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []

def save_sessions(sessions: list[dict]) -> None:
    os.makedirs(SESSION_DIR, exist_ok=True)
    with open(SESSION_FILE, "w", encoding="utf-8") as f:
        json.dump(sessions, f, indent=2, ensure_ascii=False)

def get_session(session_id: str) -> dict | None:
    sessions = load_sessions()
    for s in sessions:
        if s["id"] == session_id:
            return s
    for s in sessions:
        if s["id"].endswith(session_id):
            return s
    return None

def get_sessions_for_dir(dir_path: str) -> list[dict]:
    sessions = load_sessions()
    return sorted(
        [s for s in sessions if s["dir"] == dir_path],
        key=lambda x: x["updated_at"],
        reverse=True
    )

def save_current_session(session_id: str, dir_path: str, history: list[dict], msg_count: int, last_input: str) -> None:
    sessions = load_sessions()
    now = time.time()
    
    for s in sessions:
        if s["id"] == session_id:
            s["updated_at"] = now
            s["history"] = history
            s["msg_count"] = msg_count
            if last_input:
                s["last_input"] = last_input
            save_sessions(sessions)
            return

    sessions.append({
        "id": session_id,
        "dir": dir_path,
        "updated_at": now,
        "msg_count": msg_count,
        "last_input": last_input,
        "history": history
    })
    save_sessions(sessions)
