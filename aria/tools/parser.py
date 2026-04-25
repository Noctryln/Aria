import re

from aria.tools.registry import TOOL_NAME_PATTERN

TOOL_INNER_TAG_PATTERN = rf'<(?P<tag>{TOOL_NAME_PATTERN})(?P<attrs>(?:\s+[^>]*)?)>(?P<body>.*?)</(?P=tag)>'
TOOL_TAG_PATTERN = rf'<(?P<tag>{TOOL_NAME_PATTERN})(?P<attrs>\s+[^>]*)?>(?P<body>.*?)</(?P=tag)>'
TOOL_BLOCK_PATTERN = re.compile(TOOL_TAG_PATTERN, re.IGNORECASE | re.DOTALL)
TOOL_EXACT_PATTERN = re.compile(rf'^\s*{TOOL_TAG_PATTERN}\s*$', re.IGNORECASE | re.DOTALL)
SYSTEM_OBSERVATION_PATTERN = re.compile(r'<system_observation>.*?</system_observation>', re.DOTALL)
TOOL_TAG_FULL_PATTERN = TOOL_BLOCK_PATTERN
WRITE_FILE_ATTR_PATTERN = re.compile(r'file=["\']?([^"\'>]+)["\']?')
EDIT_FILE_ATTR_PATTERN = re.compile(r'file=["\']?([^"\'>]+)["\']?')
CHECK_FILE_ATTR_PATTERN = re.compile(r'file=["\']?([^"\'>]+)["\']?')
READ_START_PATTERN = re.compile(r'start=["\']?(\d+)["\']?')
READ_END_PATTERN = re.compile(r'end=["\']?(\d+)["\']?')

def parse_tool_block(text: str):
    match = TOOL_BLOCK_PATTERN.search(text or "")
    if not match:
        return None
    
    tag = (match.group("tag") or "").lower()
    attrs = match.group("attrs") or ""
    body = match.group("body") or ""
    
    return {
        "full": match.group(0).strip(),
        "tag": tag,
        "attrs": attrs,
        "body": body,
    }

def strip_tool_blocks(text: str) -> str:
    return re.sub(rf'\s*{TOOL_TAG_PATTERN}\s*', '\n', text or "", flags=re.IGNORECASE | re.DOTALL).strip()

