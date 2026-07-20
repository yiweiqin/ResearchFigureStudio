"""External model/provider integration entry points.

Provider code must not contain repository paths or persist credentials.
"""

from ..rebuild_vlm_adapters import build_rebuild_vlm_adapters
from ..vlm_client import call_vlm_json, resolve_vlm_model, vlm_credentials_available

__all__ = [
    "build_rebuild_vlm_adapters",
    "call_vlm_json",
    "resolve_vlm_model",
    "vlm_credentials_available",
]
