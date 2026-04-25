import random
import re
import sys
import threading
import time
from datetime import datetime

from rich.text import Text
from textual import work
from textual.widgets import Static

from aria.core.constants import FAREWELL_SYSTEM_PROMPT
from aria.utils.time import get_uptime_str

class AriaAppLifecycleMixin:
    def _save_branch(self, label: str = "") -> None:
        self._branch_counter += 1
        ts = datetime.now().strftime("%H:%M:%S")
        branch = {
            "id": self._branch_counter,
            "label": label or f"Turn {self.conversation_turns}",
            "timestamp": ts,
            "history": [dict(m) for m in self.llm.history],
            "file_snapshots": dict(self._pending_file_snapshot),
            "turn_diffs": list(self._turn_file_diffs),
        }
        self._branches.append(branch)
        self._pending_file_snapshot.clear()
        self._turn_file_diffs.clear()

    def _show_branch_ui(self) -> None:
        log = self.query_one("#chat-log")
        if not self._branches:
            box = Static("[bold #d1a662]Branch[/bold #d1a662]\n\nBelum ada branch tersimpan.\nBranch otomatis dibuat setiap kali Aria mengeksekusi tool write/edit.", classes="tool-box")
            log.mount(box); log.scroll_end(animate=False); return

        lines = ["[bold #d1a662]Branch Snapshots[/bold #d1a662]\n"]
        for b in reversed(self._branches):
            lines.append(f"[bold #c97fd4]#{b['id']}[/bold #c97fd4]  [#d1a662]{b['label']}[/#d1a662]  [#7b6b9a]{b['timestamp']}[/#7b6b9a]")
            msg_count = len(b['history'])
            lines.append(f"  [#7b6b9a]{msg_count} pesan tersimpan[/#7b6b9a]")
            if b['turn_diffs']:
                for td in b['turn_diffs']:
                    fname = td['file']
                    added = td['added']; removed = td['removed']
                    lines.append(f"  [#9d8ec0]↳ {fname}[/#9d8ec0]  [bold #71d1d1]+{added}[/bold #71d1d1] [bold #f472b6]-{removed}[/bold #f472b6]")
                    for dl in td.get('diff_preview', [])[:4]:
                        clean = dl.replace('[', '\\[')
                        if dl.startswith('+'):   lines.append(f"    [#71d1d1]{clean}[/#71d1d1]")
                        elif dl.startswith('-'): lines.append(f"    [#f472b6]{clean}[/#f472b6]")
            else:
                lines.append("  [#7b6b9a](tidak ada perubahan file)[/#7b6b9a]")
            lines.append(f"  [#7b6b9a]Ketik [bold]/restore {b['id']}[/bold] untuk kembali ke snapshot ini[/#7b6b9a]\n")

        box = Static("\n".join(lines), classes="tool-box")
        log.mount(box); log.scroll_end(animate=False)

    def _restore_branch(self, branch_id: int) -> None:
        target = next((b for b in self._branches if b['id'] == branch_id), None)
        if target is None:
            log = self.query_one("#chat-log")
            log.mount(Static(f"[bold #f472b6]Branch #{branch_id} tidak ditemukan.[/bold #f472b6]", classes="tool-box"))
            log.scroll_end(animate=False); return
        self.llm.history = [dict(m) for m in target['history']]
        self.llm.history_token_total = sum(self.llm.count_tokens(m['content']) for m in self.llm.history)
        self._refresh_status()
        log = self.query_one("#chat-log")
        log.mount(Static(f"[bold #71d1d1]✓ Restored ke Branch #{branch_id}:[/bold #71d1d1] [#d1a662]{target['label']}[/#d1a662]  [#7b6b9a]{target['timestamp']}[/#7b6b9a]\nHistory percakapan dikembalikan. File di disk tidak diubah.", classes="tool-box"))
        log.scroll_end(animate=False)

    def trigger_exit(self) -> None:
        if not hasattr(self, "is_exiting"):
            self.is_exiting = True
            self.query_one("#input-box").disabled = True
            self._start_loading("Aria bersiap pergi...")
            if self.llm.backend == "cloud":
                self._farewell_chat_ready.clear()
                threading.Thread(target=self._prewarm_farewell_chat, daemon=True).start()
            self.run_worker(self._prepare_farewell, thread=True)

    def request_reload(self, message: str) -> None:
        self.reload_requested = True
        self.skip_farewell = True
        self.query_one("#input-box").disabled = True
        self._start_loading(message)
        self.set_timer(0.2, self.exit)

    def _reset_context_window(self) -> None:
        self.llm.reset_history()
        self.conversation_turns = 0
        self.total_input_tokens = 0
        self.total_output_tokens = 0
        self._refresh_status()
        note = Text("Context window direset.", style="#71d1d1 bold")
        log = self.query_one("#chat-log")
        log.mount(Static(note, classes="tool-box"))
        log.scroll_end(animate=False)

    def _emit_debug_box(self, title: str, payload: str) -> None:
        if not self.debug_mode:
            return
        def do_mount():
            content = f"[DEBUG] {title}\n\n{payload}"
            box = Static(content, classes="tool-box", markup=False)
            self.query_one("#chat-log").mount(box)
            self.query_one("#chat-log").scroll_end(animate=False)
        if threading.get_ident() == getattr(self, "_thread_id", None):
            do_mount()
        else:
            self.call_from_thread(do_mount)

    def _show_current_debug_context(self) -> None:
        if not self.debug_mode:
            return
        if self.llm.backend == "cloud":
            payload = (
                f"model={self.llm.cloud_model}\n\n"
                f"[SYSTEM INSTRUCTION]\n{self.llm.system_prompt or '[kosong]'}"
            )
            self._emit_debug_box("CLOUD SESSION [current]", payload)

    def _prewarm_farewell_chat(self) -> None:
        try:
            self._farewell_chat_prewarm = self.llm.prepare_standalone_chat(FAREWELL_SYSTEM_PROMPT)
        except Exception:
            self._farewell_chat_prewarm = None
        finally:
            self._farewell_chat_ready.set()

    @work(thread=True)
    def _prepare_farewell(self) -> None:
        themes = ["bintang di langit malam", "senja yang berganti fajar", "ombak yang selalu kembali ke pantai", "waktu dan kenangan", "melodi lagu yang indah", "hujan dan pelangi", "buku cerita yang belum selesai", "angin yang membawa rindu"]
        prompt = (
            f"User baru saja menutup program.\n"
            f"Tema: {random.choice(themes)}.\n\n"
            "Baris 1: buat judul puitis, maksimal 5 kata.\n"
            "Baris 2: tulis satu paragraf puitis yang emosional dan hangat.\n"
            "Sampaikan bahwa meskipun Aria harus pergi sementara, ia tidak pernah benar-benar jauh.\n"
            "Baris terakhir: tulis '- Aria'."
        )
        stream = self.llm.stream_standalone_chunks(
            FAREWELL_SYSTEM_PROMPT,
            prompt,
            enable_thinking=False,
            max_tokens=256,
            temperature=0.8,
            skip_min_interval=True,
            chat=self._farewell_chat_prewarm if self._farewell_chat_ready.wait(0.8) else None,
        )
        try:
            first_chunk = next(stream)
        except StopIteration:
            first_chunk = ""
        self.farewell_data = {
            "stream": stream,
            "first_chunk": first_chunk,
            "stats_text": f"Turns    {self.conversation_turns}    |  Tokens (In -> Out) {self.total_input_tokens} -> {self.total_output_tokens}    |  Uptime {get_uptime_str(self.start_time)}",
        }
        self.call_from_thread(self.exit)
        return


def animate_spinner():
    import sys, time
    frames = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]
    i = 0
    try:
        while True:
            sys.stdout.write(f"\r\033[35m{frames[i % len(frames)]}\033[0m \033[90mMembangunkan Aria...\033[0m")
            sys.stdout.flush()
            i += 1; time.sleep(0.08)
    except KeyboardInterrupt: pass

