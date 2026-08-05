"""Optional AI-generated solution analysis.

Off by default. Enabled only when the user picks an available backend, so installing
leetvault never implies an API bill or a model download.
"""

from leetvault.ai.prompt import build_user_prompt
from leetvault.ai.providers import (
    AIProvider,
    ProviderInfo,
    available_providers,
    get_provider,
    provider_names,
)

__all__ = [
    "AIProvider",
    "ProviderInfo",
    "available_providers",
    "build_user_prompt",
    "get_provider",
    "provider_names",
]
