CSS = """
Screen { background: #0c0c0c; layout: vertical; }
#banner { height: auto; padding: 1 2 0 2; background: #0c0c0c; }
#chat-log { background: #0c0c0c; scrollbar-size: 0 0; padding: 0 2; height: 1fr; overflow-y: auto; }
.chat-msg-user { padding-bottom: 0; margin-top: 1; margin-bottom: 1; }
.think-header { color: #7b6b9a; text-style: italic; padding-top: 1; }
ThinkBlock { border-left: solid #3d2d5a; color: #7b6b9a; text-style: italic; padding-left: 1; margin-bottom: 1; height: auto; }
AIResponse { layout: horizontal; height: auto; margin-bottom: 0; }
.ai-icon { width: 3; color: #d1a662; text-style: bold; }
.ai-content { width: 1fr; color: #c6bbd8; height: auto; }
#input-area { height: auto; dock: bottom; background: #0c0c0c; }
#separator { height: 1; background: #0c0c0c; padding: 0 0; color: #3d2d5a; }
#loading-bar { height: 1; background: #0c0c0c; padding: 0 2; color: #7b6b9a; }
#input-box { height: auto; min-height: 3; max-height: 10; background: #0c0c0c; border: round #3d2d5a; border-title-color: #7b6b9a; color: #c6bbd8; padding: 0 1; margin: 0 1; }
#input-box:focus { border: round #71d1d1; border-title-color: #71d1d1; }
#input-box .text-area--cursor-line { background: transparent; }
#status-bar { height: 1; background: #0c0c0c; padding: 0 2; color: #7b6b9a; }
.tool-box { border: round #3d2d5a; background: #0c0c0c; padding: 0 1; margin: 0 1 0 3; height: auto; }
.ai-content .tool-box { margin: 0 0 0 0; }
.tool-box MarkdownParagraph { margin: 0; }
MarkdownFence { border: round #3d2d5a; background: #0c0c0c; width: 100%; margin: 0 0 1 0; padding: 0 1; }
.ai-content > MarkdownParagraph { margin: 0 0 1 0; }
.ai-content MarkdownList { margin: 0 0 1 0; padding: 0 0 0 2; }
.ai-content MarkdownListItem { margin: 0; padding: 0; }
.ai-content MarkdownListItem MarkdownParagraph { margin: 0; padding: 0; }
.ai-content > *:last-child { margin-bottom: 0; }
#permission-dialog { display: none; height: auto; background: #111111; border: round #c97fd4; padding: 1; margin: 0 1 1 1; border-title-color: #d1a662; }
#perm-buttons { height: auto; margin-top: 1; layout: vertical; align-horizontal: left; }
.perm-btn { margin: 0; padding: 0 1 0 0; width: auto; min-width: 1; height: auto; min-height: 1; border: none; background: transparent; color: #7b6b9a; text-style: bold; content-align: left middle; }
.perm-btn:hover { border: none; background: transparent; color: #d1a662; }
.perm-btn:focus { border: none; background: transparent; color: #d1a662; }
.perm-btn.-active { border: none; background: transparent; color: #d1a662; }
.thinking-placeholder { color: #9d8ec0; text-style: italic; }
#cmd-suggestions { display: none; height: auto; background: #0c0c0c; border-top: solid #3d2d5a; padding: 0; margin: 0; }
.cmd-suggestion-item { height: 1; padding: 0 2; color: #7b6b9a; background: #0c0c0c; }
.cmd-suggestion-item.--highlight { color: #0c0c0c; background: #3d2d5a; text-style: bold; }
.cmd-suggestion-item.--highlight Static { color: #71d1d1; }
"""

