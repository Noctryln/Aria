import difflib
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import urllib.parse
import urllib.request

from rich.markup import escape as rich_escape

from aria.core.paths import LAUNCH_DIR
from aria.tools.parser import (
    CHECK_FILE_ATTR_PATTERN,
    EDIT_FILE_ATTR_PATTERN,
    READ_END_PATTERN,
    READ_START_PATTERN,
    WRITE_FILE_ATTR_PATTERN,
)

class AriaToolExecutorMixin:
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

    def _check_syntax_for_file(self, path: str) -> tuple[bool, str]:
        abs_path = os.path.abspath(path)
        ext = os.path.splitext(path)[1].lower()
        base_dir = os.path.dirname(abs_path) or LAUNCH_DIR

        if ext == ".py":
            return self._run_syntax_command([sys.executable, "-m", "py_compile", abs_path])
        if ext in (".js", ".mjs", ".cjs"):
            return self._run_syntax_command(["node", "--check", abs_path])
        if ext in (".ts", ".tsx"):
            return self._run_syntax_command(["tsc", "--pretty", "false", "--noEmit", abs_path], cwd=base_dir)
        if ext == ".json":
            try:
                with open(abs_path, "r", encoding="utf-8") as f:
                    json.load(f)
                return True, "JSON valid."
            except Exception as e:
                return False, str(e)
        if ext in (".yaml", ".yml"):
            try:
                import yaml
                with open(abs_path, "r", encoding="utf-8") as f:
                    yaml.safe_load(f)
                return True, "YAML valid."
            except ImportError:
                return False, "Checker tidak tersedia: PyYAML belum diinstall."
            except Exception as e:
                return False, str(e)
        if ext == ".php":
            return self._run_syntax_command(["php", "-l", abs_path])
        if ext == ".rb":
            return self._run_syntax_command(["ruby", "-c", abs_path])
        if ext in (".sh", ".bash"):
            return self._run_syntax_command(["bash", "-n", abs_path])
        if ext == ".ps1":
            return self._run_syntax_command([
                "powershell",
                "-NoProfile",
                "-Command",
                f"[System.Management.Automation.Language.Parser]::ParseFile('{abs_path}', [ref]$null, [ref]$null) | Out-Null"
            ])
        if ext == ".lua":
            return self._run_syntax_command(["luac", "-p", abs_path])
        if ext == ".java":
            return self._run_syntax_command(["javac", "-Xlint:none", abs_path], cwd=base_dir)
        if ext == ".go":
            return self._run_syntax_command(["gofmt", "-e", abs_path])
        if ext == ".rs":
            out_dir = os.path.join(LAUNCH_DIR, ".aria_syntax_cache")
            os.makedirs(out_dir, exist_ok=True)
            return self._run_syntax_command(["rustc", "--emit", "metadata", "--out-dir", out_dir, abs_path], cwd=base_dir)
        if ext == ".c":
            return self._run_syntax_command(["gcc", "-fsyntax-only", abs_path], cwd=base_dir)
        if ext in (".cc", ".cpp", ".cxx"):
            return self._run_syntax_command(["g++", "-fsyntax-only", abs_path], cwd=base_dir)
        if ext in (".h", ".hpp"):
            return False, "Header file tidak bisa dicek sendirian secara generik. Buat file unit/translation yang meng-include header ini."
        if ext == ".swift":
            return self._run_syntax_command(["swiftc", "-parse", abs_path], cwd=base_dir)
        if ext == ".kt":
            return self._run_syntax_command(["kotlinc", abs_path, "-d", os.path.join(LAUNCH_DIR, ".aria_syntax_cache", "kotlinc-check.jar")], cwd=base_dir)
        if ext == ".r":
            r_path = abs_path.replace("\\", "/")
            return self._run_syntax_command(["Rscript", "-e", f"parse(file='{r_path}')"])
        if ext in (".xml", ".html", ".svg"):
            try:
                import xml.etree.ElementTree as ET
                ET.parse(abs_path)
                return True, "XML-like syntax valid."
            except Exception as e:
                return False, str(e)
        if ext == ".css":
            return False, "Checker CSS generik belum tersedia di lingkungan ini."

        return False, f"Bahasa/ekstensi belum didukung untuk check_syntax: {ext or '[tanpa ekstensi]'}"

    def _process_tools(self, text: str, resp_widget) -> tuple[list[str], str]:
        return _process_tools(self, text, resp_widget)

