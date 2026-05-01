from rich.text import Text
from textual.containers import Vertical
from textual.widgets import Static

class ThinkBlock(Vertical):
    def __init__(self, content: str = "", **kwargs):
        super().__init__(**kwargs)
        self.header = Static("Thinking...", classes="think-header")
        self.body = Static(content, classes="think-body")

    def compose(self):
        yield self.header
        yield self.body

    def update(self, renderable):
        if isinstance(renderable, str):
            clean_text = renderable.replace("<think>", "").replace("</think>", "").strip()
            renderable = Text(clean_text, style="#7b6b9a italic")
        self.body.update(renderable)

