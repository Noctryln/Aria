from aria.core.paths import DEFAULT_MODEL_PATH
from aria.core.runtime import CPU_COUNT

class LLMChatLocalMixin:
    def _init_local_backend(self) -> None:
        import llama_cpp
        import ctypes
        self._llama_cpp = llama_cpp
        self._ctypes = ctypes
        try:
            global _llama_log_cb
            def _mute_log(level, message, user_data): pass
            _llama_log_cb = ctypes.CFUNCTYPE(None, ctypes.c_int, ctypes.c_char_p, ctypes.c_void_p)(_mute_log)
            llama_cpp.llama_log_set(_llama_log_cb, ctypes.c_void_p(0))
        except Exception:
            pass

        model_path = self.config.get("local_model_path") or DEFAULT_MODEL_PATH
        llm_kwargs = {
            "model_path": model_path,
            "n_ctx": self.ctx,
            "n_threads": self.n_threads,
            "n_threads_batch": max(self.n_threads, CPU_COUNT),
            "n_gpu_layers": 0,
            "n_batch": self.n_batch,
            "n_ubatch": self.n_ubatch,
            "flash_attn": True,
            "verbose": False,
        }
        lora_path = (self.config.get("lora_adapter_path") or "").strip()
        if lora_path:
            llm_kwargs["lora_path"] = lora_path

        self.llm = llama_cpp.Llama(**llm_kwargs)
        self._install_abort_callback()

    def _install_abort_callback(self) -> None:
        if self.backend != "local":
            return
        try:
            llama_cpp = self._llama_cpp
            ctypes = self._ctypes
            ctx_ptr = None
            if hasattr(self.llm, "ctx") and hasattr(self.llm.ctx, "ctx"):
                ctx_ptr = self.llm.ctx.ctx
            elif hasattr(self.llm, "_ctx") and hasattr(self.llm._ctx, "ctx"):
                ctx_ptr = self.llm._ctx.ctx
            if ctx_ptr is None or not hasattr(llama_cpp, "llama_set_abort_callback"):
                return
            global _llama_abort_cb
            def _abort_cb(_):
                return bool(self._abort_event.is_set())
            _llama_abort_cb = ctypes.CFUNCTYPE(ctypes.c_bool, ctypes.c_void_p)(_abort_cb)
            llama_cpp.llama_set_abort_callback(ctx_ptr, _llama_abort_cb, None)
        except Exception:
            pass

