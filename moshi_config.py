import os
import sys
import json
import re
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
ENV_FILE = PROJECT_ROOT / "telegram" / ".env"
OPENCODE_FILE = PROJECT_ROOT / "opencode.json"

DEFAULT_MODEL = "gemma-4-12b-coder-fable5-composer2.5-v1"

def _load_env_model() -> str:
    """Read LM_MODEL from telegram/.env if present."""
    if ENV_FILE.exists():
        try:
            content = ENV_FILE.read_text(encoding="utf-8")
            for line in content.splitlines():
                if line.startswith("LM_MODEL="):
                    val = line.split("=", 1)[1].strip()
                    if val:
                        return val
        except Exception:
            pass
    return DEFAULT_MODEL

def get_model() -> str:
    """Return current active model name across the MOSHI system."""
    return os.getenv("LM_MODEL") or _load_env_model()

def set_model(new_model: str) -> str:
    """Master function to update the model in all config files and scripts."""
    new_model = new_model.strip()
    if not new_model:
        raise ValueError("Model name cannot be empty")

    # 1. Update telegram/.env
    if ENV_FILE.exists():
        content = ENV_FILE.read_text(encoding="utf-8")
        if "LM_MODEL=" in content:
            new_lines = []
            for line in content.splitlines():
                if line.startswith("LM_MODEL="):
                    new_lines.append(f"LM_MODEL={new_model}")
                else:
                    new_lines.append(line)
            ENV_FILE.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
        else:
            ENV_FILE.write_text(content.rstrip() + f"\nLM_MODEL={new_model}\n", encoding="utf-8")
    else:
        ENV_FILE.parent.mkdir(parents=True, exist_ok=True)
        ENV_FILE.write_text(f"LM_MODEL={new_model}\n", encoding="utf-8")

    # 2. Update opencode.json
    if OPENCODE_FILE.exists():
        try:
            opencode_data = json.loads(OPENCODE_FILE.read_text(encoding="utf-8"))
            # Sanitize model key for opencode model registry
            model_key = new_model
            opencode_data.setdefault("provider", {}).setdefault("lmstudio", {}).setdefault("models", {})[model_key] = {
                "name": new_model,
                "modelID": new_model
            }
            opencode_data["model"] = f"lmstudio/{model_key}"
            OPENCODE_FILE.write_text(json.dumps(opencode_data, indent=4), encoding="utf-8")
        except Exception as e:
            print(f"[WARN] Failed to update opencode.json: {e}")

    # 3. Update DEFAULT_MODEL in moshi_config.py
    config_file = Path(__file__).resolve()
    config_content = config_file.read_text(encoding="utf-8")
    updated_content = re.sub(
        r'DEFAULT_MODEL = "gemma-4-12b-coder-fable5-composer2.5-v1"',
        f'DEFAULT_MODEL = "gemma-4-12b-coder-fable5-composer2.5-v1"',
        config_content
    )
    config_file.write_text(updated_content, encoding="utf-8")

    if hasattr(sys.stdout, 'reconfigure'):
        try:
            sys.stdout.reconfigure(encoding='utf-8')
        except Exception:
            pass

    print(f"[OK] Successfully set master model to: {new_model}")
    return new_model

if __name__ == "__main__":
    if len(sys.argv) > 1:
        cmd = sys.argv[1].lower()
        if cmd == "set" and len(sys.argv) > 2:
            set_model(sys.argv[2])
        elif cmd == "get":
            print(get_model())
        else:
            print("Usage: python moshi_config.py [get | set <model_name>]")
    else:
        print(f"Master Model: {get_model()}")
