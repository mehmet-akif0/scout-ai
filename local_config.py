"""Load optional local settings without overriding injected runtime bindings."""
import os
from pathlib import Path
import tomllib

ROOT = Path(__file__).resolve().parent
LOCAL_CONFIG = ROOT / 'scoutai.local.toml'
ALLOWED = {
    'SCOUTAI_AI_API_KEY', 'SCOUTAI_AI_MODEL', 'SCOUTAI_DB_PATH',
    'SCOUTAI_RESEARCH_TOOL_CALLS', 'SCOUTAI_RESEARCH_SOURCES',
    'SCOUTAI_RESEARCH_TIMEOUT', 'SCOUTAI_RESEARCH_RETRIES',
    'SCOUTAI_RESEARCH_OUTPUT_TOKENS', 'SCOUTAI_RESEARCH_CACHE_HOURS',
    'SCOUTAI_RESEARCH_BATCH',
}


def load_local_config(path=None):
    """Return loaded variable names only. Empty examples do not configure an API."""
    path = Path(path) if path is not None else LOCAL_CONFIG
    if not path.exists():
        return []
    try:
        with path.open('rb') as file:
            config = tomllib.load(file)
    except (OSError, tomllib.TOMLDecodeError):
        raise ValueError('Cannot read scoutai.local.toml. Check its TOML syntax; no secret values are logged.') from None
    settings = config.get('environment', {})
    if set(config) - {'environment'} or not isinstance(settings, dict):
        raise ValueError('Local configuration must contain only an [environment] table.')
    # Validate the entire file before changing the environment.
    if any(name not in ALLOWED or not isinstance(value, str) for name, value in settings.items()):
        raise ValueError('Local configuration contains unsupported settings or non-string values.')
    loaded = []
    for name, value in settings.items():
        if value and not os.environ.get(name):
            os.environ[name] = value
            loaded.append(name)
    return loaded
