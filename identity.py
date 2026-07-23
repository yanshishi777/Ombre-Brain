import os

DEFAULT_AI_NAME = "AI"
DEFAULT_USER_NAME = "User"
DEFAULT_USER_DISPLAY_NAME = "用户"
DEFAULT_USER_ALIASES = ["对方"]

GENERIC_AI_NAME = "AI"
GENERIC_USER_NAME = "User"
GENERIC_USER_DISPLAY_NAME = "用户"
GENERIC_USER_ALIASES = ["对方"]


def _clean_string(value, default: str) -> str:
    text = str(value or "").strip()
    return text or default


def _clean_list(value, default: list[str]) -> list[str]:
    if isinstance(value, str):
        items = [item.strip() for item in value.split(",")]
    elif isinstance(value, list):
        items = [str(item).strip() for item in value]
    else:
        items = []
    return [item for item in items if item] or list(default)


def identity_names(config: dict | None = None) -> dict:
    cfg = {}
    if isinstance(config, dict) and isinstance(config.get("identity"), dict):
        cfg = config["identity"]

    # Environment variable overrides (highest priority)
    # 优先级：环境变量 > config.yaml > 默认值
    env_ai_name = os.environ.get("OMBRE_IDENTITY_AI_NAME", "").strip()
    env_user_name = os.environ.get("OMBRE_IDENTITY_USER_NAME", "").strip()
    env_user_display_name = os.environ.get("OMBRE_IDENTITY_USER_DISPLAY_NAME", "").strip()
    env_user_aliases = os.environ.get("OMBRE_IDENTITY_USER_ALIASES", "").strip()

    aliases = _clean_list(
        env_user_aliases or cfg.get("user_aliases"),
        DEFAULT_USER_ALIASES,
    )
    ai_name = _clean_string(
        env_ai_name or cfg.get("ai_name"),
        DEFAULT_AI_NAME,
    )
    user_name = _clean_string(
        env_user_name or cfg.get("user_name"),
        DEFAULT_USER_NAME,
    )
    user_display_name = _clean_string(
        env_user_display_name or cfg.get("user_display_name") or cfg.get("human_name"),
        DEFAULT_USER_DISPLAY_NAME,
    )
    relationship_terms = list(dict.fromkeys([ai_name, user_name, user_display_name, *aliases]))
    return {
        "ai_name": ai_name,
        "user_name": user_name,
        "user_display_name": user_display_name,
        "user_aliases": aliases,
        "user_aliases_text": "、".join(aliases),
        "relationship_terms": relationship_terms,
    }


def generic_identity_names() -> dict:
    return identity_names(
        {
            "identity": {
                "ai_name": GENERIC_AI_NAME,
                "user_name": GENERIC_USER_NAME,
                "user_display_name": GENERIC_USER_DISPLAY_NAME,
                "user_aliases": GENERIC_USER_ALIASES,
            }
        }
    )


def render_identity_template(template: str, names: dict) -> str:
    text = template
    for key, value in names.items():
        if isinstance(value, list):
            continue
        text = text.replace("{" + key + "}", str(value))
    return text
