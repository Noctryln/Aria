from textual.widgets import Static

from aria.integrations.github import AriaGithubMixin
from aria.integrations.web_search import AriaWebSearchMixin
from aria.integrations.minecraft import AriaMinecraftMixin
from aria.llm.base import LLMChat
from aria.tools.executor import AriaToolExecutorMixin
from aria.tools.registry import AriaToolRegistryMixin

class AriaAgentMixin(
    AriaToolExecutorMixin,
    AriaToolRegistryMixin,
    AriaGithubMixin,
    AriaWebSearchMixin,
    AriaMinecraftMixin,
):
    def _submit_to_chat(self, text: str, is_system_obs: bool = False, attachments: dict = None) -> None:
        if attachments is None:
            attachments = {}
        log = self.query_one("#chat-log")
        if not is_system_obs:
            llm_text = text
            for marker, (kind, real_text) in attachments.items():
                llm_text = llm_text.replace(marker, real_text)
                
            self.conversation_turns += 1; self.total_input_tokens += self.llm.count_tokens(llm_text)
            user_box = Static("", classes="chat-msg-user", markup=False)
            log.mount(user_box)
            self._animate_user_message(user_box, text)
            log.scroll_end(animate=False)
            self.llm.add_message("user", llm_text)
        else: self.total_input_tokens += self.llm.count_tokens(text); self.llm.add_message("user", text) 
        self._run_stream()