def _process_tools(self, text: str, resp_widget) -> tuple[list[str], str]:
        import re
        import os
        tool_outputs = []

        def is_safe_path(target_path):
            try: return os.path.commonpath([os.path.realpath(LAUNCH_DIR), os.path.realpath(target_path)]) == os.path.realpath(LAUNCH_DIR)
            except ValueError: return False

        def format_diff_with_lines(diff: list[str]) -> list[str]:
            colored_diff = []
            old_ln = 0
            new_ln = 0
            for line in diff:
                clean_line = line.replace('[', '\\[')
                if line.startswith('+++') or line.startswith('---'):
                    colored_diff.append(f"[bold]{clean_line}[/bold]")
                elif line.startswith('@@'):
                    m = re.search(r'@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@', line)
                    if m:
                        old_ln = int(m.group(1))
                        new_ln = int(m.group(2))
                    colored_diff.append(f"[#71d1d1]{clean_line}[/#71d1d1]")
                else:
                    clean_sub = line[1:].replace('[', '\\[') if len(line) > 1 else ""
                    if line.startswith('+'):
                        colored_diff.append(f"[#71d1d1 on #0d1a12]{new_ln:4} │ + {clean_sub}[/]")
                        new_ln += 1
                    elif line.startswith('-'):
                        colored_diff.append(f"[#f472b6 on #2a0d1a]{old_ln:4} │ - {clean_sub}[/]")
                        old_ln += 1
                    elif line.startswith('\\'):
                        colored_diff.append(f"     │   {clean_sub}")
                    else:
                        colored_diff.append(f"{new_ln:4} │   {clean_sub}")
                        old_ln += 1
                        new_ln += 1
            return colored_diff

        extracted_tools = self._extract_tools_from_text(text)
        
        ui_pieces = []
        last_idx = 0

        for tool_dict in extracted_tools:
            start = tool_dict["start"]
            end = tool_dict["end"]
            
            ui_pieces.append(text[last_idx:start])
            
            tag = tool_dict["tag"].lower()
            attrs = tool_dict["attrs"]
            inner = tool_dict["inner"]
            full_tag = tool_dict["full"]

            is_success = True
            current_notifs = []
            
            def add_notif(markup_text):
                current_notifs.append(markup_text)
                running_tag = self._decorate_tool_tags_with_status(full_tag, "running")
                combined_notif = "\n\n".join(current_notifs)
                current_ui = "".join(ui_pieces) + running_tag + f"<ui_notif>{combined_notif}</ui_notif>" + text[end:]
                self.call_from_thread(lambda ui=current_ui: resp_widget.update_content(ui))
                self.call_from_thread(lambda: self.query_one("#chat-log").scroll_end(animate=False))

            def update_last_notif(markup_text):
                if current_notifs:
                    current_notifs[-1] = markup_text
                else:
                    current_notifs.append(markup_text)
                running_tag = self._decorate_tool_tags_with_status(full_tag, "running")
                combined_notif = "\n\n".join(current_notifs)
                current_ui = "".join(ui_pieces) + running_tag + f"<ui_notif>{combined_notif}</ui_notif>" + text[end:]
                self.call_from_thread(lambda ui=current_ui: resp_widget.update_content(ui))
                self.call_from_thread(lambda: self.query_one("#chat-log").scroll_end(animate=False))

            if tag == 'ls':
                path = inner.strip().strip("'").strip('"') or "."
                if not is_safe_path(path):
                    tool_outputs.append(f"[LS {path}] -> Error: Access Denied.")
                    add_notif(f"[bold #f472b6]Access Denied:[/bold #f472b6] ({path})")
                    is_success = False
                elif os.path.isfile(path):
                    try:
                        lines = sum(1 for _ in open(path, 'r', encoding='utf-8'))
                        limit_saran = 1000 if self.llm.backend == "cloud" else 50
                        peringatan = f"\n  → Panjang. Gunakan <read start=\"1\" end=\"{limit_saran}\">{path}</read>" if lines > limit_saran else ""
                        tool_outputs.append(f"[LS {path}] -> {os.path.basename(path)} ({lines} baris){peringatan}")
                        add_notif(f"[bold]Aria checking file:[/bold] [#d1a662]{path}[/#d1a662]")
                    except Exception as e:
                        tool_outputs.append(f"[LS {path}] -> Error: {e}")
                        is_success = False
                elif not os.path.exists(path):
                    tool_outputs.append(f"[LS {path}] -> ERROR: Not found.")
                    is_success = False
                else:
                    try:
                        item_details = []
                        for item in os.listdir(path):
                            fp = os.path.join(path, item)
                            if os.path.isdir(fp): item_details.append(f"{item}/")
                            else:
                                try: item_details.append(f"{item} ({sum(1 for _ in open(fp, 'r', encoding='utf-8'))} baris)")
                                except: item_details.append(f"{item} (unknown)")
                        tool_outputs.append(f"[LS {path}] ->\n" + "\n".join(item_details))
                        add_notif(f"[bold]Aria checking dir:[/bold] [#d1a662]{path}[/#d1a662]")
                    except Exception as e:
                        tool_outputs.append(f"[LS {path}] -> Error: {e}")
                        is_success = False

            elif tag == 'find_file':
                pattern = inner.strip().strip("'").strip('"')
                import glob
                try:
                    results = glob.glob(pattern, recursive=True)
                    if not results:
                        tool_outputs.append(f"[FIND_FILE '{pattern}'] -> Not found.")
                    else:
                        limit = 100
                        res_list = [f"{fp} ({os.path.getsize(fp)} bytes)" if os.path.isfile(fp) else fp + "/" for fp in results[:limit]]
                        res_text = "\n".join(res_list)
                        if len(results) > limit:
                            res_text += f"\n... dan {len(results) - limit} file lainnya."
                        tool_outputs.append(f"[FIND_FILE '{pattern}'] ->\n{res_text}")
                    add_notif(f"[bold]Aria finding file:[/bold] [#d1a662]{pattern}[/#d1a662]")
                except Exception as e:
                    tool_outputs.append(f"[FIND_FILE '{pattern}'] -> Error: {e}")
                    is_success = False

            elif tag == 'read':
                path = inner.strip().strip("'").strip('"')
                if not path:
                    fname_match = re.search(r'file=["\']?([^"\'>]+)["\']?', attrs, re.IGNORECASE)
                    path = fname_match.group(1) if fname_match else ""
                
                if not path:
                    tool_outputs.append(f"[READ] -> Error: Path tidak ditemukan (gunakan <read>path</read> atau <read file='path'>).")
                    is_success = False
                elif not is_safe_path(path):
                    tool_outputs.append(f"[READ {path}] -> Error: Access Denied.")
                    is_success = False
                else:
                    sm = READ_START_PATTERN.search(attrs); em = READ_END_PATTERN.search(attrs)
                    sl, el = int(sm.group(1)) if sm else None, int(em.group(1)) if em else None
                    try:
                        try:
                            lines = open(path, 'r', encoding='utf-8').read().splitlines()
                        except UnicodeDecodeError:
                            from tika import parser
                            parsed = parser.from_file(path)
                            extracted_content = parsed.get("content", "")
                            if not extracted_content:
                                raise Exception("Gagal mengekstrak konten via Tika (mungkin format tidak didukung).")
                            lines = extracted_content.strip().splitlines()

                        tl = len(lines)
                        if sl is not None and el is not None:
                            si, ei = max(0, sl - 1), min(tl, el); content = "\n".join([f"{i+si+1}| {l}" for i, l in enumerate(lines[si:ei])])
                            tool_outputs.append(f"[READ {path}] ->\nIsi (Baris {si+1}-{ei} dari {tl}):\n{content}")
                            add_notif(f"[bold]Aria reading:[/bold] [#d1a662]{path}[/#d1a662] [italic](Lines {si+1}-{ei})[/italic]")
                        else:
                            max_lines = 1000 if self.llm.backend == "cloud" else 50
                            if tl > max_lines:
                                 content = "\n".join([f"{i+1}| {l}" for i, l in enumerate(lines[:max_lines])])
                                 tool_outputs.append(f"[READ {path}] ->\n[PERINGATAN] Panjang ({tl} baris). Ini {max_lines} baris pertama:\n{content}")
                                 add_notif(f"[bold #d1a662]Aria reading:[/bold #d1a662] [#d1a662]{path}[/#d1a662] (Lines 1-{max_lines})")
                            else:
                                 content = "\n".join([f"{i+1}| {l}" for i, l in enumerate(lines)])
                                 tool_outputs.append(f"[READ {path}] ->\nIsi penuh ({tl} baris):\n{content}")
                                 add_notif(f"[bold]Aria reading:[/bold] [#d1a662]{path}[/#d1a662]")
                    except Exception as e:
                        tool_outputs.append(f"[READ {path}] -> Error: {e}")
                        is_success = False

            elif tag == 'write':
                fname_match = WRITE_FILE_ATTR_PATTERN.search(attrs)
                filename = fname_match.group(1).strip() if fname_match else "File"
                if not is_safe_path(filename):
                    tool_outputs.append(f"[WRITE {filename}] -> Error: Access Denied.")
                    is_success = False
                else:
                    new_content = re.sub(r'^```[a-zA-Z0-9]*\n', '', inner)
                    new_content = re.sub(r'\n```$', '', new_content).strip() + '\n'
                    os.makedirs(os.path.dirname(filename) or ".", exist_ok=True)
                    old_lines = open(filename, 'r', encoding='utf-8').read().splitlines() if os.path.exists(filename) else []
                    if filename not in self._pending_file_snapshot:
                        self._pending_file_snapshot[filename] = "\n".join(old_lines)
                    new_lines = new_content.splitlines()
                    diff = list(difflib.unified_diff(old_lines, new_lines, fromfile=f"a/{filename}", tofile=f"b/{filename}", lineterm=''))
                    try:
                        open(filename, 'w', encoding='utf-8').write(new_content)
                        tool_outputs.append(f"[WRITE {filename}] -> Sukses.")
                        # Catat diff untuk branch
                        added = sum(1 for l in diff if l.startswith('+') and not l.startswith('+++'))
                        removed = sum(1 for l in diff if l.startswith('-') and not l.startswith('---'))
                        preview = [l for l in diff if l.startswith(('+', '-')) and not l.startswith(('+++', '---'))][:6]
                        self._turn_file_diffs.append({"file": filename, "added": added, "removed": removed, "diff_preview": preview})
                        if not diff:
                            add_notif(f"[bold]File [#d1a662]{filename}[/#d1a662] with no changes.[/bold]")
                        else:
                            colored_diff = []
                            for line in diff:
                                clean_line = line.replace('[', '\\[')
                                clean_sub = line[1:].replace('[', '\\[') if len(line) > 1 else ""
                                if line.startswith('+++') or line.startswith('---'): colored_diff.append(f"[bold]{clean_line}[/bold]")
                                elif line.startswith('+'): colored_diff.append(f"[#71d1d1 on #0d1a12]+  {clean_sub}[/]")
                                elif line.startswith('-'): colored_diff.append(f"[#f472b6 on #2a0d1a]-  {clean_sub}[/]")
                                elif line.startswith('@@'): colored_diff.append(f"[#71d1d1]{clean_line}[/#71d1d1]")
                                else: colored_diff.append(f"   {clean_sub}" if line.startswith(' ') else clean_line)
                            diff_str = "\n".join(colored_diff)
                            additions = sum(1 for l in diff if l.startswith('+') and not l.startswith('+++'))
                            deletions = sum(1 for l in diff if l.startswith('-') and not l.startswith('---'))
                            add_notif(f"[bold]File Updated:[/bold] [#d1a662]{filename}[/#d1a662]   [bold #71d1d1]+{additions}[/bold #71d1d1] [bold #f472b6]-{deletions}[/bold #f472b6]\n\n{diff_str}")
                    except Exception as e:
                        tool_outputs.append(f"[WRITE {filename}] -> Error: {e}")
                        is_success = False

            elif tag == 'edit':
                fname_match = EDIT_FILE_ATTR_PATTERN.search(attrs)
                filename = fname_match.group(1).strip() if fname_match else ""
                
                if not filename:
                    tool_outputs.append("[EDIT] -> Error: file attribute wajib diisi.")
                    is_success = False
                elif not is_safe_path(filename):
                    tool_outputs.append(f"[EDIT {filename}] -> Error: Access Denied.")
                    add_notif(f"[bold #f472b6]Access Denied:[/bold #f472b6] ({filename})")
                    is_success = False
                elif not os.path.exists(filename):
                    tool_outputs.append(f"[EDIT {filename}] -> Error: File tidak ditemukan.")
                    add_notif(f"[bold #f472b6]File Not Found:[/bold #f472b6] [#d1a662]{filename}[/#d1a662]")
                    is_success = False
                else:
                    edit_match = re.search(r'<search>\n*(.*?)\n*</search>\s*<replace>\n*(.*?)\n*</replace>', inner, re.DOTALL | re.IGNORECASE)
                    
                    if edit_match:
                        search_str = edit_match.group(1).replace('\r\n', '\n')
                        replace_str = edit_match.group(2).replace('\r\n', '\n')
                        try:
                            old_text = open(filename, 'r', encoding='utf-8').read()
                            # Simpan snapshot sebelum edit untuk branch
                            if filename not in self._pending_file_snapshot:
                                self._pending_file_snapshot[filename] = old_text
                            old_text_normalized = old_text.replace('\r\n', '\n')
                            
                            if search_str in old_text_normalized:
                                new_text = old_text_normalized.replace(search_str, replace_str, 1)
                                success_msg = "Sukses mengganti blok kode (Exact match)."
                            else:
                                search_lines = search_str.splitlines()
                                while search_lines and not search_lines[0].strip(): search_lines.pop(0)
                                while search_lines and not search_lines[-1].strip(): search_lines.pop()
                                
                                if not search_lines:
                                    tool_outputs.append(f"[EDIT {filename}] -> Error: Teks pada <search> kosong atau tidak ditemukan.")
                                    add_notif(f"[bold #f472b6]Edit Failed:[/bold #f472b6] Search string empty in [#d1a662]{filename}[/#d1a662]")
                                    is_success = False
                                else:
                                    file_lines = old_text_normalized.splitlines()
                                    stripped_search = [l.strip() for l in search_lines]
                                    
                                    match_start = -1
                                    for i in range(len(file_lines) - len(search_lines) + 1):
                                        match = True
                                        for j in range(len(search_lines)):
                                            if file_lines[i+j].strip() != stripped_search[j]:
                                                match = False
                                                break
                                        if match:
                                            match_start = i
                                            break
                                            
                                    if match_start != -1:
                                        matched_file_lines = file_lines[match_start:match_start+len(search_lines)]
                                        file_indent = ""
                                        for line in matched_file_lines:
                                            if line.strip():
                                                file_indent = line[:len(line) - len(line.lstrip())]
                                                break
                                                
                                        search_indent = ""
                                        for line in search_lines:
                                            if line.strip():
                                                search_indent = line[:len(line) - len(line.lstrip())]
                                                break
                                                
                                        replace_lines = replace_str.splitlines()
                                        while replace_lines and not replace_lines[0].strip(): replace_lines.pop(0)
                                        while replace_lines and not replace_lines[-1].strip(): replace_lines.pop()
                                        
                                        adjusted_replace_lines = []
                                        for line in replace_lines:
                                            if line.strip() == "":
                                                adjusted_replace_lines.append("")
                                            elif line.startswith(search_indent):
                                                adjusted_replace_lines.append(file_indent + line[len(search_indent):])
                                            else:
                                                adjusted_replace_lines.append(file_indent + line.lstrip())
                                                
                                        new_file_lines = file_lines[:match_start] + adjusted_replace_lines + file_lines[match_start+len(search_lines):]
                                        new_text = '\n'.join(new_file_lines)
                                        if old_text.endswith('\n') and not new_text.endswith('\n'):
                                            new_text += '\n'
                                        success_msg = f"Sukses mengganti blok kode (Fuzzy match lines {match_start+1}-{match_start+len(search_lines)})."
                                    else:
                                        tool_outputs.append(f"[EDIT {filename}] -> Error: Teks pada <search> tidak ditemukan di dalam file secara presisi maupun fuzzy. Pastikan kamu meng-copy kode lamanya dengan benar.")
                                        add_notif(f"[bold #f472b6]Edit Failed:[/bold #f472b6] Search string not found in [#d1a662]{filename}[/#d1a662]")
                                        is_success = False

                            if is_success:
                                old_lines = old_text_normalized.splitlines()
                                new_lines = new_text.splitlines()
                                diff = list(difflib.unified_diff(
                                    old_lines, new_lines, fromfile=f"a/{filename}", tofile=f"b/{filename}", lineterm=''
                                ))
                                
                                open(filename, 'w', encoding='utf-8').write(new_text)
                                tool_outputs.append(f"[EDIT {filename}] -> {success_msg}")
                                # Catat diff untuk branch
                                added = sum(1 for l in diff if l.startswith('+') and not l.startswith('+++'))
                                removed = sum(1 for l in diff if l.startswith('-') and not l.startswith('---'))
                                preview = [l for l in diff if l.startswith(('+', '-')) and not l.startswith(('+++', '---'))][:6]
                                self._turn_file_diffs.append({"file": filename, "added": added, "removed": removed, "diff_preview": preview})
                                
                                if diff:
                                    colored_diff = format_diff_with_lines(diff)
                                    add_notif(f"[bold]File Edited:[/bold] [#d1a662]{filename}[/#d1a662]\n\n" + "\n".join(colored_diff))
                                else:
                                    add_notif(f"[bold]File Edited:[/bold] [#d1a662]{filename}[/#d1a662] [italic](No diff)[/italic]")
                                
                        except Exception as e:
                            tool_outputs.append(f"[EDIT {filename}] -> Error: {e}")
                            is_success = False
                    else:
                        start_match = READ_START_PATTERN.search(attrs)
                        end_match = READ_END_PATTERN.search(attrs)
                        if not start_match:
                            tool_outputs.append("[EDIT] -> Error: Kamu tidak menggunakan format <search> dan <replace>. Gunakan format yang benar.")
                            is_success = False
                        else:
                            start_line = int(start_match.group(1))
                            end_line = int(end_match.group(1)) if end_match else start_line
                            if start_line <= 0 or end_line < start_line:
                                tool_outputs.append(f"[EDIT {filename}] -> Error: range line tidak valid.")
                                is_success = False
                            else:
                                try:
                                    old_text = open(filename, 'r', encoding='utf-8').read()
                                    # Simpan snapshot sebelum edit untuk branch
                                    if filename not in self._pending_file_snapshot:
                                        self._pending_file_snapshot[filename] = old_text
                                    old_lines = old_text.splitlines()
                                    total_lines = len(old_lines)
                                    if start_line > total_lines:
                                        tool_outputs.append(f"[EDIT {filename}] -> Error: start line {start_line} melebihi total {total_lines}.")
                                        is_success = False
                                    else:
                                        replacement = re.sub(r'^```[a-zA-Z0-9]*\n', '', inner)
                                        replacement = re.sub(r'\n```$', '', replacement)
                                        replacement_lines = replacement.splitlines()
                                        new_lines = list(old_lines)
                                        new_lines[start_line - 1:min(end_line, total_lines)] = replacement_lines
                                        new_content = "\n".join(new_lines)
                                        if old_text.endswith("\n") or not new_content.endswith("\n"):
                                            new_content += "\n"
                                        diff = list(difflib.unified_diff(
                                            old_lines, new_content.splitlines(), fromfile=f"a/{filename}", tofile=f"b/{filename}", lineterm=''
                                        ))
                                        open(filename, 'w', encoding='utf-8').write(new_content)
                                        tool_outputs.append(f"[EDIT {filename}] -> Sukses. Lines {start_line}-{min(end_line, total_lines)} diperbarui.")
                                        # Catat diff untuk branch
                                        added = sum(1 for l in diff if l.startswith('+') and not l.startswith('+++'))
                                        removed = sum(1 for l in diff if l.startswith('-') and not l.startswith('---'))
                                        preview = [l for l in diff if l.startswith(('+', '-')) and not l.startswith(('+++', '---'))][:6]
                                        self._turn_file_diffs.append({"file": filename, "added": added, "removed": removed, "diff_preview": preview})
                                        if diff:
                                            colored_diff = []
                                            for line in diff:
                                                clean_line = line.replace('[', '\\[')
                                                clean_sub = line[1:].replace('[', '\\[') if len(line) > 1 else ""
                                                if line.startswith('+++') or line.startswith('---'): colored_diff.append(f"[bold]{clean_line}[/bold]")
                                                elif line.startswith('+'): colored_diff.append(f"[#71d1d1 on #0d1a12]+  {clean_sub}[/]")
                                                elif line.startswith('-'): colored_diff.append(f"[#f472b6 on #2a0d1a]-  {clean_sub}[/]")
                                                elif line.startswith('@@'): colored_diff.append(f"[#71d1d1]{clean_line}[/#71d1d1]")
                                                else: colored_diff.append(f"   {clean_sub}" if line.startswith(' ') else clean_line)
                                            add_notif(f"[bold]File Edited:[/bold] [#d1a662]{filename}[/#d1a662] [italic](Lines {start_line}-{min(end_line, total_lines)})[/italic]\n\n" + "\n".join(colored_diff))
                                        else:
                                            add_notif(f"[bold]File Edited:[/bold] [#d1a662]{filename}[/#d1a662] [italic](No diff)[/italic]")
                                except Exception as e:
                                    tool_outputs.append(f"[EDIT {filename}] -> Error: {e}")
                                    is_success = False

            elif tag == 'check_syntax':
                fname_match = CHECK_FILE_ATTR_PATTERN.search(attrs)
                filename = fname_match.group(1).strip() if fname_match else inner.strip()
                if not filename:
                    tool_outputs.append("[CHECK_SYNTAX] -> Error: file attribute wajib diisi.")
                    is_success = False
                elif not is_safe_path(filename):
                    tool_outputs.append(f"[CHECK_SYNTAX {filename}] -> Error: Access Denied.")
                    add_notif(f"[bold #f472b6]Access Denied:[/bold #f472b6] ({filename})")
                    is_success = False
                elif not os.path.exists(filename):
                    tool_outputs.append(f"[CHECK_SYNTAX {filename}] -> Error: File tidak ditemukan.")
                    add_notif(f"[bold #f472b6]File Not Found:[/bold #f472b6] [#d1a662]{filename}[/#d1a662]")
                    is_success = False
                else:
                    ok, result = self._check_syntax_for_file(filename)
                    if ok:
                        tool_outputs.append(f"[CHECK_SYNTAX {filename}] -> OK.\n{result}")
                        add_notif(f"[bold #71d1d1]Syntax OK:[/bold #71d1d1] [#d1a662]{filename}[/#d1a662]")
                    else:
                        tool_outputs.append(f"[CHECK_SYNTAX {filename}] -> ERROR.\n{result}")
                        add_notif(f"[bold #f472b6]Syntax Error:[/bold #f472b6] [#d1a662]{filename}[/#d1a662]\n{rich_escape(result[:600])}")
                        is_success = False

            elif tag == 'mkdir':
                path = inner.strip()
                if not is_safe_path(path):
                    is_success = False
                else:
                    try:
                        os.makedirs(path, exist_ok=True)
                        tool_outputs.append(f"[MKDIR {path}] -> Sukses.")
                        add_notif(f"[bold]Folder Created:[/bold] [#d1a662]{path}[/#d1a662]")
                    except Exception as e:
                        tool_outputs.append(f"[MKDIR {path}] -> Error: {e}")
                        is_success = False

            elif tag == 'rm':
                path = inner.strip()
                if not is_safe_path(path):
                    is_success = False
                else:
                    try:
                        if os.path.isdir(path): shutil.rmtree(path)
                        else: os.remove(path)
                        tool_outputs.append(f"[RM {path}] -> Sukses dihapus.")
                        add_notif(f"[bold #f472b6]Deleted:[/bold #f472b6] [#d1a662]{path}[/#d1a662]")
                    except Exception as e:
                        tool_outputs.append(f"[RM {path}] -> Error: {e}")
                        is_success = False


            elif tag == 'mc_connect':
                host = re.search(r"host=['\"]([^'\"]+)['\"]", attrs)
                port = re.search(r"port=['\"]([^'\"]+)['\"]", attrs)
                version = re.search(r"version=['\"]([^'\"]+)['\"]", attrs)
                username = re.search(r"username=['\"]([^'\"]+)['\"]", attrs)
                resp = self._mc_call('connect', {
                    'host': host.group(1) if host else 'localhost',
                    'port': int(port.group(1)) if port else 25565,
                    'version': version.group(1) if version else '1.21.11',
                    'username': username.group(1) if username else 'Aria',
                })
                tool_outputs.append(f"[MC_CONNECT] -> {resp}")
                add_notif("[bold #71d1d1]Minecraft connect request sent.[/bold #71d1d1]")
                is_success = bool(resp.get('ok'))

            elif tag == 'mc_chat':
                msg = inner.strip()
                resp = self._mc_call('chat', {'message': msg})
                tool_outputs.append(f"[MC_CHAT] -> {resp}")
                add_notif(f"[bold]Aria chat:[/bold] [#d1a662]{rich_escape(msg[:120])}[/#d1a662]")
                is_success = bool(resp.get('ok'))

            elif tag == 'mc_observe':
                resp = self._mc_call('observe', {})
                tool_outputs.append(f"[MC_OBSERVE] -> {json.dumps(resp, ensure_ascii=False)[:5000]}")
                add_notif("[bold]Aria observing Minecraft environment.[/bold]")
                is_success = bool(resp.get('ok'))

            elif tag == 'mc_control':
                flags = {}
                for key in ('forward','back','left','right','jump','sprint','sneak'):
                    m = re.search(rf"{key}=['\"]([^'\"]+)['\"]", attrs)
                    if m:
                        flags[key] = m.group(1).lower() in ('1','true','yes','on')
                resp = self._mc_call('control', flags)
                tool_outputs.append(f"[MC_CONTROL] -> {resp}")
                add_notif("[bold]Aria control updated.[/bold]")
                is_success = bool(resp.get('ok'))

            elif tag == 'mc_look':
                yaw_m = re.search(r"yaw=['\"]([^'\"]+)['\"]", attrs)
                pitch_m = re.search(r"pitch=['\"]([^'\"]+)['\"]", attrs)
                resp = self._mc_call('look', {
                    'yaw': float(yaw_m.group(1)) if yaw_m else 0.0,
                    'pitch': float(pitch_m.group(1)) if pitch_m else 0.0,
                    'force': True,
                })
                tool_outputs.append(f"[MC_LOOK] -> {resp}")
                add_notif("[bold]Aria look direction changed.[/bold]")
                is_success = bool(resp.get('ok'))

            elif tag == 'mc_stop':
                resp = self._mc_call('stop', {})
                tool_outputs.append(f"[MC_STOP] -> {resp}")
                add_notif("[bold]Aria movement stopped.[/bold]")
                is_success = bool(resp.get('ok'))
            elif tag == 'mc_inventory':
                resp = self._mc_call('inventory', {})
                tool_outputs.append(f"[MC_INVENTORY] -> {json.dumps(resp, ensure_ascii=False)[:5000]}")
                add_notif("[bold]Aria inventory snapshot fetched.[/bold]")
                is_success = bool(resp.get('ok'))

            elif tag == 'mc_events':
                lm = re.search(r"limit=['\"]([^'\"]+)['\"]", attrs)
                limit = int(lm.group(1)) if lm else 50
                resp = self._mc_call('events', {'limit': limit})
                tool_outputs.append(f"[MC_EVENTS] -> {json.dumps(resp, ensure_ascii=False)[:5000]}")
                add_notif("[bold]Aria event stream fetched.[/bold]")
                is_success = bool(resp.get('ok'))

            elif tag == 'mc_act':
                km = re.search(r"kind=['\"]([^'\"]+)['\"]", attrs)
                kind = km.group(1) if km else inner.strip()
                payload = {'kind': kind}
                for key in ('itemName','destination','maxDistance'):
                    m = re.search(rf"{key}=['\"]([^'\"]+)['\"]", attrs)
                    if m:
                        payload[key] = m.group(1)
                resp = self._mc_call('act', payload)
                tool_outputs.append(f"[MC_ACT {kind}] -> {resp}")
                add_notif(f"[bold]Aria mc_act:[/bold] [#d1a662]{rich_escape(kind)}[/#d1a662]")
                is_success = bool(resp.get('ok'))


            elif tag == 'mc_move':
                x = re.search(r"x=['\"]([^'\"]+)['\"]", attrs)
                y = re.search(r"y=['\"]([^'\"]+)['\"]", attrs)
                z = re.search(r"z=['\"]([^'\"]+)['\"]", attrs)
                rg = re.search(r"range=['\"]([^'\"]+)['\"]", attrs)
                if not (x and y and z):
                    tool_outputs.append("[MC_MOVE] -> {'ok': False, 'error': 'x/y/z required'}")
                    is_success = False
                else:
                    resp = self._mc_call('move_to', {'x': float(x.group(1)), 'y': float(y.group(1)), 'z': float(z.group(1)), 'range': float(rg.group(1)) if rg else 1})
                    tool_outputs.append(f"[MC_MOVE] -> {resp}")
                    add_notif("[bold]Aria pathfinding to target.[/bold]")
                    is_success = bool(resp.get('ok'))

            elif tag == 'mc_follow':
                um = re.search(r"username=['\"]([^'\"]+)['\"]", attrs)
                username = um.group(1) if um else inner.strip()
                rg = re.search(r"range=['\"]([^'\"]+)['\"]", attrs)
                resp = self._mc_call('follow', {'username': username, 'range': float(rg.group(1)) if rg else 2})
                tool_outputs.append(f"[MC_FOLLOW] -> {resp}")
                add_notif(f"[bold]Aria following:[/bold] [#d1a662]{rich_escape(username)}[/#d1a662]")
                is_success = bool(resp.get('ok'))

            elif tag == 'mc_policy':
                payload = {}
                for key in ('autoCombat','autoEat','followPlayer'):
                    m = re.search(rf"{key}=['\"]([^'\"]+)['\"]", attrs)
                    if m:
                        if key in ('autoCombat','autoEat'):
                            payload[key] = m.group(1).lower() in ('1','true','yes','on')
                        else:
                            payload[key] = m.group(1)
                resp = self._mc_call('set_policy', payload)
                tool_outputs.append(f"[MC_POLICY] -> {resp}")
                add_notif("[bold]Aria policy updated.[/bold]")
                is_success = bool(resp.get('ok'))

            elif tag == 'mc_tick':
                resp = self._mc_call('autonomy_tick', {})
                tool_outputs.append(f"[MC_TICK] -> {resp}")
                add_notif("[bold]Aria autonomy tick executed.[/bold]")
                is_success = bool(resp.get('ok'))

            elif tag == 'mc_goal':
                gm = re.search(r"goal=['\"]([^'\"]+)['\"]", attrs)
                goal_name = gm.group(1) if gm else inner.strip() or 'survive'
                resp = self._mc_call('set_goal', {'goal': goal_name})
                tool_outputs.append(f"[MC_GOAL] -> {resp}")
                add_notif(f"[bold]Aria strategic goal:[/bold] [#d1a662]{rich_escape(goal_name)}[/#d1a662]")
                is_success = bool(resp.get('ok'))

            elif tag == 'mc_strategy_tick':
                resp = self._mc_call('strategic_tick', {})
                tool_outputs.append(f"[MC_STRATEGY_TICK] -> {json.dumps(resp, ensure_ascii=False)[:5000]}")
                add_notif("[bold]Aria strategic tick executed.[/bold]")
                is_success = bool(resp.get('ok'))

            elif tag in ('search', 'search_workspace'):
                query = inner.strip().strip("'").strip('"'); res = f"[SEARCH_WORKSPACE '{query}'] ->\n"
                try:
                    import re
                    try:
                        pattern = re.compile(query)
                    except re.error:
                        pattern = re.compile(re.escape(query))
                    results = []
                    for root, dirs, files in os.walk("."):
                        dirs[:] = [d for d in dirs if d not in {".git", "__pycache__", "venv", "node_modules", ".pytest_cache", "build", "dist", ".gemini"}]
                        for file in files:
                            fp = os.path.join(root, file)
                            try:
                                for i, line in enumerate(open(fp, "r", encoding="utf-8")):
                                    if pattern.search(line): results.append(f"{fp}:{i+1}: {line.strip()}")
                            except: pass
                    res += "\n".join(results[:50]) if results else "Not Found."
                    tool_outputs.append(res); add_notif(f"[bold]Search Workspace:[/bold] [#d1a662]{query}[/#d1a662]")
                except Exception as e:
                    tool_outputs.append(f"Error: {e}")
                    is_success = False

            elif tag == 'fetch_url':
                url = inner.strip()
                try:
                    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
                    html = urllib.request.urlopen(req, timeout=10).read().decode('utf-8')
                    txt = re.sub(r'\s+', ' ', re.sub(r'<[^>]+>', ' ', html))[:3000]
                    tool_outputs.append(f"[FETCH] ->\n{txt}"); add_notif(f"[bold]Web Fetched:[/bold] [#71d1d1]{url}[/#71d1d1]")
                except Exception as e:
                    tool_outputs.append(f"Error: {e}")
                    is_success = False

            elif tag == 'web_search':
                query = inner.strip()
                res = self._search_tavily(query)
                tool_outputs.append(f"[WEB_SEARCH '{query}'] ->\n{res}")
                add_notif(f"Aria Searching Web: `{query}`")

            elif tag == 'search_image':
                path = inner.strip().strip("'").strip('"')
                
                mode_match = re.search(r'mode\s*=\s*["\']([^"\']+)["\']', attrs, re.IGNORECASE)
                img_mode = mode_match.group(1).strip().lower() if mode_match else ""
                
                query_match = re.search(r'query\s*=\s*["\']([^"\']+)["\']', attrs, re.IGNORECASE)
                img_query = query_match.group(1).strip() if query_match else ""
                
                is_url = path.startswith("http://") or path.startswith("https://")
                abs_path = path if is_url else os.path.abspath(path)
                
                temp_file_path = None
                try:
                    if is_url:
                        try:
                            import tempfile, urllib.request, shutil
                            add_notif(f"[bold]Aria Downloading Image:[/bold] [#d1a662]{path}[/#d1a662]")
                            temp_fd, temp_file_path = tempfile.mkstemp(suffix=".jpg")
                            os.close(temp_fd)
                            req = urllib.request.Request(path, headers={'User-Agent': 'Mozilla/5.0'})
                            with urllib.request.urlopen(req, timeout=15) as response, open(temp_file_path, 'wb') as out_file:
                                shutil.copyfileobj(response, out_file)
                            abs_path = temp_file_path
                        except Exception as e:
                            tool_outputs.append(f"[SEARCH_IMAGE {path}] -> Error saat mendownload gambar: {e}")
                            is_success = False

                    if not is_success:
                        pass
                    elif not os.path.exists(abs_path):
                        tool_outputs.append(f"[SEARCH_IMAGE {path}] -> Error: File tidak ditemukan di sistem ({abs_path}). Pastikan path valid.")
                        is_success = False
                    elif not img_mode:
                        tool_outputs.append(f"[SEARCH_IMAGE {path}] -> Error: Atribut mode wajib disertakan (mode=\"serpapi\" atau mode=\"anime\").")
                        is_success = False
                    else:
                        try:
                            import urllib.request, urllib.parse, json
                            import requests
                            
                            if img_mode == "serpapi":
                                add_notif(f"[bold]Aria Searching Web Image:[/bold] [#d1a662]{path}[/#d1a662]")
                                
                                serpapi_key = self.config.get("serpapi_key") or ""
                                if not serpapi_key:
                                    tool_outputs.append(f"[SEARCH_IMAGE mode='serpapi'] -> Error: API Key SerpApi belum diatur. Silakan isi 'serpapi_key' di config.json terlebih dahulu.")
                                    is_success = False
                                else:
                                    try:
                                        target_url = path
                                        if not is_url:
                                            add_notif(f"[bold]Mengunggah gambar ke server...[/bold]")
                                            with open(abs_path, "rb") as f:
                                                upload_res = requests.post("https://uguu.se/upload.php", files={"files[]": f}, timeout=30)
                                            
                                            if upload_res.status_code == 200:
                                                upload_data = upload_res.json()
                                                if upload_data.get("success"):
                                                    target_url = upload_data["files"][0]["url"]
                                                else:
                                                    raise Exception(f"Gagal mengunggah: {upload_data}")
                                            else:
                                                raise Exception(f"Gagal mengunggah gambar ke server sementara: {upload_res.status_code}")
                                                
                                        add_notif(f"[bold]Mencari melalui SerpApi...[/bold]")
                                        params = {
                                            "engine": "google_lens",
                                            "url": target_url,
                                            "api_key": serpapi_key,
                                            "no_cache": "true"
                                        }
                                        
                                        self.llm._emit_debug("SERPAPI IMAGE URL", f"Image hosted at: {target_url}")
                                        search_res = requests.get("https://serpapi.com/search", params=params, timeout=30)
                                        
                                        if search_res.status_code != 200:
                                            tool_outputs.append(f"[SEARCH_IMAGE mode='serpapi'] -> Error HTTP {search_res.status_code}: {search_res.text[:100]}")
                                            is_success = False
                                        else:
                                            data = search_res.json()
                                            if "error" in data:
                                                if "hasn't returned any results" in data['error']:
                                                    tool_outputs.append(f"[SEARCH_IMAGE mode='serpapi'] -> SerpApi merespons: Google Lens tidak menemukan hasil yang cocok di web.")
                                                else:
                                                    tool_outputs.append(f"[SEARCH_IMAGE mode='serpapi'] -> Error dari SerpApi: {data['error']}")
                                                    is_success = False
                                            else:
                                                visual_matches = data.get("visual_matches", [])
                                                if not visual_matches:
                                                    tool_outputs.append(f"[SEARCH_IMAGE mode='serpapi'] -> Tidak ditemukan kecocokan visual di Google Lens (SerpApi).")
                                                else:
                                                    output_lines = [f"[SEARCH_IMAGE mode='serpapi'] -> Menemukan {len(visual_matches)} kecocokan:"]
                                                    for i, res in enumerate(visual_matches[:5]):
                                                        title = res.get('title', 'Tanpa Judul')
                                                        link = res.get('link', '')
                                                        source = res.get('source', '')
                                                        output_lines.append(f"{i+1}. {title} ({source}) - {link}")
                                                    tool_outputs.append("\n".join(output_lines))
                                                
                                    except Exception as e:
                                        tool_outputs.append(f"[SEARCH_IMAGE mode='serpapi'] -> Error memanggil API: {e}")
                                        is_success = False
                                    
                            elif img_mode == "anime":
                                add_notif(f"[bold]Aria Searching Anime Scene:[/bold] [#d1a662]{path}[/#d1a662]")
                                with open(abs_path, "rb") as f:
                                    res = requests.post("https://api.trace.moe/search", files={"image": f}, timeout=20)
                                    data = res.json()
                                    if data.get("error"):
                                        tool_outputs.append(f"[SEARCH_IMAGE] -> Error API: {data['error']}")
                                        is_success = False
                                    else:
                                        results = data.get("result", [])
                                        if not results:
                                            tool_outputs.append(f"[SEARCH_IMAGE mode='anime'] -> Tidak ditemukan kecocokan anime di database trace.moe.")
                                        else:
                                            best = results[0]
                                            similarity = best.get('similarity', 0) * 100
                                            anilist_id = best.get('anilist', 'Unknown')
                                            episode = best.get('episode', 'Unknown')

                                            anime_title = f"AniList ID: {anilist_id}"
                                            try:
                                                al_query = 'query ($id: Int) { Media (id: $id, type: ANIME) { title { romaji english native } } }'
                                                al_res = requests.post('https://graphql.anilist.co', json={'query': al_query, 'variables': {'id': anilist_id}}, timeout=10).json()
                                                title_data = al_res['data']['Media']['title']
                                                anime_title = title_data.get('romaji') or title_data.get('english') or title_data.get('native') or anime_title
                                            except: pass
                                            tool_outputs.append(f"[SEARCH_IMAGE mode='anime'] -> Ketemu!\nJudul Anime: {anime_title}\nEpisode: {episode}\nKemiripan: {similarity:.2f}%")
                        except Exception as e:
                            tool_outputs.append(f"[SEARCH_IMAGE] -> Error: {e}")
                            is_success = False
                finally:
                    if temp_file_path and os.path.exists(temp_file_path):
                        try:
                            os.remove(temp_file_path)
                        except:
                            pass

            elif tag == 'github_issue':
                repo_name = re.search(r'repo\s*=\s*["\']([^"\']+)["\']', attrs, re.IGNORECASE)
                action_match = re.search(r'action\s*=\s*["\']([^"\']+)["\']', attrs, re.IGNORECASE)
                num_match = re.search(r'number\s*=\s*["\'](\d+)["\']', attrs, re.IGNORECASE)
                
                repo_str = repo_name.group(1) if repo_name else ""
                action = action_match.group(1).lower() if action_match else "list"
                token = self.config.get("github_oauth_token")
                
                if not token:
                    tool_outputs.append("[GITHUB_ISSUE] -> Error: Belum login. Silakan ketik /github login.")
                    is_success = False
                elif not repo_str:
                    tool_outputs.append("[GITHUB_ISSUE] -> Error: Atribut 'repo' wajib diisi.")
                    is_success = False
                else:
                    try:
                        from github import Github
                        g = Github(token)
                        repo = g.get_repo(repo_str)
                        if action == "list":
                            add_notif(f"[bold]GitHub:[/bold] Listing issues in [#d1a662]{repo_str}[/#d1a662]")
                            issues = repo.get_issues(state='open')
                            lines = [f"[GITHUB_ISSUE list {repo_str}] ->"]
                            for iss in issues[:10]:
                                lines.append(f"#{iss.number}: {iss.title} (oleh {iss.user.login})")
                            tool_outputs.append("\n".join(lines) if len(lines) > 1 else "Tidak ada issue terbuka.")
                        elif action == "create":
                            title = inner.split('\n')[0][:100]
                            body = inner.split('\n', 1)[1] if '\n' in inner else inner
                            add_notif(f"[bold]GitHub:[/bold] Creating issue in [#d1a662]{repo_str}[/#d1a662]")
                            new_issue = repo.create_issue(title=title, body=body)
                            tool_outputs.append(f"[GITHUB_ISSUE create] -> Berhasil membuat issue #{new_issue.number}: {new_issue.html_url}")
                        elif action == "get":
                            num = int(num_match.group(1)) if num_match else None
                            if not num: raise ValueError("Atribut 'number' wajib.")
                            add_notif(f"[bold]GitHub:[/bold] Fetching issue [#d1a662]#{num}[/#d1a662]")
                            iss = repo.get_issue(num)
                            comments = [f"- {c.user.login}: {c.body[:200]}..." for c in iss.get_comments()]
                            c_str = "\n".join(comments) if comments else "Tidak ada komentar."
                            tool_outputs.append(f"[GITHUB_ISSUE get #{num}] ->\nTitle: {iss.title}\nState: {iss.state}\nBody:\n{iss.body}\n\nComments:\n{c_str}")
                        elif action == "comment":
                            num = int(num_match.group(1)) if num_match else None
                            if not num: raise ValueError("Atribut 'number' wajib.")
                            add_notif(f"[bold]GitHub:[/bold] Adding comment to issue [#d1a662]#{num}[/#d1a662]")
                            iss = repo.get_issue(num)
                            iss.create_comment(inner.strip())
                            tool_outputs.append(f"[GITHUB_ISSUE comment] -> Berhasil mengirim komentar ke issue #{num}.")
                        elif action == "label":
                            num = int(num_match.group(1)) if num_match else None
                            if not num: raise ValueError("Atribut 'number' wajib.")
                            labels = [l.strip() for l in inner.strip().split(',') if l.strip()]
                            add_notif(f"[bold]GitHub:[/bold] Adding labels {labels} to issue [#d1a662]#{num}[/#d1a662]")
                            iss = repo.get_issue(num)
                            iss.add_to_labels(*labels)
                            tool_outputs.append(f"[GITHUB_ISSUE label] -> Label {labels} ditambahkan ke issue #{num}.")
                        elif action == "close":
                            num = int(num_match.group(1)) if num_match else None
                            if not num: raise ValueError("Atribut 'number' wajib.")
                            add_notif(f"[bold]GitHub:[/bold] Closing issue [#d1a662]#{num}[/#d1a662]")
                            iss = repo.get_issue(num)
                            iss.edit(state="closed")
                            tool_outputs.append(f"[GITHUB_ISSUE close] -> Issue #{num} berhasil ditutup.")
                    except Exception as e:
                        err_msg = str(e)
                        if "401" in err_msg or "Bad credentials" in err_msg: 
                            from aria.core.config import save_config
                            import requests
                            client_id = self.config.get("github_client_id")
                            client_secret = self.config.get("github_client_secret")
                            refresh_token = self.config.get("github_refresh_token")
                            
                            if refresh_token and client_id and client_secret:
                                add_notif("[italic #7b6b9a]Mencoba refresh token Github secara otomatis...[/italic #7b6b9a]")
                                try:
                                    t_res = requests.post("https://github.com/login/oauth/access_token",
                                                        data={"client_id": client_id, "client_secret": client_secret, 
                                                              "refresh_token": refresh_token, "grant_type": "refresh_token"},
                                                        headers={"Accept": "application/json"}, timeout=15)
                                    t_data = t_res.json()
                                    if "access_token" in t_data:
                                        self.config["github_oauth_token"] = t_data["access_token"]
                                        if "refresh_token" in t_data:
                                            self.config["github_refresh_token"] = t_data["refresh_token"]
                                        save_config(self.config)
                                        err_msg = "Token expired tapi berhasil di-refresh otomatis. Silakan ulangi instruksi sebelumnya."
                                    else:
                                        err_msg = "Gagal refresh token otomatis. Silakan ketik /github login lagi."
                                except Exception:
                                    err_msg = "Gagal refresh token otomatis. Silakan ketik /github login lagi."
                            else:
                                err_msg = "Token kadaluarsa. (Untuk auto-refresh, isi 'github_client_secret' di config). Ketik /github login."
                        tool_outputs.append(f"[GITHUB_ISSUE] -> Error: {err_msg}")
                        is_success = False

            elif tag == 'github_pr':
                repo_name = re.search(r'repo\s*=\s*["\']([^"\']+)["\']', attrs, re.IGNORECASE)
                action_match = re.search(r'action\s*=\s*["\']([^"\']+)["\']', attrs, re.IGNORECASE)
                num_match = re.search(r'number\s*=\s*["\'](\d+)["\']', attrs, re.IGNORECASE)
                title_match = re.search(r'title\s*=\s*["\']([^"\']+)["\']', attrs, re.IGNORECASE)
                head_match = re.search(r'head\s*=\s*["\']([^"\']+)["\']', attrs, re.IGNORECASE)
                base_match = re.search(r'base\s*=\s*["\']([^"\']+)["\']', attrs, re.IGNORECASE)
                
                repo_str = repo_name.group(1) if repo_name else ""
                action = action_match.group(1).lower() if action_match else "list"
                token = self.config.get("github_oauth_token")
                
                if not token:
                    tool_outputs.append("[GITHUB_PR] -> Error: Belum login.")
                    is_success = False
                elif not repo_str:
                    tool_outputs.append("[GITHUB_PR] -> Error: Atribut 'repo' wajib.")
                    is_success = False
                else:
                    try:
                        from github import Github
                        g = Github(token)
                        repo = g.get_repo(repo_str)
                        if action == "list":
                            add_notif(f"[bold]GitHub:[/bold] Listing PRs in [#d1a662]{repo_str}[/#d1a662]")
                            pulls = repo.get_pulls(state='open')
                            lines = [f"[GITHUB_PR list {repo_str}] ->"]
                            for pr in pulls[:10]:
                                lines.append(f"#{pr.number}: {pr.title} ({pr.head.ref} -> {pr.base.ref})")
                            tool_outputs.append("\n".join(lines) if len(lines) > 1 else "Tidak ada PR terbuka.")
                        elif action == "create":
                            title = title_match.group(1) if title_match else "New Pull Request"
                            head = head_match.group(1) if head_match else ""
                            base = base_match.group(1) if base_match else "main"
                            if not head: raise ValueError("Atribut 'head' wajib untuk create PR.")
                            add_notif(f"[bold #71d1d1]GitHub:[/bold #71d1d1] Creating PR in [#d1a662]{repo_str}[/#d1a662] ({head} -> {base})")
                            pr = repo.create_pull(title=title, body=inner.strip(), head=head, base=base)
                            tool_outputs.append(f"[GITHUB_PR create] -> Berhasil membuat PR #{pr.number}: {pr.html_url}")
                        elif action == "get":
                            num = int(num_match.group(1)) if num_match else None
                            if not num: raise ValueError("Atribut 'number' wajib.")
                            add_notif(f"[bold]GitHub:[/bold] Fetching PR [#d1a662]#{num}[/#d1a662]")
                            pr = repo.get_pull(num)
                            comments = [f"- {c.user.login}: {c.body[:200]}..." for c in pr.get_issue_comments()]
                            c_str = "\n".join(comments) if comments else "Tidak ada komentar."
                            tool_outputs.append(f"[GITHUB_PR get #{num}] ->\nTitle: {pr.title}\nState: {pr.state}\nMergeable: {pr.mergeable}\nBody:\n{pr.body}\n\nComments:\n{c_str}")
                        elif action == "get_diff":
                            num = int(num_match.group(1)) if num_match else None
                            if not num: raise ValueError("Atribut 'number' wajib.")
                            add_notif(f"[bold]GitHub:[/bold] Fetching diff for PR [#d1a662]#{num}[/#d1a662]")
                            pr = repo.get_pull(num)
                            import requests
                            api_url = f"https://api.github.com/repos/{repo_str}/pulls/{num}"
                            diff_res = requests.get(
                                api_url,
                                headers={
                                    "Authorization": f"Bearer {token}",
                                    "Accept": "application/vnd.github.v3.diff"
                                },
                                timeout=20
                            )
                            if diff_res.status_code == 200:
                                diff_txt = diff_res.text[:5000]
                            else:
                                diff_txt = f"Gagal mendapatkan diff (Status {diff_res.status_code}): {diff_res.text[:200]}"
                            tool_outputs.append(f"[GITHUB_PR diff #{num}] ->\n{diff_txt}")
                        elif action == "review":
                            num = int(num_match.group(1)) if num_match else None
                            if not num: raise ValueError("Atribut 'number' wajib.")
                            add_notif(f"[bold]GitHub:[/bold] Submitting review to PR [#d1a662]#{num}[/#d1a662]")
                            pr = repo.get_pull(num)
                            pr.create_review(body=inner.strip(), event="COMMENT")
                            tool_outputs.append(f"[GITHUB_PR review] -> Review dikirim ke PR #{num}.")
                        elif action == "approve":
                            num = int(num_match.group(1)) if num_match else None
                            if not num: raise ValueError("Atribut 'number' wajib.")
                            add_notif(f"[bold #71d1d1]GitHub:[/bold #71d1d1] Approving PR [#d1a662]#{num}[/#d1a662]")
                            pr = repo.get_pull(num)
                            pr.create_review(body="Approved by Aria Assist Code", event="APPROVE")
                            tool_outputs.append(f"[GITHUB_PR approve] -> PR #{num} disetujui.")
                        elif action == "merge":
                            num = int(num_match.group(1)) if num_match else None
                            if not num: raise ValueError("Atribut 'number' wajib.")
                            add_notif(f"[bold #71d1d1]GitHub:[/bold #71d1d1] Merging PR [#d1a662]#{num}[/#d1a662]")
                            pr = repo.get_pull(num)
                            status = pr.merge()
                            tool_outputs.append(f"[GITHUB_PR merge] -> PR #{num} " + ("berhasil di-merge." if status.merged else f"gagal di-merge: {status.message}"))
                        elif action == "close":
                            num = int(num_match.group(1)) if num_match else None
                            if not num: raise ValueError("Atribut 'number' wajib.")
                            add_notif(f"[bold #f472b6]GitHub:[/bold #f472b6] Closing PR [#d1a662]#{num}[/#d1a662]")
                            pr = repo.get_pull(num)
                            pr.edit(state="closed")
                            tool_outputs.append(f"[GITHUB_PR close] -> PR #{num} ditutup.")
                    except Exception as e:
                        err_msg = str(e)
                        if "401" in err_msg or "Bad credentials" in err_msg: 
                            from aria.core.config import save_config
                            import requests
                            client_id = self.config.get("github_client_id")
                            client_secret = self.config.get("github_client_secret")
                            refresh_token = self.config.get("github_refresh_token")
                            
                            if refresh_token and client_id and client_secret:
                                add_notif("[italic #7b6b9a]Mencoba refresh token Github secara otomatis...[/italic #7b6b9a]")
                                try:
                                    t_res = requests.post("https://github.com/login/oauth/access_token",
                                                        data={"client_id": client_id, "client_secret": client_secret, 
                                                              "refresh_token": refresh_token, "grant_type": "refresh_token"},
                                                        headers={"Accept": "application/json"}, timeout=15)
                                    t_data = t_res.json()
                                    if "access_token" in t_data:
                                        self.config["github_oauth_token"] = t_data["access_token"]
                                        if "refresh_token" in t_data:
                                            self.config["github_refresh_token"] = t_data["refresh_token"]
                                        save_config(self.config)
                                        err_msg = "Token expired tapi berhasil di-refresh otomatis. Silakan ulangi instruksi sebelumnya."
                                    else:
                                        err_msg = "Gagal refresh token otomatis. Silakan ketik /github login lagi."
                                except Exception:
                                    err_msg = "Gagal refresh token otomatis. Silakan ketik /github login lagi."
                            else:
                                err_msg = "Token kadaluarsa. (Untuk auto-refresh, isi 'github_client_secret' di config). Ketik /github login."
                        tool_outputs.append(f"[GITHUB_PR] -> Error: {err_msg}")
                        is_success = False

            elif tag == 'github_actions':
                repo_name = re.search(r'repo\s*=\s*["\']([^"\']+)["\']', attrs, re.IGNORECASE)
                action_match = re.search(r'action\s*=\s*["\']([^"\']+)["\']', attrs, re.IGNORECASE)
                run_match = re.search(r'run_id\s*=\s*["\'](\d+)["\']', attrs, re.IGNORECASE)
                workflow_match = re.search(r'workflow_id\s*=\s*["\']([^"\']+)["\']', attrs, re.IGNORECASE)
                ref_match = re.search(r'ref\s*=\s*["\']([^"\']+)["\']', attrs, re.IGNORECASE)
                repo_str = repo_name.group(1) if repo_name else ""
                action = action_match.group(1).lower() if action_match else "list_runs"
                token = self.config.get("github_oauth_token")
                if not token:
                    tool_outputs.append("[GITHUB_ACTIONS] -> Error: Belum login.")
                    is_success = False
                else:
                    try:
                        from github import Github
                        g = Github(token)
                        repo = g.get_repo(repo_str)
                        if action == "list_runs":
                            runs = repo.get_workflow_runs()
                            lines = [f"[GITHUB_ACTIONS list {repo_str}] ->"]
                            for r in runs[:8]:
                                status_emoji = "✓" if r.conclusion == "success" else "✗" if r.conclusion == "failure" else "..."
                                lines.append(f"{status_emoji} ID:{r.id} - {r.display_title} ({r.status})")
                            tool_outputs.append("\n".join(lines))
                        elif action == "get_log":
                            rid = int(run_match.group(1)) if run_match else None
                            if not rid: raise ValueError("run_id wajib.")
                            add_notif(f"[bold]GitHub:[/bold] Fetching logs for run [#d1a662]{rid}[/#d1a662]")
                            import requests
                            log_res = requests.get(f"https://api.github.com/repos/{repo_str}/actions/runs/{rid}/logs", headers={"Authorization": f"token {token}"}, timeout=20)
                            tool_outputs.append(f"[GITHUB_ACTIONS log {rid}] -> Log URL: https://github.com/{repo_str}/actions/runs/{rid}/logs")
                        elif action == "trigger":
                            workflow_id = workflow_match.group(1) if workflow_match else None
                            ref = ref_match.group(1) if ref_match else "main"
                            if not workflow_id: raise ValueError("workflow_id wajib.")
                            add_notif(f"[bold #71d1d1]GitHub:[/bold #71d1d1] Triggering workflow [#d1a662]{workflow_id}[/#d1a662] on {ref}")
                            workflow = repo.get_workflow(workflow_id)
                            success = workflow.create_dispatch(ref)
                            if success:
                                tool_outputs.append(f"[GITHUB_ACTIONS trigger] -> Berhasil memicu workflow {workflow_id} pada branch {ref}.")
                            else:
                                tool_outputs.append(f"[GITHUB_ACTIONS trigger] -> Gagal memicu workflow {workflow_id}.")
                    except Exception as e:
                        tool_outputs.append(f"[GITHUB_ACTIONS] -> Error: {e}")
                        is_success = False

            elif tag == 'github_repo':
                repo_match = re.search(r'repo\s*=\s*["\']([^"\']+)["\']', attrs, re.IGNORECASE)
                action_match = re.search(r'action\s*=\s*["\']([^"\']+)["\']', attrs, re.IGNORECASE)
                branch_match = re.search(r'branch\s*=\s*["\']([^"\']+)["\']', attrs, re.IGNORECASE)
                base_match = re.search(r'base\s*=\s*["\']([^"\']+)["\']', attrs, re.IGNORECASE)
                
                repo_str = repo_match.group(1) if repo_match else ""
                action = (action_match.group(1).lower() if action_match else "get_info")
                
                token = self.config.get("github_oauth_token")
                if not token:
                    tool_outputs.append("[GITHUB_REPO] -> Error: Belum login.")
                    is_success = False
                else:
                    try:
                        from github import Github
                        g = Github(token)
                        if action == "list":
                            add_notif(f"[bold]GitHub:[/bold] Fetching repository list...")
                            user = g.get_user()
                            repos = user.get_repos()
                            lines = [f"[GITHUB_REPO list] -> Terhubung sebagai: {user.login}"]
                            for r in repos[:15]:
                                lines.append(f"- {r.full_name} ({r.stargazers_count} stars)")
                            tool_outputs.append("\n".join(lines))
                        elif action == "create":
                            add_notif(f"[bold #71d1d1]GitHub:[/bold #71d1d1] Creating new repository [#d1a662]{repo_str}[/#d1a662]")
                            new_repo = g.get_user().create_repo(repo_str)
                            tool_outputs.append(f"[GITHUB_REPO create] -> Berhasil: {new_repo.html_url}")
                        elif action == "fork":
                            add_notif(f"[bold #71d1d1]GitHub:[/bold #71d1d1] Forking [#d1a662]{repo_str}[/#d1a662]")
                            repo = g.get_repo(repo_str)
                            forked = g.get_user().create_fork(repo)
                            tool_outputs.append(f"[GITHUB_REPO fork] -> Berhasil mem-fork ke: {forked.html_url}")
                        elif action == "get_info":
                            add_notif(f"[bold]GitHub:[/bold] Fetching info for [#d1a662]{repo_str}[/#d1a662]")
                            repo = g.get_repo(repo_str)
                            info = f"Repo: {repo.full_name}\nDesc: {repo.description}\nStars: {repo.stargazers_count} | Forks: {repo.forks_count}\nLang: {repo.language}"
                            tool_outputs.append(f"[GITHUB_REPO info] ->\n{info}")
                        elif action == "list_branches":
                            add_notif(f"[bold]GitHub:[/bold] Listing branches for [#d1a662]{repo_str}[/#d1a662]")
                            repo = g.get_repo(repo_str)
                            branches = repo.get_branches()
                            lines = [f"[GITHUB_REPO list_branches {repo_str}] ->"]
                            for b in branches[:30]:
                                lines.append(f"- {b.name}")
                            tool_outputs.append("\n".join(lines))
                        elif action == "list_commits":
                            b_name = branch_match.group(1) if branch_match else "main"
                            add_notif(f"[bold]GitHub:[/bold] Fetching commits for [#d1a662]{repo_str}[/#d1a662] on branch {b_name}")
                            repo = g.get_repo(repo_str)
                            commits = repo.get_commits(sha=b_name)
                            lines = [f"[GITHUB_REPO list_commits {repo_str} ({b_name})] ->"]
                            for c in list(commits)[:15]:
                                lines.append(f"- {c.sha[:7]}: {c.commit.message.splitlines()[0]} ({c.commit.author.name})")
                            tool_outputs.append("\n".join(lines))
                        elif action == "create_branch":
                            b_name = branch_match.group(1) if branch_match else ""
                            base_name = base_match.group(1) if base_match else "main"
                            if not b_name: raise ValueError("Atribut 'branch' wajib untuk create_branch.")
                            add_notif(f"[bold #71d1d1]GitHub:[/bold #71d1d1] Creating branch [#d1a662]{b_name}[/#d1a662] in {repo_str}")
                            repo = g.get_repo(repo_str)
                            source = repo.get_branch(base_name)
                            repo.create_git_ref(ref=f"refs/heads/{b_name}", sha=source.commit.sha)
                            tool_outputs.append(f"[GITHUB_REPO create_branch] -> Branch {b_name} dibuat dari {base_name}.")
                        elif action == "delete_branch":
                            b_name = branch_match.group(1) if branch_match else ""
                            if not b_name: raise ValueError("Atribut 'branch' wajib untuk delete_branch.")
                            add_notif(f"[bold #f472b6]GitHub:[/bold #f472b6] Deleting branch [#d1a662]{b_name}[/#d1a662] in {repo_str}")
                            repo = g.get_repo(repo_str)
                            ref = repo.get_git_ref(f"heads/{b_name}")
                            ref.delete()
                            tool_outputs.append(f"[GITHUB_REPO delete_branch] -> Branch {b_name} telah dihapus.")
                        elif action == "delete":
                            add_notif(f"[bold #f472b6]GitHub:[/bold #f472b6] DELETING REPOSITORY [#d1a662]{repo_str}[/#d1a662]")
                            repo = g.get_repo(repo_str)
                            repo.delete()
                            tool_outputs.append(f"[GITHUB_REPO delete] -> Repo {repo_str} telah dihapus.")
                    except Exception as e:
                        err_msg = str(e)
                        if "401" in err_msg or "Bad credentials" in err_msg: 
                            from aria.core.config import save_config
                            import requests
                            client_id = self.config.get("github_client_id")
                            client_secret = self.config.get("github_client_secret")
                            refresh_token = self.config.get("github_refresh_token")
                            
                            if refresh_token and client_id and client_secret:
                                add_notif("[italic #7b6b9a]Mencoba refresh token Github secara otomatis...[/italic #7b6b9a]")
                                try:
                                    t_res = requests.post("https://github.com/login/oauth/access_token",
                                                        data={"client_id": client_id, "client_secret": client_secret, 
                                                              "refresh_token": refresh_token, "grant_type": "refresh_token"},
                                                        headers={"Accept": "application/json"}, timeout=15)
                                    t_data = t_res.json()
                                    if "access_token" in t_data:
                                        self.config["github_oauth_token"] = t_data["access_token"]
                                        if "refresh_token" in t_data:
                                            self.config["github_refresh_token"] = t_data["refresh_token"]
                                        save_config(self.config)
                                        err_msg = "Token expired tapi berhasil di-refresh otomatis. Ulangi toolnya!"
                                    else:
                                        err_msg = "Gagal refresh token otomatis. Silakan ketik /github login lagi."
                                except Exception:
                                    err_msg = "Gagal refresh token otomatis. Silakan ketik /github login lagi."
                            else:
                                err_msg = "Token kadaluarsa. (Untuk auto-refresh, isi 'github_client_secret' di config). Ketik /github login."
                        tool_outputs.append(f"[GITHUB_REPO] -> Error: {err_msg}")
                        is_success = False

            elif tag == 'github_file':
                repo_match = re.search(r'repo\s*=\s*["\']([^"\']+)["\']', attrs, re.IGNORECASE)
                path_match = re.search(r'path\s*=\s*["\']([^"\']+)["\']', attrs, re.IGNORECASE)
                action_match = re.search(r'action\s*=\s*["\']([^"\']+)["\']', attrs, re.IGNORECASE)
                branch_match = re.search(r'branch\s*=\s*["\']([^"\']+)["\']', attrs, re.IGNORECASE)
                msg_match = re.search(r'message\s*=\s*["\']([^"\']+)["\']', attrs, re.IGNORECASE)
                local_path_match = re.search(r'local_path\s*=\s*["\']([^"\']+)["\']', attrs, re.IGNORECASE)

                repo_str = repo_match.group(1) if repo_match else ""
                path_str = path_match.group(1) if path_match else ""
                action = (action_match.group(1).lower() if action_match else "read")
                branch = (branch_match.group(1) if branch_match else "main")
                msg = (msg_match.group(1) if msg_match else "Aria Assist Code update")
                local_path = local_path_match.group(1) if local_path_match else ""

                token = self.config.get("github_oauth_token")
                if not token:
                    tool_outputs.append("[GITHUB_FILE] -> Error: Belum login.")
                    is_success = False
                else:
                    try:
                        from github import Github
                        g = Github(token)
                        repo = g.get_repo(repo_str)
                        if action == "read":
                            add_notif(f"[bold]GitHub:[/bold] Reading cloud file [#d1a662]{path_str}[/#d1a662]")
                            content = repo.get_contents(path_str, ref=branch)
                            tool_outputs.append(f"[GITHUB_FILE read {path_str}] ->\n{content.decoded_content.decode('utf-8')}")
                        elif action == "list_dir":
                            add_notif(f"[bold]GitHub:[/bold] Listing cloud directory [#d1a662]{path_str}[/#d1a662]")
                            contents = repo.get_contents(path_str, ref=branch)
                            if not isinstance(contents, list):
                                contents = [contents]
                            lines = [f"[GITHUB_FILE list_dir {path_str} ({branch})] ->"]
                            for c in contents:
                                lines.append(f"- {c.path} ({c.type})")
                            tool_outputs.append("\n".join(lines))
                        elif action == "write":
                            add_notif(f"[bold #71d1d1]GitHub:[/bold #71d1d1] Committing to [#d1a662]{path_str}[/#d1a662] ([italic]{branch}[/italic])")
                            try:
                                contents = repo.get_contents(path_str, ref=branch)
                                repo.update_file(contents.path, msg, inner.strip(), contents.sha, branch=branch)
                                tool_outputs.append(f"[GITHUB_FILE write] -> Berhasil memperbarui {path_str} di branch {branch}.")
                            except:
                                repo.create_file(path_str, msg, inner.strip(), branch=branch)
                                tool_outputs.append(f"[GITHUB_FILE write] -> Berhasil membuat file baru {path_str} di branch {branch}.")
                        elif action == "push_local":
                            if not local_path: raise ValueError("Atribut 'local_path' wajib untuk action push_local.")
                            if not os.path.exists(local_path): raise ValueError(f"Path lokal tidak ditemukan: {local_path}")
                            
                            if os.path.isfile(local_path):
                                with open(local_path, "r", encoding="utf-8") as f:
                                    local_content = f.read()
                                add_notif(f"[bold #71d1d1]GitHub:[/bold #71d1d1] Pushing local file [#d1a662]{local_path}[/#d1a662] to [#d1a662]{path_str}[/#d1a662] ([italic]{branch}[/italic])")
                                try:
                                    contents = repo.get_contents(path_str, ref=branch)
                                    repo.update_file(contents.path, msg, local_content, contents.sha, branch=branch)
                                    tool_outputs.append(f"[GITHUB_FILE push_local] -> Berhasil memperbarui file {path_str}.")
                                except:
                                    repo.create_file(path_str, msg, local_content, branch=branch)
                                    tool_outputs.append(f"[GITHUB_FILE push_local] -> Berhasil membuat file {path_str}.")
                            elif os.path.isdir(local_path):
                                add_notif(f"[bold #71d1d1]GitHub:[/bold #71d1d1] Pushing local directory [#d1a662]{local_path}[/#d1a662] to [#d1a662]{path_str}[/#d1a662] ([italic]{branch}[/italic])")
                                
                                files_to_push = []
                                for root, _, files in os.walk(local_path):
                                    for file in files:
                                        if file.startswith('.') or file.endswith(('.png', '.jpg', '.jpeg', '.gif', '.pyc', '.exe', '.zip', '.tar', '.gz')): continue
                                        files_to_push.append(os.path.join(root, file))
                                
                                total_files = len(files_to_push)
                                if total_files == 0:
                                    tool_outputs.append(f"[GITHUB_FILE push_local] -> Warning: Tidak ada file valid yang bisa diunggah di folder {local_path}.")
                                else:
                                    add_notif(f"Menghitung {total_files} file...")
                                    pushed_count = 0
                                    
                                    for i, file_local_path in enumerate(files_to_push):
                                        rel_path = os.path.relpath(file_local_path, local_path)
                                        target_path = os.path.join(path_str, rel_path).replace("\\", "/")
                                        
                                        # Render Progress Bar (Seamless Slim Line)
                                        p_val = (i + 1) / total_files
                                        perc = int(p_val * 100)
                                        bar_len = 30
                                        filled = int(p_val * bar_len)
                                        bar = f"[#d1a662]{'━' * filled}[/#d1a662][#3d2d5a]{'─' * (bar_len - filled)}[/#3d2d5a]"
                                        update_last_notif(f"[bold #87c095]{i+1}/{total_files}[/bold #87c095] {bar} [bold #87c095]{perc}%[/bold #87c095]\n[#7b6b9a]Uploading: {target_path}[/#7b6b9a]")
                                        
                                        try:
                                            with open(file_local_path, "r", encoding="utf-8") as f:
                                                content = f.read()
                                            try:
                                                contents = repo.get_contents(target_path, ref=branch)
                                                repo.update_file(contents.path, msg, content, contents.sha, branch=branch)
                                            except:
                                                repo.create_file(target_path, msg, content, branch=branch)
                                            pushed_count += 1
                                        except Exception as sub_e:
                                            tool_outputs.append(f"[GITHUB_FILE push_local] -> Warning: Gagal mengunggah {file_local_path}: {sub_e}")
                                            
                                    final_bar = f"[#d1a662]{'━' * 30}[/#d1a662]"
                                    update_last_notif(f"[bold #87c095]{total_files}/{total_files}[/bold #87c095] {final_bar} [bold #87c095]100%[/bold #87c095]\n[#7b6b9a]Selesai mengunggah {pushed_count} file.[/#7b6b9a]")
                                    tool_outputs.append(f"[GITHUB_FILE push_local] -> Selesai mengunggah {pushed_count} file dari folder {local_path}.")                        
                        elif action == "delete":
                            add_notif(f"[bold #f472b6]GitHub:[/bold #f472b6] Deleting cloud file [#d1a662]{path_str}[/#d1a662]")
                            contents = repo.get_contents(path_str, ref=branch)
                            repo.delete_file(contents.path, msg, contents.sha, branch=branch)
                            tool_outputs.append(f"[GITHUB_FILE delete] -> {path_str} berhasil dihapus.")
                    except Exception as e:
                        tool_outputs.append(f"[GITHUB_FILE] -> Error: {e}")
                        is_success = False

            elif tag == 'github_search':
                query_match = re.search(r'query\s*=\s*["\']([^"\']+)["\']', attrs, re.IGNORECASE)
                stype_match = re.search(r'type\s*=\s*["\']([^"\']+)["\']', attrs, re.IGNORECASE)

                query = query_match.group(1) if query_match else ""
                stype = (stype_match.group(1).lower() if stype_match else "code")
                
                token = self.config.get("github_oauth_token")
                if not token:
                    tool_outputs.append("[GITHUB_SEARCH] -> Error: Belum login.")
                    is_success = False
                else:
                    try:
                        from github import Github
                        g = Github(token)
                        if stype == "repo":
                            add_notif(f"[bold]GitHub Search:[/bold] Finding repos matching '[#d1a662]{query}[/#d1a662]'")
                            res = g.search_repositories(query)
                            lines = [f"[GITHUB_SEARCH repo '{query}'] ->"]
                            for r in res[:8]: lines.append(f"- {r.full_name} ({r.stargazers_count} stars)")
                            tool_outputs.append("\n".join(lines))
                        elif stype == "code":
                            add_notif(f"[bold]GitHub Search:[/bold] Finding code matching '[#d1a662]{query}[/#d1a662]'")
                            res = g.search_code(query)
                            lines = [f"[GITHUB_SEARCH code '{query}'] ->"]
                            for c in res[:8]: lines.append(f"- {c.repository.full_name}: {c.path}")
                            tool_outputs.append("\n".join(lines))
                    except Exception as e:
                        err_msg = str(e)
                        if "401" in err_msg or "Bad credentials" in err_msg: 
                            from aria.core.config import save_config
                            import requests
                            client_id = self.config.get("github_client_id")
                            client_secret = self.config.get("github_client_secret")
                            refresh_token = self.config.get("github_refresh_token")

                            if refresh_token and client_id and client_secret:
                                add_notif("[italic #7b6b9a]Mencoba refresh token Github secara otomatis...[/italic #7b6b9a]")
                                try:
                                    t_res = requests.post("https://github.com/login/oauth/access_token",
                                                        data={"client_id": client_id, "client_secret": client_secret, 
                                                              "refresh_token": refresh_token, "grant_type": "refresh_token"},
                                                        headers={"Accept": "application/json"}, timeout=15)
                                    t_data = t_res.json()
                                    if "access_token" in t_data:
                                        self.config["github_oauth_token"] = t_data["access_token"]
                                        if "refresh_token" in t_data:
                                            self.config["github_refresh_token"] = t_data["refresh_token"]
                                        save_config(self.config)
                                        err_msg = "Token expired tapi berhasil di-refresh otomatis. Silakan ulangi instruksi sebelumnya."
                                    else:
                                        err_msg = "Gagal refresh token otomatis. Silakan ketik /github login lagi."
                                except Exception:
                                    err_msg = "Gagal refresh token otomatis. Silakan ketik /github login lagi."
                            else:
                                err_msg = "Token kadaluarsa. (Untuk auto-refresh, isi 'github_client_secret' di config). Ketik /github login."
                        tool_outputs.append(f"[GITHUB_FILE] -> Error: {err_msg}")
                        is_success = False

            elif tag in ['run_cmd', 'runcmd']:
                import re
                cmd = inner.strip()

                timeout_val = 60.0
                if attrs:
                    m_timeout = re.search(r'timeout\s*=\s*["\']?(\d+)["\']?', attrs, re.IGNORECASE)
                    if m_timeout:
                        try: timeout_val = float(m_timeout.group(1))
                        except: pass                
                self.process_header = f"[bold #71d1d1]▶ Shell:[/bold #71d1d1] [#d1a662]{rich_escape(cmd)}[/#d1a662]\n"
                self.process_out_lines = []
                
                prefix_ui = "".join(ui_pieces)
                running_tag = self._decorate_tool_tags_with_status(full_tag, "running")
                suffix_ui = text[end:]
                
                def update_live_ui():
                    display_lines = "".join([f"[#71d1d1]{rich_escape(t)}[/#71d1d1]" if u else rich_escape(t) for t, u in self.process_out_lines[-30:]])
                    base_notifs = "\n\n".join(current_notifs)
                    live_shell_notif = self.process_header + display_lines
                    final_notif = base_notifs + ("\n\n" if base_notifs else "") + live_shell_notif
                    current_ui = prefix_ui + running_tag + f"<ui_notif>{final_notif}</ui_notif>" + suffix_ui
                    self.call_from_thread(lambda ui=current_ui: resp_widget.update_content(ui))
                    self.call_from_thread(lambda: self.query_one("#chat-log").scroll_end(animate=False))

                self._live_ui_updater = update_live_ui
                
                env = os.environ.copy()
                env["PYTHONUNBUFFERED"] = "1" 
                
                import shlex
                try:
                    parsed_cmd = shlex.split(cmd, posix=(os.name != "nt"))
                    if not parsed_cmd:
                        raise ValueError("Command kosong")
                    
                    process = subprocess.Popen(
                        parsed_cmd, shell=False, 
                        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, 
                        text=True, bufsize=1, errors='replace', env=env
                    )
                    self.active_process = process
                    
                    def set_terminal_title():
                        ib = self.query_one("#input-box")
                        ib.border_title = "[Terminal] Ketik argumen lalu tekan Enter..."
                        ib.styles.border_title_color = "#d1a662"
                    self.call_from_thread(set_terminal_title)
                    
                    def kill_process():
                        if process.poll() is None: 
                            process.kill()
                            self.process_out_lines.append(("\n[SYSTEM: Proses dihentikan paksa (Limit 60 detik)]", False))
                            
                    timer = threading.Timer(60.0, kill_process); timer.start()
                    
                    current_line = ""
                    last_proc_ui_update = 0.0
                    while True:
                        chunk = process.stdout.read(64)
                        if not chunk and process.poll() is not None:
                            break
                        if chunk:
                            current_line += chunk
                            while True:
                                split_idx = current_line.find("\n")
                                if split_idx == -1:
                                    break
                                self.process_out_lines.append((current_line[:split_idx + 1], False))
                                current_line = current_line[split_idx + 1:]
                            if current_line.endswith(": ") or current_line.endswith("? ") or current_line.endswith("> "):
                                self.process_out_lines.append((current_line, False))
                                current_line = ""
                            now = time.time()
                            if now - last_proc_ui_update >= 0.08:
                                update_live_ui()
                                last_proc_ui_update = now

                    if current_line:
                        self.process_out_lines.append((current_line, False))
                    
                    timer.cancel(); process.wait()
                    self.active_process = None
                    
                    def reset_terminal_title():
                        ib = self.query_one("#input-box")
                        ib.border_title = "Ketik pesan untuk Aria..."
                        ib.styles.border_title_color = "#7b6b9a"
                    self.call_from_thread(reset_terminal_title)
                    
                    full_out_sys = "".join([t for t, u in self.process_out_lines])
                    full_out_sys = full_out_sys[:2000] + ("\n...[TRUNCATED]" if len(full_out_sys) > 2000 else "")
                    if not full_out_sys.strip(): full_out_sys = "[Selesai tanpa output]"
                    
                    full_out_ui = "".join([f"[#71d1d1]{rich_escape(t)}[/#71d1d1]" if u else rich_escape(t) for t, u in self.process_out_lines])
                    add_notif(self.process_header + full_out_ui)
                    
                    tool_outputs.append(f"[RUN_CMD '{cmd}'] ->\n{full_out_sys}")
                except Exception as e:
                    self.active_process = None
                    tool_outputs.append(f"[RUN_CMD '{cmd}'] -> Error: {e}")
                    add_notif(self.process_header + f"[bold #f472b6]Error: {e}[/bold #f472b6]")
                    is_success = False

            if tag in ('write', 'edit') and is_success:
                # Jangan tambahkan decorated_tag (stream lama) agar digantikan dengan diff.
                pass
            else:
                decorated_tag = self._decorate_tool_tags_with_status(full_tag, "success" if is_success else "error")
                ui_pieces.append(decorated_tag)
                
            if current_notifs:
                combined_notifs = "\n\n".join(current_notifs)
                ui_pieces.append(f"<ui_notif>{combined_notifs}</ui_notif>")
            
            last_idx = end

            if not is_success:
                tool_outputs.append(f"\n[SYSTEM: Proses sekuensial dihentikan karena tool <{tag}> mengalami error.]")
                break

        tail_text = text[last_idx:].lstrip('\n')
        ui_pieces.append(tail_text)
        full_combined_text = "".join(ui_pieces).strip()

        return tool_outputs, full_combined_text
