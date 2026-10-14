"""Browser-scoped credential storage; never persist credentials on the server."""
from pathlib import Path

import streamlit.components.v1 as components

_key_store = components.declare_component(
    'groq_key_store', path=str(Path(__file__).parent / 'components' / 'api_key_store')
)


def saved_browser_key():
    result = _key_store(key='groq-browser-key', default=None)
    if not isinstance(result, dict):
        return None
    value = result.get('api_key')
    return value.strip() if isinstance(value, str) and value.strip() else None
