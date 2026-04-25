import re

from aria.tools.registry import TOOL_OPEN_PATTERN

SYSTEM_OBSERVATION_PATTERN = re.compile(r'<system_observation>.*?</system_observation>', re.DOTALL)
LIST_NUM_PATTERN = re.compile(r'^\d+\.\s')
LIST_BULLET_PATTERN = re.compile(r'^[-*]\s')

class AriaTextMixin:
    def _decorate_tool_tags_with_status(self, text: str, status: str) -> str:
        def repl(match):
            tag = match.group(1)
            attrs = match.group(2) or ""
            if re.search(r'\bstatus\s*=', attrs, flags=re.IGNORECASE):
                attrs = re.sub(r'\bstatus\s*=\s*"[^"]*"', f'status="{status}"', attrs, flags=re.IGNORECASE)
            else:
                attrs = f'{attrs} status="{status}"'
            return f"<{tag}{attrs}>"
        return TOOL_OPEN_PATTERN.sub(repl, text)
