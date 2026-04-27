import os
import time

class LLMChatCloudMixin:
    def _init_cloud_backend(self) -> None:
        self.cloud_api_key = (self.config.get("google_api_key") or os.environ.get("GOOGLE_API_KEY") or "").strip()
        self.cloud_model = self.config.get("cloud_model").strip()
        if not self.cloud_api_key:
            raise RuntimeError("Google AI Studio API key belum diatur. Isi 'google_api_key' di config.json atau env GOOGLE_API_KEY.")
        from google import genai
        from google.genai import types
        self._genai = genai
        self._genai_types = types
        self.cloud_client = genai.Client(api_key=self.cloud_api_key)
        self.cloud_chat = self._create_cloud_chat(self.system_prompt, label="main")
        self.llm = self

    def _emit_debug(self, title: str, payload: str) -> None:
        if callable(self.debug_hook):
            try:
                self.debug_hook(title, payload)
            except Exception:
                pass

    def _create_cloud_chat(self, system_prompt: str, label: str = "cloud-session", history_data: list = None):
        config = self._genai_types.GenerateContentConfig(
            system_instruction=system_prompt or None,
            thinking_config=self._genai_types.ThinkingConfig(thinking_level="high"),
        )
        
        chat_history = None
        if history_data:
            chat_history = []
            for m in history_data:
                role = "user" if m.get("role") == "user" else "model"
                content = m.get("content") or ""
                chat_history.append({"role": role, "parts": [{"text": content}]})
                
        self._emit_debug(
            f"CLOUD SESSION [{label}]",
            f"model={self.cloud_model}\n\n[SYSTEM INSTRUCTION]\n{system_prompt or '[kosong]'}\n\n[HISTORY]\n{len(history_data) if history_data else 0} messages",
        )
        return self.cloud_client.chats.create(
            model=self.cloud_model,
            config=config,
            history=chat_history,
        )

    def prepare_standalone_chat(self, system_prompt: str):
        if self.backend != "cloud":
            return None
        return self._create_cloud_chat(system_prompt, label="prewarm")

    def _extract_cloud_chunk_text(self, response_obj) -> str:
        payload = None
        if hasattr(response_obj, "model_dump"):
            try:
                payload = response_obj.model_dump(exclude_none=True)
            except Exception:
                payload = None

        if isinstance(payload, dict):
            parts = []
            for candidate in payload.get("candidates", []) or []:
                content = candidate.get("content") or {}
                for part in content.get("parts", []) or []:
                    if part.get("thought") is True:
                        continue
                    text = part.get("text")
                    if text:
                        parts.append(text)
            return "".join(parts)

        parts = []
        for candidate in getattr(response_obj, "candidates", []) or []:
            content = getattr(candidate, "content", None)
            for part in getattr(content, "parts", []) or []:
                part_payload = None
                if hasattr(part, "model_dump"):
                    try:
                        part_payload = part.model_dump(exclude_none=True)
                    except Exception:
                        part_payload = None
                if isinstance(part_payload, dict) and part_payload.get("thought") is True:
                    continue
                if getattr(part, "thought", False):
                    continue
                text = getattr(part, "text", None)
                if text:
                    parts.append(text)
        return "".join(parts)

    def _stream_cloud_response(self, messages, chat=None, debug_label="cloud-main", skip_min_interval=False):
        body = list(messages)
        if body and body[0].get("role") == "system":
            body = body[1:]
        user_message = ""
        for msg in reversed(body):
            if msg.get("role") == "user":
                user_message = (msg.get("content") or "").strip()
                break
        if not user_message:
            return

        import re
        import os
        
        pattern = re.compile(
            r'(?:'
            r'"([^"]+\.(?:png|jpg|jpeg|webp|heic|bmp|gif))"|'
            r"'([^']+\.(?:png|jpg|jpeg|webp|heic|bmp|gif))'|"
            r'([a-zA-Z]:[\\/][^\s"\'<>]+\.(?:png|jpg|jpeg|webp|heic|bmp|gif))|'
            r'((?:/|\.\.?/|\.\.\\)[^\s"\'<>]+\.(?:png|jpg|jpeg|webp|heic|bmp|gif))|'
            r'([^\s"\'<>]+\.(?:png|jpg|jpeg|webp|heic|bmp|gif))'
            r')', 
            re.IGNORECASE
        )
        
        content_parts = []
        last_idx = 0
        
        for match in pattern.finditer(user_message):
            path = match.group(1) or match.group(2) or match.group(3) or match.group(4) or match.group(5)
            if path and os.path.isfile(path):
                try:
                    uploaded_file = self.cloud_client.files.upload(file=path)
                    text_before = user_message[last_idx:match.end()]
                    if text_before:
                        content_parts.append(text_before)
                    content_parts.append(uploaded_file)
                    last_idx = match.end()
                except Exception as e:
                    self._emit_debug("IMAGE UPLOAD ERROR", f"Failed to upload {path}: {e}")
        
        remaining_text = user_message[last_idx:].strip()
        if remaining_text:
            content_parts.append(remaining_text)
            
        if not content_parts:
            message_payload = user_message
        elif len(content_parts) == 1 and isinstance(content_parts[0], str):
            message_payload = content_parts[0]
        else:
            message_payload = content_parts

        target_chat = chat or self.cloud_chat
        
        dynamic_system_prompt = self.system_prompt
        if messages and messages[0].get("role") == "system":
            dynamic_system_prompt = messages[0].get("content") or self.system_prompt
            
        dynamic_config = self._genai_types.GenerateContentConfig(
            system_instruction=dynamic_system_prompt,
            thinking_config=self._genai_types.ThinkingConfig(thinking_level="high")
        )
        
        self._emit_debug(
            f"CLOUD REQUEST [{debug_label}]",
            f"model={self.cloud_model}\n"
            f"temperature={self.temperature}\n"
            f"top_p={self.top_p}\n"
            f"max_output_tokens={self.max_tokens}\n\n"
            f"[SYSTEM INSTRUCTION]\n{dynamic_system_prompt}\n\n"
            f"[USER MESSAGE]\n{user_message}",
        )
        while True:
            try:
                self._enforce_cloud_rate_limit(skip_min_interval=skip_min_interval)
                response = target_chat.send_message_stream(
                    message_payload,
                    config=dynamic_config,
                )
                got_any = False
                last_finish_reason = None
                for chunk in response:
                    if self._abort_event.is_set():
                        return
                    chunk_text = self._extract_cloud_chunk_text(chunk)
                    if getattr(chunk, "candidates", None):
                        last_finish_reason = getattr(chunk.candidates[0], "finish_reason", last_finish_reason)
                    if chunk_text:
                        got_any = True
                        yield chunk_text
                if not got_any and not self._abort_event.is_set():
                    yield f"\n[System: Response empty (finish_reason={last_finish_reason}). Continuing automatically...]\n"
                self.is_waiting_rate_limit = False
                return
            except Exception as e:
                err_msg = str(e)
                if ("429" in err_msg or "Resource has been exhausted" in err_msg or "quota" in err_msg.lower()) and not self._abort_event.is_set():
                    self.is_waiting_rate_limit = True
                    retry_match = re.search(r'retry in ([\d\.]+)s', err_msg)
                    wait_time = float(retry_match.group(1)) if retry_match else 10.0
                    time.sleep(min(wait_time, 30.0))
                    continue
                self.is_waiting_rate_limit = False
                raise RuntimeError(f"Google AI Studio API error: {e}") from None

    def create_chat_completion(self, messages, max_tokens, temperature, stream=True, **kwargs):
        original_max = self.max_tokens
        original_temp = self.temperature
        self.max_tokens = max_tokens
        self.temperature = temperature
        try:
            normalized_messages = list(messages)
            if not normalized_messages or normalized_messages[0].get("role") != "system":
                normalized_messages = [{"role": "system", "content": self.system_prompt}] + normalized_messages
            system_prompt = normalized_messages[0].get("content", self.system_prompt)
            temp_chat = self._create_cloud_chat(system_prompt, label="compat")
            text = "".join(self._stream_cloud_response(normalized_messages, chat=temp_chat, debug_label="compat"))
        finally:
            self.max_tokens = original_max
            self.temperature = original_temp
        if stream:
            def gen():
                yield {"choices": [{"delta": {"content": text}}]}
            return gen()
        return {"choices": [{"message": {"content": text}}]}

