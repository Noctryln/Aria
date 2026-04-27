import re
import threading
import time

import speech_recognition as sr
from rich.table import Table
from rich.text import Text
from textual import work
from textual.app import App, ComposeResult
from textual.containers import Vertical, VerticalScroll
from textual.widgets import Button, Static, TextArea

import uuid
from aria.agent.agent import AriaAgentMixin, LLMChat
from aria.app.lifecycle import AriaAppLifecycleMixin
from aria.agent.memory import get_session, get_sessions_for_dir, save_current_session
from aria.core.config import save_config
from aria.core.paths import LAUNCH_DIR
from aria.tools.parser import (
    CHECK_FILE_ATTR_PATTERN,
    EDIT_FILE_ATTR_PATTERN,
    READ_END_PATTERN,
    READ_START_PATTERN,
    WRITE_FILE_ATTR_PATTERN,
    parse_tool_block,
)
from aria.ui.rendering import CSS
from aria.ui.widgets.ai_response import AIResponse
from aria.ui.widgets.banner import Banner
from aria.ui.widgets.chat_input import ChatInput
from aria.ui.widgets.think_block import ThinkBlock
from aria.utils.system import AriaSystemMixin
from aria.utils.text import AriaTextMixin

class AriaApp(AriaTextMixin, AriaSystemMixin, AriaAppLifecycleMixin, AriaAgentMixin, App):
    CSS = CSS
    LOADING_FRAMES = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]
    USER_STREAM_INTERVAL = 0.02
    BINDINGS = [("escape", "interrupt", "Stop"), ("ctrl+q", "quit_app", "Quit")]

    def __init__(self, llm: LLMChat, config: dict, resume_session_id: str = None):
        super().__init__()
        self.llm = llm
        self.config = dict(config)
        self.mode_label = llm.mode_label
        self.session_id = resume_session_id if resume_session_id else str(uuid.uuid4())
        self._startup_notification = None
        
        if resume_session_id:
            sess = get_session(resume_session_id)
            if sess:
                import os
                if os.path.normpath(sess.get("dir", "")) == os.path.normpath(LAUNCH_DIR):
                    self.session_id = sess["id"]
                    self.llm.load_history(sess.get("history", []))
                else:
                    self.session_id = str(uuid.uuid4())
                    self._startup_notification = f"[bold #f472b6]Sesi tidak tersedia.[/bold #f472b6] Sesi {resume_session_id[-4:]} berada di direktori yang berbeda. Memulai sesi baru."

        self._loading_frame = 0; self._loading_timer = None; self._stop_listening_fn = None
        self._recognizer = sr.Recognizer(); self.show_thinking = (llm.backend == "cloud"); self._cancel_stream = False 
        self.start_time = 0.0; 
        
        self.conversation_turns = len([m for m in self.llm.history if m["role"] == "user"])
        self.total_input_tokens = sum(self.llm.count_tokens(m["content"]) for m in self.llm.history if m["role"] == "user")
        self.total_output_tokens = sum(self.llm.count_tokens(m["content"]) for m in self.llm.history if m["role"] == "assistant")
        
        self.farewell_data = None; self.current_suggestion = None
        self.tool_permission_session = False; self.tool_permission_event = threading.Event(); self.tool_permission_granted = False
        self.reload_requested = False
        self.skip_farewell = False
        self.debug_mode = False
        self._thread_id = None
        self._farewell_chat_prewarm = None
        self._farewell_chat_ready = threading.Event()
        self.llm.debug_hook = self._emit_debug_box
        self.active_process = None
        self.process_box = None
        self.process_out_lines = []
        self.process_header = ""
        self._suggestion_items: list[str] = []
        self._suggestion_index: int = -1
        self._session_items: list[dict] = []
        self._session_index: int = -1
        self._branches: list[dict] = []
        self._branch_counter: int = 0
        self._pending_file_snapshot: dict[str, str] = {}
        self._turn_file_diffs: list[dict] = []

    def action_interrupt(self) -> None:
        if self.query_one("#session-dialog").display:
            self._hide_session_ui()
            return
        self._cancel_stream = True
        self.llm.request_abort()

    def action_quit_app(self) -> None: self.trigger_exit()

    def action_copy_selection(self) -> None:
        try:
            sel = self.query_one("#input-box").selected_text
            if not sel:
                sel = self.screen.get_selected_text()
            if sel:
                self.copy_to_clipboard(sel)
        except Exception:
            pass

    def compose(self) -> ComposeResult:
        with VerticalScroll(id="chat-log"):
            yield Banner(id="banner")
        with Vertical(id="input-area"):
            yield Static(id="separator"); yield Static("", id="loading-bar")
            with Vertical(id="permission-dialog"):
                yield Static("[bold #e5c07b]Tool Execution Request[/bold #e5c07b]", id="perm-title")
                yield Static("", id="perm-tools-list")
                with Vertical(id="perm-buttons"):
                    yield Button("Allow once", id="btn-allow-once", classes="perm-btn")
                    yield Button("Always allow session", id="btn-allow-session", classes="perm-btn")
                    yield Button("Deny", id="btn-deny", classes="perm-btn")
            with Vertical(id="session-dialog"):
                pass
            chat_input = ChatInput(id="input-box")
            chat_input.show_line_numbers = False; chat_input.border_title = "Ketik pesan untuk Aria..."
            yield chat_input
            yield Vertical(id="cmd-suggestions")
            yield Static(id="status-bar")

    def on_mount(self) -> None:
        self._thread_id = threading.get_ident()
        self.start_time = time.time()
        self._refresh_separator(); self._refresh_status(); self._render_idle_bar(); self.query_one("#input-box").focus()
        if self.llm.history:
            self._render_history()
        if getattr(self, "_startup_notification", None):
            log = self.query_one("#chat-log")
            log.mount(Static(self._startup_notification, classes="tool-box", markup=True))
            log.scroll_end(animate=False)

    def _render_history(self) -> None:
        log = self.query_one("#chat-log")
        from rich.table import Table
        from rich.text import Text
        for m in self.llm.history:
            role = m.get("role")
            content = m.get("content", "")
            
            if role == "user":
                if content.startswith("<system_observation>") or content.startswith("[Sistem:"):
                    continue
                else:
                    grid = Table.grid(padding=(0, 2))
                    grid.add_column(width=1)
                    grid.add_column()
                    
                    import re
                    clean_content = re.sub(r'<system_observation>.*?(?:</system_observation>|$)', '', content, flags=re.DOTALL).strip()
                    
                    t_content = Text(clean_content, style="#c6bbd8")
                    for match in re.finditer(r'\[(?:Image|File)-\d+\]|\[\d+-lines\]', clean_content):
                        t_content.stylize("bold #71d1d1", match.start(), match.end())
                        
                    grid.add_row(Text(">", style="#d1a662 bold"), t_content)
                    user_box = Static(grid, classes="chat-msg-user", markup=False)
                    log.mount(user_box)
            elif role == "assistant":
                resp = AIResponse()
                resp.display = True
                log.mount(resp)
                resp.finalize_animated_content(content.strip())
        log.scroll_end(animate=False)

    def on_resize(self) -> None: self._refresh_separator()

    def _refresh_separator(self) -> None: self.query_one("#separator").update("─" * max(self.app.size.width, 10))

    def _smart_scroll_end(self) -> None:
        try:
            log = self.query_one("#chat-log")
            max_y = getattr(log, "max_scroll_y", 0)
            cur_y = getattr(log, "scroll_y", 0)
            if max_y <= 0 or cur_y >= max_y - 2:
                log.scroll_end(animate=False)
        except Exception: pass

    def _refresh_status(self) -> None:
        max_ctx = self.llm.active_ctx
        remaining_tokens = max(0, max_ctx - self.llm.history_token_total)
        rem_pct_float = (remaining_tokens / max_ctx) * 100 
        rem_pct = int(rem_pct_float)
        
        bar_len = 15
        fill_val = (rem_pct_float / 100) * bar_len
        full_blocks = int(fill_val)
        fraction = fill_val - full_blocks
        
        blocks = [" ", "▏", "▎", "▍", "▌", "▋", "▊", "▉", "█"]
        frac_idx = int(fraction * 8)
        
        if rem_pct > 50: fg_color = "#71d1d1"
        elif rem_pct > 20: fg_color = "#d1a662"
        else: fg_color = "#f472b6"
        
        bg_color = "#2a2a2a" 
        
        bar_text = Text()
        bar_text.append("[", style="#7b6b9a") # Bracket kiri
        
        bar_text.append("█" * full_blocks, style=f"{fg_color} on {bg_color}")
        
        if full_blocks < bar_len:
            bar_text.append(blocks[frac_idx], style=f"{fg_color} on {bg_color}")
            empty_count = bar_len - full_blocks - 1
            bar_text.append(" " * empty_count, style=f"{fg_color} on {bg_color}")

        bar_text.append("] ", style="#7b6b9a") # Bracket kanan
        
        grid = Table.grid(expand=True)
        grid.add_column(justify="left"); grid.add_column(justify="right")
        
        lt, rt = Text(), Text()
        lt.append("Dir: ", style="#7b6b9a"); lt.append(f"{LAUNCH_DIR}  ", style="#d1a662")
        
        rt.append("Context: ", style="#7b6b9a")
        rt.append(bar_text) 
        rt.append(f"{rem_pct}%", style=fg_color)
        
        grid.add_row(lt, rt); self.query_one("#status-bar").update(grid)

    def _render_idle_bar(self) -> None:
        grid = Table.grid(expand=True); grid.add_column(justify="left"); grid.add_column(justify="right")
        grid.add_row(Text(""), Text("Type / for other commands", style="#7b6b9a italic"))
        self.query_one("#loading-bar").update(grid)
        self._set_console_title("Aria")

    _CMD_DESCRIPTIONS = {
        "/speech":  "Aktifkan input suara",
        "/think":   "Toggle mode thinking",
        "/debug":   "Toggle debug API log",
        "/lora":    "Load LoRA adapter: /lora <path|off>",
        "/local":   "Beralih ke backend model lokal",
        "/cloud":   "Beralih ke backend cloud",
        "/github":  "Otentikasi GitHub: /github login",
        "/clear":   "Bersihkan layar chat",
        "/reset":   "Reset context window percakapan",
        "/branch":  "Lihat snapshot branch percakapan",
        "/session": "Lihat/muat sesi percakapan",
        "/quit":    "Keluar dari Aria",
    }

    def _render_suggestions(self, matches: list[str]) -> None:
        self._suggestion_items = matches
        panel = self.query_one("#cmd-suggestions")
        panel.remove_children()
        if not matches:
            panel.display = False
            return
        for i, cmd in enumerate(matches):
            desc = self._CMD_DESCRIPTIONS.get(cmd, "")
            is_sel = (i == self._suggestion_index)
            row = Static(
                f"{'❯ ' if is_sel else '  '}[bold]{cmd}[/bold]  [dim]{desc}[/dim]" if is_sel
                else f"  {cmd}  [dim]{desc}[/dim]",
                classes="cmd-suggestion-item" + (" --highlight" if is_sel else ""),
                markup=True,
            )
            panel.mount(row)
        panel.display = True

    def _hide_suggestions(self) -> None:
        self._suggestion_items = []
        self._suggestion_index = -1
        panel = self.query_one("#cmd-suggestions")
        panel.remove_children()
        panel.display = False

    def _render_sessions(self) -> None:
        panel = self.query_one("#session-dialog")
        panel.remove_children()
        if not self._session_items:
            panel.display = False
            return
        
        # Header
        panel.mount(Static("  [bold #d1a662]ID   | msg | time | input[/bold #d1a662]", markup=True, classes="session-item"))
        
        for i, s in enumerate(self._session_items[:5]): # Max 5 items
            is_sel = (i == self._session_index)
            
            sid = s["id"][-4:]
            msg = str(s.get("msg_count", 0)).rjust(3)
            
            import time as time_mod
            dt = time_mod.time() - s.get("updated_at", time_mod.time())
            if dt < 60:
                t_str = f"{int(dt)}s".rjust(4)
            elif dt < 3600:
                t_str = f"{int(dt/60)}m".rjust(4)
            elif dt < 86400:
                t_str = f"{int(dt/3600)}h".rjust(4)
            else:
                t_str = f"{int(dt/86400)}d".rjust(4)
                
            inp = (s.get("last_input", "") or "...")[:40]
            inp = inp.replace("\n", " ")
            
            row_text = f"{sid} | {msg} | {t_str} | {inp}"
            
            row = Static(
                f"{'❯ ' if is_sel else '  '}[bold]{row_text}[/bold]" if is_sel else f"  {row_text}",
                classes="session-item" + (" --highlight" if is_sel else ""),
                markup=True,
            )
            panel.mount(row)
        panel.display = True

    def _show_session_ui(self) -> None:
        from aria.agent.memory import get_sessions_for_dir
        self._hide_suggestions()
        self.query_one("#input-box").border_title = "Pilih sesi (Panah Bawah/Atas, Enter untuk Load, Esc untuk Batal)"
        sessions = get_sessions_for_dir(LAUNCH_DIR)
        self._session_items = sessions
        self._session_index = 0 if sessions else -1
        if not sessions:
            self._session_items = []
            panel = self.query_one("#session-dialog")
            panel.remove_children()
            panel.mount(Static("  [italic #7b6b9a]Belum ada sesi di direktori ini.[/italic #7b6b9a]", markup=True, classes="session-item"))
            panel.display = True
            return
        self._render_sessions()

    def _hide_session_ui(self) -> None:
        self._session_items = []
        self._session_index = -1
        panel = self.query_one("#session-dialog")
        panel.remove_children()
        panel.display = False
        if not getattr(self, "active_process", None):
            self.query_one("#input-box").border_title = "Ketik pesan untuk Aria..."

    def _suggestion_move(self, direction: int) -> None:
        if self.query_one("#session-dialog").display:
            if not self._session_items: return
            n = min(len(self._session_items), 5)
            self._session_index = (self._session_index + direction) % n
            self._render_sessions()
            return
            
        if not self._suggestion_items:
            return
        n = len(self._suggestion_items)
        self._suggestion_index = (self._suggestion_index + direction) % n
        self._render_suggestions(self._suggestion_items)

    def _start_loading(self, msg="Thinking...") -> None:
        if self._loading_timer:
            self._loading_timer.stop()
            self._loading_timer = None
        self._loading_frame = 0; self.loading_msg = msg; self._render_loading()
        self._loading_timer = self.set_interval(0.08, self._tick_loading)

    def _tick_loading(self) -> None:
        self._loading_frame = (self._loading_frame + 1) % len(self.LOADING_FRAMES); self._render_loading()

    def _render_loading(self) -> None:
        grid = Table.grid(expand=True); grid.add_column(justify="left"); grid.add_column(justify="right")
        lt = Text(); lt.append(f"{self.LOADING_FRAMES[self._loading_frame]} ", style="#c97fd4 bold"); lt.append(self.loading_msg, style="#7b6b9a")
        grid.add_row(lt, Text("Type / for other commands", style="#7b6b9a italic"))
        self.query_one("#loading-bar").update(grid)
        self._set_console_title(f"{self.LOADING_FRAMES[self._loading_frame]} {self.loading_msg}")

    def _stop_loading(self) -> None:
        if self._loading_timer: self._loading_timer.stop(); self._loading_timer = None
        self._render_idle_bar()

    def on_text_area_changed(self, event: TextArea.Changed) -> None:
        if event.text_area.id != "input-box": return
        text = event.text_area.text
        if not self._stop_listening_fn and not hasattr(self, "is_exiting"):
            if not (getattr(self, "active_process", None) and self.active_process.poll() is None):
                event.text_area.border_title = "" if text else "Ketik pesan untuk Aria..."

        if text.startswith("/"):
            all_cmds = ["/speech", "/think", "/debug", "/lora", "/local", "/cloud", "/github", "/clear", "/reset", "/branch", "/session", "/quit"]
            matches = [c for c in all_cmds if c.startswith(text.lower())]
            # Reset index jika daftar matches berubah
            if matches != self._suggestion_items:
                self._suggestion_index = 0 if matches else -1
            self.current_suggestion = matches[self._suggestion_index] if matches and self._suggestion_index >= 0 else (matches[0] if matches else None)
            self._render_suggestions(matches)
            if self._loading_timer is None: self._render_idle_bar()
        else:
            self.current_suggestion = None
            self._hide_suggestions()
            if self._loading_timer is None: self._render_idle_bar()

    def handle_input_submission(self, text: str, attachments: dict = None) -> None:
        if attachments is None:
            attachments = {}
            
        if self.query_one("#session-dialog").display:
            if self._session_items and self._session_index >= 0:
                selected = self._session_items[self._session_index]
                self._hide_session_ui()
                self.session_id = selected["id"]
                self.request_reload(f"Loading session {self.session_id[-4:]}...")
            else:
                self._hide_session_ui()
            return

        if self._stop_listening_fn:
            self._stop_listening_fn(wait_for_stop=False); self._stop_listening_fn = None; self._reset_input_placeholder(); return
            
        if getattr(self, "active_process", None) and self.active_process.poll() is None:
            try:
                self.active_process.stdin.write(text + "\n")
                self.active_process.stdin.flush()
                self.process_out_lines.append((text + "\n", True))
                if hasattr(self, "_live_ui_updater"):
                    self._live_ui_updater()
            except Exception: pass
            return

        if text.startswith("/"):
            if self._suggestion_index >= 0 and self._suggestion_items:
                text = self._suggestion_items[self._suggestion_index]
            elif self.current_suggestion:
                text = self.current_suggestion
        if not text: return
        self.current_suggestion = None
        self._hide_suggestions()
        if self._loading_timer is None: self._render_idle_bar()

        lower_text = text.lower()
        if lower_text == "/session": self._show_session_ui(); return
        if lower_text == "/speech": self.query_one("#input-box").border_title = "Mendengarkan... (Bicara sekarang, Enter untuk batal)"; self._start_speech_recognition(); return
        if lower_text.startswith("/github"):
            parts = text.split()
            if len(parts) > 1 and parts[1].lower() == "login":
                self._github_login_flow()
            else:
                log = self.query_one("#chat-log")
                log.mount(Static("[bold #d1a662]GitHub Command:[/bold #d1a662]\nUsage: /github login", classes="tool-box"))
                log.scroll_end(animate=False)
            return
        if lower_text == "/think":
            self.show_thinking = not self.show_thinking
            t_status = Text(f"Thinking: {'Aktif' if self.show_thinking else 'Non-aktif'}", style="#71d1d1 bold")
            log = self.query_one("#chat-log"); log.mount(Static(t_status, classes="tool-box")); log.scroll_end(animate=False); return
        if lower_text == "/debug":
            self.debug_mode = not self.debug_mode
            t_status = Text(f"Debug API: {'Aktif' if self.debug_mode else 'Non-aktif'}", style="#71d1d1 bold")
            log = self.query_one("#chat-log"); log.mount(Static(t_status, classes="tool-box")); log.scroll_end(animate=False)
            if self.debug_mode:
                self._show_current_debug_context()
                if self.llm.backend == "cloud":
                    self.llm.reset_history()
            return
        if lower_text == "/clear":
            self.query_one("#chat-log").remove_children()
            self._reset_input_placeholder()
            if self._loading_timer is None: self._render_idle_bar()
            return
        if lower_text.startswith("/reset"):
            self._reset_context_window()
            return
        if lower_text.startswith("/cloud"):
            self.config["backend"] = "cloud"
            save_config(self.config)
            self.request_reload("Beralih ke Cloud...")
            return
        if lower_text.startswith("/local"):
            self.config["backend"] = "local"
            save_config(self.config)
            self.request_reload("Beralih ke Local...")
            return
        if lower_text.startswith("/lora"):
            parts = text.split(maxsplit=1)
            arg = parts[1].strip() if len(parts) > 1 else ""
            self.config["backend"] = "local"
            if arg:
                if arg.lower() in ("off", "none", "disable"):
                    self.config["lora_adapter_path"] = ""
                else:
                    self.config["lora_adapter_path"] = arg
            save_config(self.config)
            self.request_reload("Memuat ulang model lokal...")
            return
        if lower_text in ("exit", "quit", "/quit"): self.trigger_exit(); return
        if lower_text == "/branch":
            self._show_branch_ui(); return
        if lower_text.startswith("/restore"):
            parts = text.split(maxsplit=1)
            if len(parts) == 2 and parts[1].strip().isdigit():
                self._restore_branch(int(parts[1].strip()))
            else:
                log = self.query_one("#chat-log")
                log.mount(Static("[bold #f472b6]Usage:[/bold #f472b6] /restore <id>  (lihat id dari /branch)", classes="tool-box"))
                log.scroll_end(animate=False)
            return
        self._submit_to_chat(text, attachments=attachments)

    def _animate_user_message(self, widget: Static, text: str) -> None:
        rendered_chars = 0
        total_chars = len(text)
        step = max(2, total_chars // 15)
        timer_ref = {"timer": None}

        def render_now() -> None:
            nonlocal rendered_chars
            rendered_chars = min(total_chars, rendered_chars + step)
            
            grid = Table.grid(padding=(0, 2))
            grid.add_column(width=1)
            grid.add_column()
            
            t_content = Text(text[:rendered_chars], style="#c6bbd8")
            import re
            for match in re.finditer(r'\[(?:Image|File)-\d+\]|\[\d+-lines\]', text[:rendered_chars]):
                t_content.stylize("bold #71d1d1", match.start(), match.end())
                
            grid.add_row(Text(">", style="#d1a662 bold"), t_content)

            widget.update(grid)
            self.query_one("#chat-log").scroll_end(animate=False)
            if rendered_chars >= total_chars and timer_ref["timer"] is not None:
                timer_ref["timer"].stop()

        timer_ref["timer"] = self.set_interval(self.USER_STREAM_INTERVAL, render_now)
        render_now()

    def _show_permission_dialog(self, tags: list) -> None:
        self._stop_loading()
        dialog = self.query_one("#permission-dialog")
        
        clean_tags = []
        for t in tags:
            parsed = parse_tool_block(t)
            if parsed:
                tag_name = parsed["tag"]
                attrs = parsed["attrs"].strip()
                inner = parsed["body"].strip()
                if tag_name == "write":
                    fname = WRITE_FILE_ATTR_PATTERN.search(attrs)
                    fname = fname.group(1) if fname else "File"
                    clean_tags.append(f"• [bold #71d1d1]Writing File:[/bold #71d1d1] {fname} [italic]({len(inner.splitlines())} lines code)[/italic]")
                elif tag_name == "edit":
                    fname = EDIT_FILE_ATTR_PATTERN.search(attrs)
                    fname = fname.group(1) if fname else "File"
                    start_match = READ_START_PATTERN.search(attrs)
                    end_match = READ_END_PATTERN.search(attrs)
                    if start_match and end_match:
                        span = f" lines {start_match.group(1)}-{end_match.group(1)}"
                    elif start_match:
                        span = f" line {start_match.group(1)}"
                    else:
                        span = ""
                    clean_tags.append(f"• [bold #71d1d1]Editing File:[/bold #71d1d1] {fname}{span}")
                elif tag_name == "check_syntax":
                    fname = CHECK_FILE_ATTR_PATTERN.search(attrs)
                    fname = fname.group(1) if fname else "File"
                    clean_tags.append(f"[bold #c97fd4]Check Syntax:[/bold #c97fd4] {fname}")
                elif tag_name in ["run_cmd", "runcmd"]:
                    clean_tags.append(f"• [bold #f472b6]Eksekusi Perintah:[/bold #f472b6] {inner}")
                elif tag_name == "search_workspace":
                    clean_tags.append(f"• [bold #d1a662]Search Workspace:[/bold #d1a662] {inner}")
                else:
                    clean_tags.append(f"• [bold #d1a662]{tag_name.upper()}:[/bold #d1a662] {attrs} {inner[:40]}...")
            else:
                clean_tags.append(f"• [#71d1d1]Tool Eksekusi[/#71d1d1]")

        self.query_one("#perm-tools-list").update("\n".join(clean_tags))
        self.query_one("#input-box").disabled = True
        dialog.display = True; self.query_one("#btn-allow-once").focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id in ("btn-allow-once", "btn-allow-session", "btn-deny"):
            self.query_one("#permission-dialog").display = False
            self.query_one("#input-box").disabled = False; self.query_one("#input-box").focus()

            if event.button.id == "btn-allow-session": self.tool_permission_session = True; self.tool_permission_granted = True
            elif event.button.id == "btn-allow-once": self.tool_permission_granted = True
            else: self.tool_permission_granted = False

            self._start_loading("Executing tools..."); self.tool_permission_event.set()

    def _save_session_sync(self) -> None:
        from aria.agent.memory import save_current_session
        user_msgs = [
            m["content"] for m in self.llm.history 
            if m["role"] == "user" 
            and not m["content"].startswith("<system_observation>") 
            and not m["content"].startswith("[Sistem:")
        ]
        last_input = user_msgs[-1] if user_msgs else ""
        import re
        last_input = re.sub(r'<system_observation>.*?(?:</system_observation>|$)', '', last_input, flags=re.DOTALL).strip()
        save_current_session(self.session_id, LAUNCH_DIR, self.llm.history, len(self.llm.history), last_input)

    @work(thread=True)
    def _run_stream(self) -> None:
        last_user_msg = ""
        for m in reversed(self.llm.history):
            if m['role'] == 'user' and not m['content'].startswith('<system_observation>'):
                last_user_msg = m['content']
                break
        _complex_keywords = ['buat', 'tulis', 'refactor', 'ubah semua', 'perbaiki', 'implementasi',
                             'create', 'build', 'fix all', 'migrate', 'rename', 'restructure']
        _is_complex = (
            len(last_user_msg) > 80 and
            sum(1 for kw in _complex_keywords if kw in last_user_msg.lower()) >= 1 and
            any(w in last_user_msg.lower() for w in ['file', 'kode', 'code', 'fungsi', 'function', 'semua', 'all'])
        )
        if _is_complex:
            plan_injection = (
                "<system_observation>\n"
                "PLANNING MODE: Task ini terdeteksi kompleks.\n"
                "Sebelum mengeksekusi tool apa pun, buat rencana langkah-langkah eksplisit terlebih dahulu:\n"
                "1. Sebutkan file/komponen yang akan disentuh\n"
                "2. Urutan operasi yang akan dilakukan\n"
                "3. Potensi risiko atau dependency\n"
                "Setelah plan disetujui secara implisit (tidak perlu tanya user), lanjut eksekusi.\n"
                "</system_observation>"
            )
            for i in range(len(self.llm.history) - 1, -1, -1):
                if self.llm.history[i]['role'] == 'user' and not self.llm.history[i]['content'].startswith('<system_observation>'):
                    self.llm.history[i] = dict(self.llm.history[i])
                    self.llm.history[i]['content'] += plan_injection
                    break
        self.call_from_thread(self._start_loading, "Aria berpikir...")
        widgets = {}

        def setup_msg():
            widgets['resp'] = AIResponse()
            widgets['resp'].display = True
            log = self.query_one("#chat-log")
            log.mount(widgets['resp'])
            widgets['resp'].start_thinking_placeholder()
            log.scroll_end(animate=False)

        self.call_from_thread(setup_msg)
        buf = ""; resp_text = ""; last_update_time = 0.0; last_scroll_time = 0.0
        _streaming_started = False

        def update_ui(r_text: str):
            if 'resp' not in widgets: return
            clean_r = r_text.strip()
            if clean_r:
                widgets['resp'].display = True
                if self.llm.backend == "cloud":
                    resp_widget = widgets['resp']
                    if len(resp_widget._content_animation_visible) > len(clean_r):
                        resp_widget._content_animation_visible = clean_r
                    resp_widget._content_animation_target = clean_r
                    if resp_widget._content_animation_timer is None:
                        resp_widget._content_animation_timer = resp_widget.set_interval(
                            AriaApp.USER_STREAM_INTERVAL, resp_widget._tick_content_animation
                        )
                else:
                    widgets['resp'].update_content(clean_r)
            else:
                widgets['resp'].stop_content_animation()
                widgets['resp'].stop_thinking_placeholder()
                widgets['resp'].display = False
            nonlocal last_scroll_time
            now = time.time()
            if now - last_scroll_time >= 0.12:
                self._smart_scroll_end()
                last_scroll_time = now

        def trigger_update(force=False):
            nonlocal last_update_time; now = time.time()
            if force or (now - last_update_time > 0.05):
                self.call_from_thread(update_ui, resp_text); last_update_time = now

        self._cancel_stream = False
        stream_error = None
        try:
            for raw_token in self.llm.stream_response(enable_thinking=self.show_thinking):
                if not _streaming_started:
                    _streaming_started = True
                    # Fase 2: streaming dimulai → ubah loading ke "Aria Mengetik..."
                    self.call_from_thread(self._start_loading, "Aria Mengetik...")
                if self._cancel_stream:
                    resp_text += "\n\n*[Dihentikan]*"
                    break

                # Update status berdasarkan keberadaan tag think yang belum ditutup
                is_thinking = False
                if self.show_thinking:
                    open_count = (resp_text + buf).count("<think>")
                    close_count = (resp_text + buf).count("</think>")
                    is_thinking = open_count > close_count
                
                target_msg = "Aria Berpikir..." if is_thinking else "Aria Mengetik..."
                if getattr(self, "loading_msg", "") != target_msg:
                    self.call_from_thread(self._start_loading, target_msg)

                # Jika show_thinking False, hapus tag think on the fly (jika ada)
                if not self.show_thinking:
                    buf += raw_token.replace("\r", "")
                    # Sangat disederhanakan: Hapus tag think
                    idx = buf.find("<think>")
                    if idx != -1:
                        idx_close = buf.find("</think>", idx)
                        if idx_close != -1:
                            buf = buf[:idx] + buf[idx_close + 8:]
                        else:
                            # Masih menunggu penutup tag, simpan di buf
                            pass
                    if "<think>" not in buf:
                        resp_text += buf; buf = ""
                else:
                    resp_text += raw_token.replace("\r", "")

                trigger_update()
        except Exception as e:
            stream_error = e

        if buf and not self.show_thinking and "<think>" not in buf:
            resp_text += buf
        elif buf and self.show_thinking:
            resp_text += buf

        if stream_error is not None and not self._cancel_stream:
            resp_text += f"\n\n*[Runtime LLM Error: {stream_error}]*"
        if self._cancel_stream and not resp_text.strip():
            resp_text = "*[Dihentikan sebelum output tampil]*"

        trigger_update(force=True)
        if self.llm.backend == "cloud":
            self.call_from_thread(widgets['resp'].finalize_animated_content, resp_text.strip())
        self.total_output_tokens += self.llm.count_tokens(resp_text)
        self.call_from_thread(self._refresh_status)

        tool_ready_resp = resp_text
        extracted_tools = self._extract_tools_from_text(tool_ready_resp)
        active_tags = [t["full"] for t in extracted_tools]

        if active_tags:
            if not self.tool_permission_session:
                self.call_from_thread(self._show_permission_dialog, active_tags)
                self.tool_permission_event.clear(); self.tool_permission_event.wait()

                if not self.tool_permission_granted:
                    denied_resp_text = self._decorate_tool_tags_with_status(resp_text, "denied")
                    self.llm.add_message("assistant", denied_resp_text)
                    self.call_from_thread(update_ui, denied_resp_text)
                    self.call_from_thread(self._stop_loading)
                    self.call_from_thread(self._submit_to_chat, "<system_observation>\nERROR: Permission Denied by User.\nSTATUS TOOL: Izin ditolak oleh user.\n</system_observation>", True)
                    return

        tool_outputs, full_combined_resp = self._process_tools(resp_text, widgets['resp'])

        if self._turn_file_diffs or self._pending_file_snapshot:
            user_msgs = [m['content'] for m in self.llm.history if m['role'] == 'user']
            last_user = user_msgs[-1][:40].replace('\n', ' ') if user_msgs else "turn"
            self._save_branch(label=last_user)

        import re
        history_resp_text = re.sub(r'<ui_notif>.*?</ui_notif>', '', full_combined_resp, flags=re.DOTALL).strip()
        self.llm.add_message("assistant", history_resp_text)
        
        if self.llm.backend == "cloud":
            self.call_from_thread(widgets['resp'].finalize_animated_content, full_combined_resp)
        self.call_from_thread(update_ui, full_combined_resp)
        self.call_from_thread(self._stop_loading)

        if tool_outputs:
            has_error = any(
                ("-> Error:" in o or "FAILED" in o.upper() or "tidak ditemukan" in o.lower())
                for o in tool_outputs
            )

            obs_content = "HASIL DARI TOOL:\n\n" + "\n\n".join(tool_outputs)
            if has_error:
                obs_content += (
                    "\n\n[!] SELF-CORRECTION REQUIRED: Satu atau lebih tool mengalami error di atas.\n"
                    "Analisis penyebab error, lalu coba strategi alternatif tanpa meminta konfirmasi user.\n"
                    "Jangan ulangi pendekatan yang sama persis. Jika error tidak bisa dipulihkan, jelaskan alasannya secara singkat."
                )

            obs_text = f"[Sistem: Hasil Eksekusi Tool]\n<system_observation>\n{obs_content}\n</system_observation>"
            self.call_from_thread(self._submit_to_chat, obs_text, True)
            
        self.call_from_thread(self._save_session_sync)
