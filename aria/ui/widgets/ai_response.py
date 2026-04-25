import re

from rich import box
from rich.console import Group
from rich.markup import escape as rich_escape
from rich.table import Table
from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Static

from aria.core.runtime import THINKING_PHRASE_SWAP_EVERY, THINKING_SHIMMER_INTERVAL, THINKING_SHIMMER_STEP
from aria.utils.text import LIST_BULLET_PATTERN, LIST_NUM_PATTERN, SYSTEM_OBSERVATION_PATTERN, TOOL_OPEN_PATTERN

class AriaApp:
    USER_STREAM_INTERVAL = 0.02

class AIResponse(Horizontal):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._segment_widgets = []; self._segment_layout = []
        self._last_signature = None
        self._thinking_timer = None
        self._thinking_frame = 0
        self._thinking_phrase_index = 0
        self._thinking_visible_chars = 0
        self._thinking_active = False
        self._thinking_pending_render = False
        self._content_animation_timer = None
        self._content_animation_target = ""
        self._content_animation_visible = ""
        self._thinking_phrases = [
            "Aria lagi ngerapihin pikiran...",
            "Lagi negosiasi sama otak.",
            "Menata jawaban agar estetik.",
            "Mikir caranya berpikir.",
            "Lagi milih kata yang pas.",
            "Aria baru bangun, tunggu ya.",
            "Sedang memproses ide.",
            "Menata jawaban, tunggu ya.",
        ]

    def compose(self) -> ComposeResult:
        yield Static("◈  ", classes="ai-icon")
        self.msg_content = Vertical(classes="ai-content")
        yield self.msg_content

    def on_mount(self) -> None:
        if self._thinking_active or self._thinking_pending_render:
            self._render_thinking_placeholder()

    def start_thinking_placeholder(self) -> None:
        if self._thinking_active:
            return
        self._thinking_active = True
        self._thinking_pending_render = True
        self._thinking_frame = 0
        self._thinking_visible_chars = 0
        if self._thinking_timer is None:
            self._thinking_timer = self.set_interval(THINKING_SHIMMER_INTERVAL, self._tick_thinking_placeholder)
        if hasattr(self, "msg_content"):
            self._render_thinking_placeholder()

    def stop_thinking_placeholder(self) -> None:
        self._thinking_active = False
        if self._thinking_timer is not None:
            self._thinking_timer.stop()
            self._thinking_timer = None

    def _tick_thinking_placeholder(self) -> None:
        if not self._thinking_active:
            return
        self._thinking_frame += THINKING_SHIMMER_STEP
        if self._thinking_frame % THINKING_PHRASE_SWAP_EVERY == 0:
            self._thinking_phrase_index = (self._thinking_phrase_index + 1) % len(self._thinking_phrases)
            self._thinking_visible_chars = 0
        phrase = self._get_thinking_phrase()
        step = self._stream_reveal_step(len(phrase))
        self._thinking_visible_chars = min(len(phrase), self._thinking_visible_chars + step)
        self._render_thinking_placeholder()

    def _stream_reveal_step(self, total_chars: int) -> int:
        if total_chars > 160:
            return 4
        if total_chars > 80:
            return 3
        return 2

    def animate_content_to(self, text: str) -> None:
        self.stop_thinking_placeholder()
        target = text or ""
        if target == self._content_animation_target and self._content_animation_timer is not None:
            return
        if not target:
            self.stop_content_animation()
            self.update_content("")
            return
        if len(self._content_animation_visible) > len(target):
            self._content_animation_visible = target
        self._content_animation_target = target
        if self._content_animation_timer is None:
            self._content_animation_timer = self.set_interval(AriaApp.USER_STREAM_INTERVAL, self._tick_content_animation)
        self._tick_content_animation()

    def stop_content_animation(self) -> None:
        if self._content_animation_timer is not None:
            self._content_animation_timer.stop()
            self._content_animation_timer = None

    def finalize_animated_content(self, text: str) -> None:
        self._content_animation_target = text or ""
        self._content_animation_visible = self._content_animation_target
        self.stop_content_animation()
        self.update_content(self._content_animation_visible)

    def _tick_content_animation(self) -> None:
        target = self._content_animation_target
        visible = self._content_animation_visible
        if not target:
            self.stop_content_animation()
            return
        if len(visible) >= len(target):
            self.stop_content_animation()
            self.update_content(target)
            return
        gap = len(target) - len(visible)
        if gap > 200:
            step = gap // 4
        elif gap > 50:
            step = max(8, gap // 8)
        else:
            step = self._stream_reveal_step(len(target))
        next_visible = target[:min(len(target), len(visible) + step)]
        self._content_animation_visible = next_visible
        self.update_content(next_visible)
        if len(next_visible) >= len(target):
            self.stop_content_animation()

    def _render_shimmer_text(self, text: str, frame: int) -> str:
        if not text:
            return ""
        width = 8
        cycle = len(text) + width + 6
        pos = frame % cycle - width
        parts = []
        for idx, ch in enumerate(text):
            dist = abs(idx - pos)
            if dist <= 1:
                color = "#f0e6ff"
            elif dist <= 3:
                color = "#c97fd4"
            elif dist <= 5:
                color = "#9d8ec0"
            else:
                color = "#7b6b9a"
            parts.append(f"[{color}]{rich_escape(ch)}[/{color}]")
        return "".join(parts)

    def _render_thinking_placeholder(self) -> None:
        if not hasattr(self, "msg_content"):
            return
        
        phrase = self._get_thinking_phrase()
        visible_phrase = phrase[:self._thinking_visible_chars] if self._thinking_visible_chars else ""
             
        if len(visible_phrase) < len(phrase):
            shimmer = f"[#7b6b9a]{rich_escape(visible_phrase)}[/#7b6b9a]"
        else:
            shimmer = self._render_shimmer_text(visible_phrase, self._thinking_frame)
            
        self._thinking_pending_render = False
        self._last_signature = ("thinking", self._thinking_phrase_index, self._thinking_frame)
        if self._segment_layout != [("thinking", "")]:
            self.msg_content.remove_children()
            widget = Static("", classes="thinking-placeholder", markup=True)
            self.msg_content.mount(widget)
            self._segment_widgets = [widget]
            self._segment_layout = [("thinking", "")]
        self._segment_widgets[0].update(shimmer)

    def _get_thinking_phrase(self) -> str:
        if getattr(self.app.llm, "is_waiting_rate_limit", False):
            return "Menunggu Limit... (Kapasitas penuh, Aria sedang istirahat sejenak)"
        return self._thinking_phrases[self._thinking_phrase_index]

    def _inline_to_rich(self, text: str) -> str:
        if "Runtime LLM Error:" in text:
            return rich_escape(text)

        placeholders = []
        
        def shield_code(m):
            code_content = m.group(1) if m.group(1) is not None else m.group(2)
            safe_code = code_content.replace("\\", "\\\\").replace("[", "\\[")
            placeholders.append(f"[#d1a662]{safe_code}[/#d1a662]")
            return f"\x01{len(placeholders)-1}\x01"

        text = re.sub(r'``(.*?)``|`([^`]+)`', shield_code, text)
        
        safe = text.replace("\\", "\\\\").replace("[", "\\[")
        safe = safe.replace("\\\\rightarrow", "→").replace("\\\\to", "→").replace("->", "→")
        safe = safe.replace("\\\\Rightarrow", "⇒").replace("\\\\leftarrow", "←").replace("<-", "←")
        safe = safe.replace("\\\\Leftarrow", "⇐").replace("\\\\leftrightarrow", "↔").replace("<->", "↔")
        safe = re.sub(r'(?<!-)->(?!>)', "→", safe)
        safe = re.sub(r'(?<!=)=>(?!>)', "⇒", safe)
        safe = re.sub(r'(?<!\*)\*\*\*(.+?)\*\*\*(?!\*)', r'[bold italic]\1[/bold italic]', safe)
        safe = re.sub(r'(?<!\*)\*\*(.+?)\*\*(?!\*)', r'[bold]\1[/bold]', safe)
        safe = re.sub(r'(?<!\*)\*(.+?)\*(?!\*)', r'[italic]\1[/italic]', safe)
        safe = re.sub(r'(?<!\w)___(.+?)___(?!\w)', r'[bold italic]\1[/bold italic]', safe)
        safe = re.sub(r'(?<!\w)__(.+?)__(?!\w)', r'[bold]\1[/bold]', safe)
        safe = re.sub(r'(?<!\w)_([^_]+?)_(?!\w)', r'[italic]\1[/italic]', safe)
        safe = re.sub(r'~~(.+?)~~', r'[strike]\1[/strike]', safe)
        
        for i, val in enumerate(placeholders):
            safe = safe.replace(f"\x01{i}\x01", val)
            
        return safe

    def _parse_stream_segments(self, text: str) -> list[tuple[str, str, str]]:
        segments = []
        i = 0
        n = len(text)
        
        def tool_title(tag: str, attrs: str, inner: str) -> str:
            t = tag.lower().replace("runcmd", "run_cmd")
            status_match = re.search(r'status\s*=\s*"([^"]+)"', attrs or "", flags=re.IGNORECASE)
            status_value = status_match.group(1).lower() if status_match else "pending"
            
            if status_value == "success": status_label = "[bold #87c095]✓[/bold #87c095]"
            elif status_value == "error": status_label = "[bold #f472b6]✗[/bold #f472b6]"
            elif status_value == "denied": status_label = "[bold #f472b6]✗ (Izin ditolak)[/bold #f472b6]"
            else: status_label = "[bold #7b6b9a]...[/bold #7b6b9a]"

            t_formatted = " ".join(word.capitalize() for word in t.split("_"))
            return f"[bold #d1a662]{t_formatted}[/bold #d1a662] {status_label}"

        current_text = ""
        
        while i < n:
            md_block_match = re.search(r'```', text[i:])
            md_inline_match = re.search(r'`', text[i:])
            tool_match = TOOL_OPEN_PATTERN.search(text[i:])
            obs_match = SYSTEM_OBSERVATION_PATTERN.search(text[i:])
            notif_match = re.search(r'<ui_notif>\n*(.*?)\n*</ui_notif>', text[i:], re.DOTALL)
            
            candidates = []
            if md_block_match: candidates.append((i + md_block_match.start(), "md_block", md_block_match))
            if md_inline_match: candidates.append((i + md_inline_match.start(), "md_inline", md_inline_match))
            if tool_match: candidates.append((i + tool_match.start(), "tool", tool_match))
            if obs_match: candidates.append((i + obs_match.start(), "obs", obs_match))
            if notif_match: candidates.append((i + notif_match.start(), "notif", notif_match))
            
            if not candidates:
                current_text += text[i:]
                break
                
            candidates.sort(key=lambda x: x[0])
            open_idx, kind, match = candidates[0]
            
            if kind == "md_inline" and text[open_idx:open_idx+3] == "```":
                kind = "md_block"
                
            current_text += text[i:open_idx]
            
            if kind == "md_block":
                if current_text:
                    segments.append(("text", current_text, ""))
                    current_text = ""
                lang_end = text.find("\n", open_idx + 3)
                if lang_end == -1:
                    segments.append(("text", text[open_idx:], ""))
                    break
                language = text[open_idx + 3:lang_end].strip()
                close_idx = text.find("```", lang_end + 1)
                if close_idx == -1:
                    segments.append(("code", text[lang_end + 1:], language))
                    break
                segments.append(("code", text[lang_end + 1:close_idx], language))
                i = close_idx + 3
                
            elif kind == "md_inline":
                close_idx = text.find("`", open_idx + 1)
                if close_idx == -1:
                    current_text += "`"
                    i = open_idx + 1
                else:
                    current_text += text[open_idx:close_idx+1]
                    i = close_idx + 1
                    
            elif kind == "obs":
                if current_text:
                    segments.append(("text", current_text, ""))
                    current_text = ""
                segments.append(("obs", match.group(0), ""))
                i = open_idx + len(match.group(0))
                
            elif kind == "notif":
                if current_text:
                    segments.append(("text", current_text, ""))
                    current_text = ""
                segments.append(("notif", match.group(1), ""))
                i = open_idx + len(match.group(0))
                
            elif kind == "tool":
                tag_start = open_idx
                line_start = text.rfind("\n", 0, tag_start) + 1
                before_tag_on_line = text[line_start:tag_start]
                if before_tag_on_line.strip():
                    current_text += match.group(0)
                    i = open_idx + len(match.group(0))
                    continue
                    
                if current_text:
                    segments.append(("text", current_text, ""))
                    current_text = ""
                    
                tag = match.group("tag")
                attrs = match.group("attrs") or ""
                after_open = open_idx + len(match.group(0))
                
                close_match = re.search(rf'</{re.escape(tag)}>', text[after_open:], flags=re.IGNORECASE)
                if close_match:
                    inner_end = after_open + close_match.start()
                    inner = text[after_open:inner_end]
                    i = after_open + close_match.end()
                else:
                    inner = text[after_open:]
                    i = n

                body = ""
                if tag.lower() == "write":
                    body_content = re.sub(r'^```[a-zA-Z0-9]*\n', '', inner)
                    body_content = re.sub(r'\n```$', '', body_content)
                    if body_content.strip(): body = f"\n{body_content}"
                elif tag.lower() == "edit":
                    edit_m = re.search(r'<search>\n*(.*?)\n*</search>\s*<replace>\n*(.*?)\n*</replace>', inner, re.DOTALL | re.IGNORECASE)
                    if edit_m:
                        body = f"\n\n[SEARCH]\n{edit_m.group(1).strip()}\n\n[REPLACE]\n{edit_m.group(2).strip()}"
                    else:
                        body = f"\n\n{inner.strip()}" if inner.strip() else ""
                elif tag.lower() in ("run_cmd", "runcmd") and inner.strip():
                    body = f"\n{inner.strip()}"
                
                segments.append(("tool", f"{tool_title(tag, attrs, inner)}{body}", ""))

        if current_text:
            segments.append(("text", current_text, ""))

        merged = []
        for skind, scontent, slang in segments:
            if merged and merged[-1][0] == "text" and skind == "text":
                merged[-1] = ("text", merged[-1][1] + scontent, "")
            elif merged and merged[-1][0] == "tool" and skind == "notif":
                # Gabungkan notif ke dalam tool-box yang sama
                merged[-1] = ("tool", f"{merged[-1][1]}\n\n[#7b6b9a]{scontent}[/#7b6b9a]", "")
            else: merged.append((skind, scontent, slang))
        
        final = []
        for j, (skind, scontent, slang) in enumerate(merged):
            if skind == "text" and not scontent.strip():
                if j > 0 and j + 1 < len(merged):
                    if merged[j-1][0] != "text" and merged[j+1][0] != "text":
                        continue
            final.append((skind, scontent, slang))
        return final

    def _split_markdown_table_row(self, line: str) -> list[str] | None:
        stripped = line.strip()
        if "|" not in stripped:
            return None
        if stripped.startswith("|"):
            stripped = stripped[1:]
        if stripped.endswith("|"):
            stripped = stripped[:-1]
        cells = [cell.strip() for cell in stripped.split("|")]
        if len(cells) < 2 or any(cell == "" for cell in cells):
            return None
        return cells

    def _is_markdown_table_separator(self, line: str, expected_cols: int) -> bool:
        cells = self._split_markdown_table_row(line)
        if not cells or len(cells) != expected_cols:
            return False
        for cell in cells:
            compact = cell.replace(" ", "")
            if not re.fullmatch(r":?-{3,}:?", compact):
                return False
        return True

    def _extract_markdown_table(self, lines: list[str], start: int):
        if start + 1 >= len(lines):
            return None
        header = self._split_markdown_table_row(lines[start])
        if not header:
            return None
        if not self._is_markdown_table_separator(lines[start + 1], len(header)):
            return None

        alignments = []
        for cell in self._split_markdown_table_row(lines[start + 1]) or []:
            compact = cell.replace(" ", "")
            if compact.startswith(":") and compact.endswith(":"):
                alignments.append("center")
            elif compact.endswith(":"):
                alignments.append("right")
            else:
                alignments.append("left")

        rows = []
        cursor = start + 2
        while cursor < len(lines):
            row = self._split_markdown_table_row(lines[cursor])
            if not row or len(row) != len(header):
                break
            rows.append(row)
            cursor += 1

        if not rows:
            return None
        return header, alignments, rows, cursor

    def _render_markdown_table(self, header: list[str], alignments: list[str], rows: list[list[str]]):
        table = Table(
            box=box.SQUARE,
            show_header=True,
            show_edge=True,
            pad_edge=True,
            expand=False,
            padding=(0, 1),
            header_style="#d1a662 bold",
            border_style="#7b6b9a",
        )
        for heading, align in zip(header, alignments):
            table.add_column(header=Text.from_markup(self._inline_to_rich(heading)), justify=align, style="#c6bbd8")
        for row in rows:
            table.add_row(*[Text.from_markup(self._inline_to_rich(cell)) for cell in row])
        return table

    def update_content(self, text: str) -> None:
        if self._thinking_active:
            self.stop_thinking_placeholder()
        
        is_error = "Runtime LLM Error:" in text
        segments = [(k, c, l) for k, c, l in self._parse_stream_segments(text) if k in ("code", "obs", "notif") or c.strip() or c == "\n"]
        signature = tuple(segments)
        if getattr(self, "_last_signature", None) == signature: return
        self._last_signature = signature

        next_layout = [(k, l) for k, _, l in segments]
        if next_layout != self._segment_layout:
            self.msg_content.remove_children()
            self._segment_widgets = []; self._segment_layout = next_layout
            for k, _, _ in segments:
                if k == "text": widget = Static("", markup=True)
                elif k in ("notif", "tool", "obs"): widget = Static("", classes="tool-box", markup=True)
                else: widget = Static("", classes="tool-box", markup=False)
                self.msg_content.mount(widget)
                self._segment_widgets.append(widget)

        for idx, (kind, content, language) in enumerate(segments):
            widget = self._segment_widgets[idx]
            clean_content = content
            if kind == "text":
                if idx + 1 < len(segments) and segments[idx + 1][0] in ("code", "tool", "obs"): clean_content = clean_content.rstrip("\n")
                if idx > 0 and segments[idx - 1][0] in ("code", "tool", "obs"): clean_content = clean_content.lstrip("\n")
                widget.display = bool(clean_content.strip())
            elif kind in ("code", "tool", "obs") and idx == len(segments) - 1: clean_content = clean_content.rstrip("\n")

            if not widget.display:
                continue

            if kind == "code" and language: widget.update(f"[{rich_escape(language)}]\n{clean_content}")
            elif kind == "obs": widget.update(clean_content) # Markup hasil tool
            elif kind == "notif": widget.update(clean_content)
            elif kind in ("code", "tool"): widget.update(clean_content)
            else:
                if not clean_content.strip() and clean_content != "\n":
                    widget.display = False
                    continue
                lines = clean_content.split("\n"); renderables = []; prev_was_list = False
                i = 0
                while i < len(lines):
                    line = lines[i]
                    stripped = line.strip()
                    if not is_error:
                        table_block = self._extract_markdown_table(lines, i)
                        if table_block is not None:
                            header, alignments, rows, next_index = table_block
                            renderables.append(self._render_markdown_table(header, alignments, rows))
                            prev_was_list = False
                            if next_index < len(lines) and lines[next_index].strip() != "":
                                renderables.append("")
                            i = next_index
                            continue
                    m_num = LIST_NUM_PATTERN.match(stripped)
                    m_bullet = LIST_BULLET_PATTERN.match(stripped)
                    is_list_item = bool(m_num) or bool(m_bullet)
                    
                    if stripped == "" and prev_was_list:
                        next_stripped = lines[i + 1].strip() if i + 1 < len(lines) else ""
                        if bool(LIST_NUM_PATTERN.match(next_stripped)) or bool(LIST_BULLET_PATTERN.match(next_stripped)):
                            prev_was_list = False; continue  
                        else: renderables.append(""); prev_was_list = False; continue

                    if is_error:
                        renderables.append(Text(line, style="#f472b6"))
                    else:
                        header_match = re.match(r'^(\s{0,3})(#{1,6})\s+(.*)', line)
                        if header_match:
                            spaces, hashes, content = header_match.groups()
                            level = len(hashes)
                            rich_content = self._inline_to_rich(content)
                            if level == 1: renderables.append(Text.from_markup(f"{spaces}[bold underline]{rich_content}[/bold underline]"))
                            elif level == 2: renderables.append(Text.from_markup(f"{spaces}[bold underline]{rich_content}[/bold underline]"))
                            elif level >= 3: renderables.append(Text.from_markup(f"{spaces}[bold]{rich_content}[/bold]"))
                        elif line.lstrip().startswith("> "):
                            indent_str = line[:len(line) - len(line.lstrip())]
                            content = line.lstrip()[2:]
                            grid = Table.grid(padding=(0, 1))
                            grid.add_column()
                            grid.add_column()
                            grid.add_row(Text(indent_str + "┃", style="#7b6b9a"), Text.from_markup(f"[italic]{self._inline_to_rich(content)}[/italic]", style="#7b6b9a"))
                            renderables.append(grid)
                        elif is_list_item:
                            indent_len = len(line) - len(line.lstrip())
                            m = m_num or m_bullet
                            marker_raw = m.group(0)
                            marker_text = "•" if m_bullet else marker_raw.strip()
                            content_text = line[line.find(marker_raw) + len(marker_raw):].lstrip()
                            
                            grid = Table.grid(padding=(0, 1))
                            grid.add_column(width=4 + indent_len, justify="right")
                            grid.add_column()
                            grid.add_row(Text(marker_text, style="#c6bbd8"), Text.from_markup(self._inline_to_rich(content_text)))
                            renderables.append(grid)
                        elif line.startswith(" ") and stripped != "":
                            indent_len = len(line) - len(line.lstrip())
                            grid = Table.grid(padding=(0, 1))
                            grid.add_column(width=4 + (indent_len if indent_len > 2 else indent_len))
                            grid.add_column()
                            grid.add_row("", Text.from_markup(self._inline_to_rich(line.lstrip())))
                            renderables.append(grid)
                        else: 
                            renderables.append(Text.from_markup(self._inline_to_rich(line)))

                    if is_list_item:
                        next_stripped = lines[i + 1].strip() if i + 1 < len(lines) else ""
                        if not (bool(LIST_NUM_PATTERN.match(next_stripped)) or bool(LIST_BULLET_PATTERN.match(next_stripped))) and next_stripped != "":
                            renderables.append("")  
                    prev_was_list = is_list_item
                    i += 1
                widget.update(Group(*renderables))
