import re

TOOL_NAME_PATTERN = r'search_workspace|search_image|find_file|check_syntax|web_search|run_?cmd|fetch_url|github_actions|github_search|github_issue|github_repo|github_file|github_pr|mkdir|read|edit|write|search|ls|rm'
TOOL_OPEN_PATTERN = re.compile(rf'<(?P<tag>{TOOL_NAME_PATTERN})(?P<attrs>[^>]*)>', re.IGNORECASE)

class AriaToolRegistryMixin:
    def _extract_tools_from_text(self, text: str) -> list[dict]:
        tools = []
        i = 0
        n = len(text)
        
        md_block_re = re.compile(r'```')
        md_inline_re = re.compile(r'`')
        
        while i < n:
            md_block_match = md_block_re.search(text, i)
            md_inline_match = md_inline_re.search(text, i)
            tool_match = TOOL_OPEN_PATTERN.search(text, i)
            
            candidates = []
            if md_block_match: candidates.append((md_block_match.start(), "md_block", md_block_match))
            if md_inline_match: candidates.append((md_inline_match.start(), "md_inline", md_inline_match))
            if tool_match: candidates.append((tool_match.start(), "tool", tool_match))
            
            if not candidates:
                break
                
            candidates.sort(key=lambda x: x[0])
            open_idx, kind, match = candidates[0]
            
            if kind == "md_inline" and text[open_idx:open_idx+3] == "```":
                kind = "md_block"
                
            if kind == "md_block":
                close_idx = text.find("```", open_idx + 3)
                if close_idx == -1:
                    break
                i = close_idx + 3
            elif kind == "md_inline":
                close_idx = text.find("`", open_idx + 1)
                if close_idx == -1:
                    i = open_idx + 1
                else:
                    i = close_idx + 1
            elif kind == "tool":
                tag_start = open_idx
                line_start = text.rfind("\n", 0, tag_start) + 1
                before_tag_on_line = text[line_start:tag_start]
                if before_tag_on_line.strip():
                    i = open_idx + len(match.group(0))
                    continue
                    
                tag = match.group("tag")
                attrs = match.group("attrs") or ""
                after_open = open_idx + len(match.group(0))
                
                close_match = re.compile(rf'</{re.escape(tag)}>', flags=re.IGNORECASE).search(text, after_open)
                if close_match:
                    inner_end = close_match.start()
                    inner = text[after_open:inner_end]
                    full_match_text = text[open_idx:close_match.end()]
                    
                    tools.append({
                        "tag": tag,
                        "attrs": attrs,
                        "inner": inner,
                        "full": full_match_text,
                        "start": open_idx,
                        "end": close_match.end()
                    })
                    i = close_match.end()
                else:
                    i = open_idx + len(match.group(0))
                    
        return tools
