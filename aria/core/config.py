import json
import os

from aria.core.paths import CONFIG_PATH, DEFAULT_MODEL_PATH

DEFAULT_CONFIG = {
    "backend": "local",
    "local_model_path": DEFAULT_MODEL_PATH,
    "lora_adapter_path": "",
    "google_api_key": "",
    "cloud_model": "gemma-4-26b-a4b-it",
    "serpapi_key": "",
    "github_oauth_token": "",
    "github_client_id": "",
}

def load_config() -> dict:
    config = dict(DEFAULT_CONFIG)
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                loaded = json.load(f)
            if isinstance(loaded, dict):
                config.update({k: v for k, v in loaded.items() if k in DEFAULT_CONFIG})
        except Exception:
            pass
    save_config(config)
    return config

def save_config(config: dict) -> None:
    merged = dict(DEFAULT_CONFIG)
    merged.update({k: v for k, v in config.items() if k in DEFAULT_CONFIG})
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(merged, f, indent=2, ensure_ascii=False)

