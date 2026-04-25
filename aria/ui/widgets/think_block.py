from textual.widgets import Static

class ThinkBlock(Static): 
    def __init__(self, *args, **kwargs): super().__init__(*args, markup=False, **kwargs)

