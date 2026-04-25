from textual import events
from textual.binding import Binding
from textual.widgets import TextArea

class ChatInput(TextArea):
    BINDINGS = [
        Binding("enter", "submit_message", "Kirim", priority=True),
        Binding("shift+enter", "insert_newline", "Baris Baru", priority=True),
        Binding("ctrl+n", "insert_newline", "Baris Baru (Alternatif)", priority=True),
        Binding("up", "suggest_up", "Naik", priority=True),
        Binding("down", "suggest_down", "Turun", priority=True),
        Binding("ctrl+c", "copy_selected", "Copy", priority=True),
    ]
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.attachments = {}
        self.image_counter = 0
        self.file_counter = 0
        self.text_counter = 0

    def _on_paste(self, event: events.Paste) -> None:
        text = event.text
        if not text:
            return
            
        import os
        is_image = False
        is_file = False
        is_long_text = False
        
        clean_text = text.strip().strip('"').strip("'")
        
        if os.path.isfile(clean_text):
            ext = os.path.splitext(clean_text)[1].lower()
            if ext in ['.png', '.jpg', '.jpeg', '.webp', '.heic', '.bmp', '.gif']:
                is_image = True
            else:
                is_file = True
        else:
            lines = text.splitlines()
            if len(lines) > 5:
                is_long_text = True
                
        if is_image:
            self.image_counter += 1
            marker = f"[Image-{self.image_counter}]"
            text_for_llm = f"\n[User melampirkan gambar. Path: {clean_text}]\n"
            self.attachments[marker] = ("image", text_for_llm)
            self.insert(marker)
            event.prevent_default()
        elif is_file:
            self.file_counter += 1
            marker = f"[File-{self.file_counter}]"
            try:
                with open(clean_text, "r", encoding="utf-8") as f:
                    content = f.read()
                text_for_llm = f"\n<file path=\"{clean_text}\">\n{content}\n</file>\n"
            except Exception:
                text_for_llm = f"\n[User melampirkan file namun tidak dapat dibaca otomatis. Path: {clean_text}]\n"
            self.attachments[marker] = ("file", text_for_llm)
            self.insert(marker)
            event.prevent_default()
        elif is_long_text:
            self.text_counter += 1
            num_lines = len(text.splitlines())
            marker = f"[{num_lines}-lines]"
            self.attachments[marker] = ("text", text)
            self.insert(marker)
            event.prevent_default()

    def action_submit_message(self) -> None:
        if self.text.strip(): 
            import inspect
            sig = inspect.signature(self.app.handle_input_submission)
            if 'attachments' in sig.parameters:
                self.app.handle_input_submission(self.text.strip(), self.attachments)
            else:
                self.app.handle_input_submission(self.text.strip())
        self.text = ""
        self.attachments = {}
        self.image_counter = 0
        self.file_counter = 0
        self.text_counter = 0
    def action_insert_newline(self) -> None: self.insert("\n")
    def action_suggest_up(self) -> None:
        if hasattr(self.app, "_suggestion_move"):
            self.app._suggestion_move(-1)
    def action_suggest_down(self) -> None:
        if hasattr(self.app, "_suggestion_move"):
            self.app._suggestion_move(1)
    def action_copy_selected(self) -> None:
        if not self.selected_text:
            from textual.actions import SkipAction
            raise SkipAction()
        self.app.copy_to_clipboard(self.selected_text)

