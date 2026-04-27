import multiprocessing
import os
import re
import signal
import sys
import time

from aria.agent.agent import LLMChat
from aria.app.lifecycle import animate_spinner
from aria.core.config import load_config
from aria.core.constants import DEFAULT_SYSTEM_PROMPT
from aria.core.runtime import (
    DEFAULT_CTX,
    DEFAULT_MAX_TOKENS,
    DEFAULT_N_BATCH,
    DEFAULT_N_THREADS,
    DEFAULT_N_UBATCH,
    DEFAULT_TEMPERATURE,
    DEFAULT_TOP_P,
)
from aria.ui.app import AriaApp

def main():
    resume_session_id = None
    if len(sys.argv) > 2 and sys.argv[1] == "--resume":
        resume_session_id = sys.argv[2]
    
    try:
        if os.name == "nt":
            os.system("title Aria")
        else:
            sys.stdout.write("\33]0;Aria\a")
            sys.stdout.flush()
    except Exception:
        pass

    sys.stdout.write("\033[2J\033[1;1H")
    sys.stdout.flush()

    signal.signal(signal.SIGINT, signal.SIG_IGN)

    global app
    app = None
    while True:
        config = load_config()
        spinner_process = multiprocessing.Process(target=animate_spinner)
        spinner_process.start()
        try:
            llm = LLMChat(
                config=config, system_prompt=DEFAULT_SYSTEM_PROMPT,
                ctx=DEFAULT_CTX, max_tokens=DEFAULT_MAX_TOKENS, temperature=DEFAULT_TEMPERATURE,
                top_p=DEFAULT_TOP_P, n_threads=DEFAULT_N_THREADS,
                n_batch=DEFAULT_N_BATCH, n_ubatch=DEFAULT_N_UBATCH,
            )
        finally:
            spinner_process.terminate()
            spinner_process.join()
        sys.stdout.write("\r" + " " * 50 + "\r")
        sys.stdout.flush()
        app = AriaApp(llm, config, resume_session_id=resume_session_id)
        app.run()
        if getattr(app, "reload_requested", False):
            resume_session_id = getattr(app, "session_id", resume_session_id)
            llm.close()  # Bebaskan RAM sebelum loop berikutnya
            sys.stdout.write("\033[2J\033[1;1H")
            sys.stdout.flush()
            continue
        break
    
    if getattr(app, "skip_farewell", False):
        return
    if hasattr(app, "farewell_data") and app.farewell_data is not None:
        os.system('cls' if os.name == 'nt' else 'clear')
        from rich.live import Live; from rich.panel import Panel; from rich.console import Console, Group
        from rich.text import Text; from rich.padding import Padding; from rich import box
        from rich.style import Style
        from rich.theme import Theme

        aria_theme = Theme({
            "aria.border":   Style(color="#3d2d5a"),
            "aria.dim":      Style(color="#7b6b9a"),
            "aria.text":     Style(color="#c6bbd8"),
            "aria.gold":     Style(color="#d1a662", bold=True),
            "aria.purple":   Style(color="#c97fd4", bold=True),
            "aria.cyan":     Style(color="#71d1d1"),
            "aria.pink":     Style(color="#f472b6"),
            "aria.active":   Style(color="#71d1d1", bold=True),
            "aria.inactive": Style(color="#3d2d5a", bold=True),
        })
        console = Console(theme=aria_theme)
        data = app.farewell_data
        stats_text = data["stats_text"]
        stream = data.get("stream")
        full_text = data.get("first_chunk", "")

        def get_panel(text, is_done=False):
            clean_text = re.sub(r'<think>.*?(?:</think>\n*|$)', '', text, flags=re.DOTALL).strip()
            clean_text = re.sub(r'\*\*(.*?)\*\*', r'\1', clean_text)
            clean_text = re.sub(r'\*(.*?)\*', r'\1', clean_text)
            lines = clean_text.split('\n', 1)
            topic, farewell_body = (lines[0].strip(), lines[1].strip()) if len(lines) == 2 else ("Catatan Perjalanan", clean_text)
            topic = re.sub(r'\[/?bold\]', '', topic.replace('\u201c','').replace('\u201d','').replace('"',''), flags=re.IGNORECASE).strip()
            farewell_body = re.sub(r'\[/?bold\]', '', farewell_body, flags=re.IGNORECASE).strip()

            dot_color = "#3d2d5a" if is_done else "#71d1d1"
            dot_label = "Non-Active" if is_done else "Active"
            status_text = Text()
            status_text.append("Status : ", style="#7b6b9a")
            status_text.append("● ", style=f"bold {dot_color}")
            status_text.append(dot_label, style="#7b6b9a")

            header_panel = Panel(
                status_text,
                title=Text.assemble(("◈ ", "#d1a662"), ("Aria", "#c97fd4 bold"), (" Terminal Echo", "#c6bbd8")),
                title_align="left",
                border_style="#3d2d5a",
                box=box.ROUNDED,
            )

            topic_line = Text()
            topic_line.append(f'"{topic}"', style="#d1a662 bold")
            topic_line.append("\n")

            body_line = Text()
            body_line.append("     " + farewell_body, style="#9d8ec0")

            def highlight_aria(t: Text) -> Text:
                raw = t.plain
                idx = raw.rfind("- Aria")
                if idx == -1:
                    return t
                before = raw[:idx]
                result = Text()
                result.append(before, style="#9d8ec0")
                result.append("- ", style="#7b6b9a")
                result.append("Aria", style="#c97fd4 bold")
                return result
            body_line = highlight_aria(body_line)

            middle_content = Padding(Group(topic_line, body_line), (1, 4, 1, 4))

            stats_line = Text()
            for part in stats_text.split("|"):
                part = part.strip()
                if ":" in part:
                    k, v = part.split(":", 1)
                    stats_line.append(k.strip() + ": ", style="#7b6b9a")
                    stats_line.append(v.strip(), style="#d1a662")
                else:
                    stats_line.append(part, style="#7b6b9a")
                stats_line.append("  |  ", style="#3d2d5a")
                
            session_id_short = getattr(app, "session_id", "unknown")
            stats_line.append("Session ID: ", style="#7b6b9a")
            stats_line.append(session_id_short, style="#d1a662")

            footer_panel = Panel(
                stats_line,
                title=Text("Metrics", style="#7b6b9a"),
                title_align="left",
                border_style="#3d2d5a",
                box=box.ROUNDED,
            )

            return Padding(Group(header_panel, middle_content, footer_panel), (1, 2))

        try:
            with Live(get_panel(full_text, is_done=False), console=console, refresh_per_second=30) as live:
                if stream is not None:
                    for chunk in stream:
                        if chunk:
                            for char in chunk:
                                full_text += char
                                live.update(get_panel(full_text, is_done=False))
                                time.sleep(0.03)
                live.update(get_panel(full_text, is_done=True))
        except KeyboardInterrupt:
            if 'live' in locals():
                live.update(get_panel(full_text, is_done=True))

