import os

PACKAGE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
PROJECT_ROOT = os.path.abspath(os.path.join(PACKAGE_DIR, ".."))
SCRIPT_DIR = PROJECT_ROOT
LAUNCH_DIR = os.path.abspath(os.getcwd())
ASSETS_DIR = os.path.join(PACKAGE_DIR, "assets")
DEFAULT_MODEL_NAME     = "Qwen3-4B"
DEFAULT_MODEL_PATH     = os.path.join(PROJECT_ROOT, "models", DEFAULT_MODEL_NAME, f"{DEFAULT_MODEL_NAME}.gguf")
CONFIG_PATH = os.path.join(PROJECT_ROOT, "config.json")
