import threading
from collections import deque

from aria.core.runtime import DEFAULT_CLOUD_CTX
from aria.llm.cloud import LLMChatCloudMixin
from aria.llm.local import LLMChatLocalMixin
from aria.llm.rate_limit import LLMChatRateLimitMixin
from aria.llm.stream import LLMChatStreamMixin

class LLMChat(
    LLMChatLocalMixin,
    LLMChatCloudMixin,
    LLMChatStreamMixin,
    LLMChatRateLimitMixin,
):
    def __init__(self, config, system_prompt, ctx, max_tokens, temperature, top_p, n_threads, n_batch, n_ubatch):
        self.config = dict(config)
        self.system_prompt = system_prompt
        self.ctx = ctx
        self.max_tokens = max_tokens
        self.temperature = temperature
        self.top_p = top_p
        self.n_threads = n_threads
        self.n_batch = n_batch
        self.n_ubatch = n_ubatch
        self.history = []
        self.history_lock = threading.RLock()
        self.history_token_total = 0
        self._abort_event = threading.Event()
        self._cloud_request_lock = threading.Lock()
        self._cloud_request_times = deque()
        self.debug_hook = None
        self.backend = self.config.get("backend", "local").lower()
        self.mode_label = "Cloud" if self.backend == "cloud" else "Local"
        self.is_waiting_rate_limit = False
        self.llm = None
        self._llama_cpp = None
        self._ctypes = None
        self._init_backend()

    @property
    def active_ctx(self) -> int:
        return DEFAULT_CLOUD_CTX if self.backend == "cloud" else self.ctx

    def close(self) -> None:
        if self.backend == "local" and self.llm is not None:
            # Explicitly delete the Llama instance to free C++ memory
            try:
                if hasattr(self.llm, "close"):
                    self.llm.close()
                del self.llm
                self.llm = None
            except Exception:
                pass
            import gc
            gc.collect()

    def _init_backend(self) -> None:
        if self.backend == "cloud":
            self._init_cloud_backend()
        else:
            self._init_local_backend()

    def request_abort(self) -> None:
        self._abort_event.set()

    def clear_abort(self) -> None:
        self._abort_event.clear()

    def reset_history(self) -> None:
        with self.history_lock:
            self.history = []
            self.history_token_total = 0
        if self.backend == "cloud":
            self.cloud_chat = self._create_cloud_chat(self.system_prompt, label="reset")

    def _prune_history(self) -> bool:
        limit = int(self.active_ctx * 0.95) # 5% buffer
        pruned = False
        # Always keep at least 4 messages to maintain some context
        with self.history_lock:
            while self.history_token_total > limit and len(self.history) > 4:
                removed = self.history.pop(0)
                self.history_token_total -= self.count_tokens(removed["content"])
                pruned = True
        return pruned

    def load_history(self, history: list) -> None:
        with self.history_lock:
            self.history = [dict(m) for m in history]
            self.history_token_total = sum(self.count_tokens(m["content"]) for m in self.history)
        self._prune_history()
        if self.backend == "cloud":
            self.cloud_chat = self._create_cloud_chat(self.system_prompt, label="resume", history_data=self.history)

    def count_tokens(self, text: str) -> int:
        if self.backend == "local" and self.llm:
            try:
                return len(self.llm.tokenize(text.encode("utf-8")))
            except Exception:
                pass
        return max(1, len(text) // 3) # More conservative estimate (1 token approx 3 chars)

    def add_message(self, role, content):
        with self.history_lock:
            # Sliding Window for Minecraft Tools (Optimization)
            if role == "user" or role == "assistant":
                if "[MC_OBSERVE]" in content:
                    # Keep only the latest MC_OBSERVE
                    self.history = [m for m in self.history if "[MC_OBSERVE]" not in m["content"]]
                elif "[MC_ACT]" in content:
                    # Keep only the last 3 MC_ACT to preserve some context but avoid bloat
                    acts = [i for i, m in enumerate(self.history) if "[MC_ACT]" in m["content"]]
                    if len(acts) >= 3:
                        for idx in acts[:-2]: # Keep last 2 in history, the new one will be the 3rd
                            self.history[idx]["content"] = "[MC_ACT] (Previous result truncated to save tokens)"
            
            self.history.append({"role": role, "content": content})
            self.history_token_total = sum(self.count_tokens(m["content"]) for m in self.history)
        
        if self._prune_history():
            if self.backend == "cloud":
                self.cloud_chat = self._create_cloud_chat(self.system_prompt, label="pruned", history_data=self.history)

