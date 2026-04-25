import os
import subprocess
import sys

import speech_recognition as sr
from textual import work

from aria.core.paths import LAUNCH_DIR

class AriaSystemMixin:
    def _run_syntax_command(self, cmd: list[str], cwd: str | None = None) -> tuple[bool, str]:
        try:
            proc = subprocess.run(
                cmd,
                cwd=cwd or LAUNCH_DIR,
                capture_output=True,
                text=True,
                timeout=30,
                errors="replace",
                shell=False,
            )
            output = (proc.stdout or "") + (("\n" + proc.stderr) if proc.stderr else "")
            output = output.strip() or "[Tanpa output]"
            return proc.returncode == 0, output
        except FileNotFoundError:
            return False, f"Checker tidak tersedia: {cmd[0]}"
        except subprocess.TimeoutExpired:
            return False, f"Checker timeout: {' '.join(cmd)}"
        except Exception as e:
            return False, f"Checker error: {e}"

    def _set_console_title(self, title: str) -> None:
        safe_title = (title or "Aria").replace("\n", " ").replace("\r", " ").strip()
        try:
            if os.name == "nt":
                os.system(f"title {safe_title}")
            else:
                sys.stdout.write(f"\33]0;{safe_title}\a")
                sys.stdout.flush()
        except Exception:
            pass

    @work(thread=True)
    def _start_speech_recognition(self) -> None:
        try:
            with sr.Microphone() as source: self._recognizer.adjust_for_ambient_noise(source, duration=0.5)
            self._stop_listening_fn = self._recognizer.listen_in_background(sr.Microphone(), self._audio_callback)
        except Exception as e:
            self.call_from_thread(self._reset_input_placeholder, f"Error Mic: {str(e)}"); self._stop_listening_fn = None

    def _audio_callback(self, recognizer, audio) -> None:
        if not self._stop_listening_fn: return
        self.call_from_thread(self._reset_input_placeholder, "Memproses suara...")
        try: self.call_from_thread(self._handle_speech_result, recognizer.recognize_google(audio, language="id-ID"))
        except: self.call_from_thread(self._reset_input_placeholder, "Suara tidak jelas...")
        finally:
            if self._stop_listening_fn: self._stop_listening_fn(wait_for_stop=False); self._stop_listening_fn = None

    def _handle_speech_result(self, text: str) -> None:
        self._reset_input_placeholder(); 
        if text: self._submit_to_chat(text)

    def _reset_input_placeholder(self, placeholder: str = "Ketik pesan untuk Aria...") -> None:
        self.query_one("#input-box").border_title = placeholder

