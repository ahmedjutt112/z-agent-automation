"""AI Provider abstraction — master prompt §6.

Architecture:

    AIProvider (abstract base)
     ├── OpenAIProvider            (first-party OpenAI)
     ├── AnthropicProvider         (first-party Anthropic Claude)
     ├── GeminiProvider            (first-party Google Gemini)
     ├── OllamaProvider            (local LLM)
     ├── CustomProvider            (OpenAI-compatible custom endpoint)
     ├── OpenAICompatibleProvider  (deepseek, mistral, groq, together, ... 28 others)
     ├── VercelAIGatewayProvider   (single-key aggregator)
     ├── CohereProvider            (Task 4-c)
     ├── VoyageProvider            (embeddings only — Task 4-c)
     ├── StabilityProvider         (image generation — Task 4-c)
     ├── ReplicateProvider         (Task 4-c)
     ├── CloudflareProvider        (Task 4-c)
     ├── AWSBedrockProvider        (also reused for amazon_nova — Task 4-c)
     ├── GoogleVertexProvider      (Task 4-c)
     ├── AzureAIProvider           (Task 4-c)
     ├── IBMWatsonxProvider        (Task 4-c)
     └── DatabricksProvider        (Task 4-c)
"""

from __future__ import annotations

from .base import (
    AIProvider,
    AIProviderConfig,
    OpenAIProvider,
    AnthropicProvider,
    GeminiProvider,
    OllamaProvider,
    CustomProvider,
    get_provider,
    get_provider_from_credentials,
    list_providers,
    chat_completion,
)
from .sdk_providers import (
    CohereProvider,
    VoyageProvider,
    StabilityProvider,
    ReplicateProvider,
    CloudflareProvider,
    AWSBedrockProvider,
    GoogleVertexProvider,
    AzureAIProvider,
    IBMWatsonxProvider,
    DatabricksProvider,
)

__all__ = [
    "AIProvider",
    "AIProviderConfig",
    "OpenAIProvider",
    "AnthropicProvider",
    "GeminiProvider",
    "OllamaProvider",
    "CustomProvider",
    "CohereProvider",
    "VoyageProvider",
    "StabilityProvider",
    "ReplicateProvider",
    "CloudflareProvider",
    "AWSBedrockProvider",
    "GoogleVertexProvider",
    "AzureAIProvider",
    "IBMWatsonxProvider",
    "DatabricksProvider",
    "get_provider",
    "get_provider_from_credentials",
    "list_providers",
    "chat_completion",
]
