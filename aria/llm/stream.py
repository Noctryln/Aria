from aria.utils.time import get_current_datetime_indonesian

class LLMChatStreamMixin:
    def _effective_system_prompt(self, enable_thinking=True) -> str:
        limit = 500 if self.backend == "cloud" else 50
        think_status = "YA" if enable_thinking else "TIDAK"
        
        mode_info = f"\n\n[INFO SISTEM]\nSaat ini kamu berjalan di mode: {self.backend.upper()}."
        if self.backend == "cloud":
            mode_info += f"\nWaktu sekarang: {get_current_datetime_indonesian()}"
        
        mode_info += f"\nBatas maksimal baris untuk membaca file per chunk adalah: {limit} baris.\nSesuaikan urutan chunk membacamu dengan batas ini (misal 1-{limit}, {limit+1}-{limit*2}, dst).\nStatus /think: {think_status}"
        
        think_info = ""
        if self.backend == "cloud" and enable_thinking:
            think_info = (
                "\n\n[PENTING: FORMAT OUTPUT BERPIKIR (KHUSUS CLOUD)]\n"
                "API cloud TIDAK memiliki fitur pemikiran bawaan. Oleh karena itu, kamu WAJIB MEMBUNGKUS seluruh "
                "proses penalaran, perencanaan, dan status ke dalam tag XML <think> dan </think> secara eksplisit.\n"
                "ATURAN MUTLAK:\n"
                "1. SEMUA deklarasi seperti INTENT, TASK SCOPE, PROGRESS, RE-ANCHOR, RISK CHECK, CMD CHECK, "
                "REWRITE, BLAST RADIUS, Asumsi, dan Rencana aksi HARUS berada DI DALAM tag <think>.\n"
                "   (PENGECUALIAN: Jika user secara EKSPLISIT menyuruhmu untuk menulis atau mengutip kembali "
                "isi dari INTENT/PLANNING/dll sebagai bagian dari percakapan normal, maka tulislah di luar tag).\n"
                "2. JANGAN PERNAH MENCETAK keyword-keyword tersebut di luar tag <think> (kecuali kondisi pengecualian terpenuhi)!\n"
                "3. Di dalam tag <think>, kamu BEBAS menggunakan baris baru (Enter), list angka (1. 2. 3.), atau bullet point (-). "
                "Jangan gabungkan semuanya menjadi satu paragraf panjang yang sulit dibaca. Buatlah rapi.\n"
                "4. Kamu bisa menggunakan satu blok <think>...</think> besar di awal respons, atau beberapa blok "
                "<think>...</think> kecil jika tersebar, asalkan tidak ada keyword penalaran yang bocor ke respons utama.\n\n"
                "CONTOH STRUKTUR RESPONS YANG BENAR:\n"
                "<think>\n"
                "INTENT: Aku menginterpretasikan permintaan ini sebagai...\n"
                "Rencana aksi:\n"
                "1. Membuat file...\n"
                "2. Menjalankan skrip...\n"
                "Asumsi yang aku buat: Kamu ingin kode yang...\n\n"
                "TASK SCOPE: Membuat skrip... | DIKETAHUI: ... | BELUM DIKETAHUI: ...\n"
                "BLAST RADIUS: Perubahan ini hanya...\n"
                "</think>\n"
                "Tentu, aku akan membuatkan skrip kalkulator yang kamu minta. Berikut adalah filenya:\n"
                "<write file=\"kalkulator.py\">\n"
                "...\n"
                "</write>"
            )
            
        return self.system_prompt + mode_info + think_info

    def _apply_runtime_controls(self, messages, enable_thinking=True):
        prepared = [dict(msg) for msg in messages]
        if len(prepared) > 1 and prepared[-1]["role"] == "user":
            control_prefix = "/think\n" if enable_thinking else "/no_think\n"
            prepared[-1]["content"] = control_prefix + prepared[-1]["content"]
        return prepared

    def _build_messages(self, enable_thinking=True, use_history=True):
        max_hist_tokens = int(self.active_ctx * 0.8)
        while self.history and self.history_token_total > max_hist_tokens:
            removed = self.history.pop(0)
            self.history_token_total -= self.count_tokens(removed["content"])

        messages = [{"role": "system", "content": self._effective_system_prompt(enable_thinking=enable_thinking)}]        
        if self.backend == "cloud":
            if self.history:
                messages.append(dict(self.history[-1]))
            return messages
        if use_history:
            for msg in self.history:
                messages.append(dict(msg))
        return self._apply_runtime_controls(messages, enable_thinking=enable_thinking)

    def _stream_local_response(self, messages):
        stream_kwargs = {
            "messages": messages,
            "max_tokens": self.max_tokens,
            "temperature": self.temperature,
            "top_p": self.top_p,
            "stream": True,
            "stop": ["<system_observation>", "</system_observation>"],
            "cache_prompt": True,
        }
        try:
            stream = self.llm.create_chat_completion(**stream_kwargs)
        except TypeError:
            stream_kwargs.pop("cache_prompt", None)
            stream = self.llm.create_chat_completion(**stream_kwargs)

        try:
            for chunk in stream:
                if self._abort_event.is_set():
                    break
                delta = chunk["choices"][0]["delta"]
                if "content" in delta:
                    yield delta["content"]
        except RuntimeError as e:
            if self._abort_event.is_set() and "llama_decode returned 2" in str(e):
                return
            raise

    def stream_response(self, enable_thinking=True, use_history=True):
        self.clear_abort()
        try:
            if self.backend == "cloud":
                messages = self._build_messages(enable_thinking=enable_thinking, use_history=use_history)
                yield from self._stream_cloud_response(messages, debug_label="chat")
            else:
                messages = self._build_messages(enable_thinking=enable_thinking, use_history=use_history)
                yield from self._stream_local_response(messages)
        finally:
            self.clear_abort()

    def stream_one_off(self, prompt: str, enable_thinking=False, max_tokens=None, temperature=None) -> str:
        original_max = self.max_tokens
        original_temp = self.temperature
        if max_tokens is not None:
            self.max_tokens = max_tokens
        if temperature is not None:
            self.temperature = temperature
        try:
            if self.backend == "cloud":
                messages = [
                    {"role": "system", "content": self._effective_system_prompt(enable_thinking=enable_thinking)},
                    {"role": "user", "content": prompt},
                ]
                temp_chat = self._create_cloud_chat(self._effective_system_prompt(enable_thinking=enable_thinking), label="one-off")
                return "".join(self._stream_cloud_response(messages, chat=temp_chat, debug_label="one-off", skip_min_interval=True))
            messages = self._apply_runtime_controls(
                [
                    {"role": "system", "content": self._effective_system_prompt(enable_thinking=enable_thinking)},
                    {"role": "user", "content": prompt},
                ],
                enable_thinking=enable_thinking,
            )
            return "".join(self._stream_local_response(messages))
        finally:
            self.max_tokens = original_max
            self.temperature = original_temp

    def stream_standalone(self, system_prompt: str, prompt: str, enable_thinking=False, max_tokens=None, temperature=None) -> str:
        return "".join(self.stream_standalone_chunks(system_prompt, prompt, enable_thinking=enable_thinking, max_tokens=max_tokens, temperature=temperature))

    def stream_standalone_chunks(self, system_prompt: str, prompt: str, enable_thinking=False, max_tokens=None, temperature=None, skip_min_interval=False, chat=None):
        original_max = self.max_tokens
        original_temp = self.temperature
        if max_tokens is not None:
            self.max_tokens = max_tokens
        if temperature is not None:
            self.temperature = temperature
        try:
            if self.backend == "cloud":
                messages = [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": prompt},
                ]
                temp_chat = chat or self._create_cloud_chat(system_prompt, label="standalone")
                yield from self._stream_cloud_response(messages, chat=temp_chat, debug_label="standalone", skip_min_interval=skip_min_interval)
            else:
                messages = self._apply_runtime_controls(
                    [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": prompt},
                    ],
                    enable_thinking=enable_thinking,
                )
                yield from self._stream_local_response(messages)
        finally:
            self.max_tokens = original_max
            self.temperature = original_temp

