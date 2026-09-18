"""Top-level ``ai_providers`` package — registry of supported AI providers.

This package lives *outside* the ``automation_service`` Python package so it
can be imported by both the ``zai`` CLI (in :mod:`app.main`) and the
automation-service itself (in :mod:`automation_service.ai_providers.base`).

The :data:`PROVIDERS` dict is the **single source of truth** for the 51 AI
providers this project supports (master prompt §6 — originally 5 providers,
expanded to 50+). Each entry maps a provider slug to a dict of metadata:

    {
        "display_name":        str,         # human-readable
        "base_url":            str | None,  # OpenAI-compatible base URL, if any
        "env_key":             str | None,  # credential service name (resolved via get_credential)
        "docs_url":            str,         # provider documentation
        "openai_compatible":   bool,        # whether OpenAICompatibleProvider works
        "supports_model_list": bool,        # whether GET {base_url}/models works
        "default_model":       str,         # sensible default model id
        "notes":              str,         # free-form notes for non-OpenAI-compatible providers
    }

Importing this module is dependency-free (pure dict literal) so it is safe
to load from anywhere — the ``zai`` CLI, the FastAPI service, or tests.
"""

from __future__ import annotations


# ---------------------------------------------------------------------------
# 51 AI providers (master prompt §6, expanded scope)
# ---------------------------------------------------------------------------


PROVIDERS: dict[str, dict] = {
    # ---- Tier 1 — first-party direct APIs ----
    "openai": {
        "display_name": "OpenAI",
        "base_url": "https://api.openai.com/v1",
        "env_key": "openai_api_key",
        "docs_url": "https://platform.openai.com/docs",
        "openai_compatible": True,
        "supports_model_list": True,
        "default_model": "gpt-4o-mini",
        "notes": "First-party. Handled by OpenAIProvider in base.py.",
    },
    "anthropic": {
        "display_name": "Anthropic (Claude)",
        "base_url": "https://api.anthropic.com",
        "env_key": "anthropic_api_key",
        "docs_url": "https://docs.anthropic.com",
        "openai_compatible": False,
        "supports_model_list": False,
        "default_model": "claude-3-5-sonnet-20241022",
        "notes": "Uses the anthropic SDK (Messages API). Handled by AnthropicProvider in base.py.",
    },
    "gemini": {
        "display_name": "Google Gemini",
        "base_url": "https://generativelanguage.googleapis.com",
        "env_key": "gemini_api_key",
        "docs_url": "https://ai.google.dev/docs",
        "openai_compatible": False,
        "supports_model_list": True,
        "default_model": "gemini-1.5-flash",
        "notes": "Uses the google-generativeai SDK. Handled by GeminiProvider in base.py.",
    },
    "deepseek": {
        "display_name": "DeepSeek",
        "base_url": "https://api.deepseek.com/v1",
        "env_key": "deepseek_api_key",
        "docs_url": "https://api-docs.deepseek.com",
        "openai_compatible": True,
        "supports_model_list": True,
        "default_model": "deepseek-chat",
        "notes": "OpenAI-compatible.",
    },
    "mistral": {
        "display_name": "Mistral AI",
        "base_url": "https://api.mistral.ai/v1",
        "env_key": "mistral_api_key",
        "docs_url": "https://docs.mistral.ai",
        "openai_compatible": True,
        "supports_model_list": True,
        "default_model": "mistral-large-latest",
        "notes": "OpenAI-compatible.",
    },
    "xai": {
        "display_name": "xAI (Grok)",
        "base_url": "https://api.x.ai/v1",
        "env_key": "xai_api_key",
        "docs_url": "https://docs.x.ai",
        "openai_compatible": True,
        "supports_model_list": True,
        "default_model": "grok-2-latest",
        "notes": "OpenAI-compatible.",
    },
    "cohere": {
        "display_name": "Cohere",
        "base_url": "https://api.cohere.ai/v1",
        "env_key": "cohere_api_key",
        "docs_url": "https://docs.cohere.com",
        "openai_compatible": False,
        "supports_model_list": True,
        "default_model": "command-r-plus",
        "notes": "Uses the cohere SDK (Chat API).",
    },
    "groq": {
        "display_name": "Groq",
        "base_url": "https://api.groq.com/openai/v1",
        "env_key": "groq_api_key",
        "docs_url": "https://console.groq.com/docs",
        "openai_compatible": True,
        "supports_model_list": True,
        "default_model": "llama-3.3-70b-versatile",
        "notes": "OpenAI-compatible.",
    },
    "together": {
        "display_name": "Together AI",
        "base_url": "https://api.together.xyz/v1",
        "env_key": "together_api_key",
        "docs_url": "https://docs.together.ai",
        "openai_compatible": True,
        "supports_model_list": True,
        "default_model": "meta-llama/Llama-3.3-70B-Instruct-Turbo",
        "notes": "OpenAI-compatible.",
    },
    "fireworks": {
        "display_name": "Fireworks AI",
        "base_url": "https://api.fireworks.ai/inference/v1",
        "env_key": "fireworks_api_key",
        "docs_url": "https://docs.fireworks.ai",
        "openai_compatible": True,
        "supports_model_list": True,
        "default_model": "accounts/fireworks/models/llama-v3p1-70b-instruct",
        "notes": "OpenAI-compatible.",
    },
    "cerebras": {
        "display_name": "Cerebras",
        "base_url": "https://api.cerebras.ai/v1",
        "env_key": "cerebras_api_key",
        "docs_url": "https://inference-docs.cerebras.ai",
        "openai_compatible": True,
        "supports_model_list": True,
        "default_model": "llama-3.3-70b",
        "notes": "OpenAI-compatible.",
    },
    "sambanova": {
        "display_name": "SambaNova",
        "base_url": "https://api.sambanova.ai/v1",
        "env_key": "sambanova_api_key",
        "docs_url": "https://docs.sambanova.ai",
        "openai_compatible": True,
        "supports_model_list": True,
        "default_model": "Meta-Llama-3.1-70B-Instruct",
        "notes": "OpenAI-compatible.",
    },
    "ai21": {
        "display_name": "AI21 Labs",
        "base_url": "https://api.ai21.com/studio/v1",
        "env_key": "ai21_api_key",
        "docs_url": "https://docs.ai21.com",
        "openai_compatible": False,
        "supports_model_list": False,
        "default_model": "jamba-1-5-large",
        "notes": "Uses the ai21 SDK (Studio API).",
    },
    "perplexity": {
        "display_name": "Perplexity",
        "base_url": "https://api.perplexity.ai",
        "env_key": "perplexity_api_key",
        "docs_url": "https://docs.perplexity.ai",
        "openai_compatible": True,
        "supports_model_list": True,
        "default_model": "llama-3.1-sonar-large-128k-online",
        "notes": "OpenAI-compatible.",
    },
    "openrouter": {
        "display_name": "OpenRouter",
        "base_url": "https://openrouter.ai/api/v1",
        "env_key": "openrouter_api_key",
        "docs_url": "https://openrouter.ai/docs",
        "openai_compatible": True,
        "supports_model_list": True,
        "default_model": "openai/gpt-4o-mini",
        "notes": "OpenAI-compatible aggregator.",
    },
    "huggingface": {
        "display_name": "Hugging Face Inference",
        "base_url": "https://api-inference.huggingface.co/v1",
        "env_key": "huggingface_api_key",
        "docs_url": "https://huggingface.co/docs/api-inference",
        "openai_compatible": True,
        "supports_model_list": True,
        "default_model": "meta-llama/Llama-3.3-70B-Instruct",
        "notes": "OpenAI-compatible (router endpoint).",
    },
    "nvidia_nim": {
        "display_name": "NVIDIA NIM",
        "base_url": "https://integrate.api.nvidia.com/v1",
        "env_key": "nvidia_nim_api_key",
        "docs_url": "https://docs.api.nvidia.com",
        "openai_compatible": True,
        "supports_model_list": True,
        "default_model": "meta/llama-3.1-70b-instruct",
        "notes": "OpenAI-compatible.",
    },
    "cloudflare": {
        "display_name": "Cloudflare Workers AI",
        "base_url": "https://api.cloudflare.com/client/v4/accounts",
        "env_key": "cloudflare_ai_api_key",
        "docs_url": "https://developers.cloudflare.com/workers-ai",
        "openai_compatible": False,
        "supports_model_list": False,
        "default_model": "@cf/meta/llama-3.1-70b-instruct",
        "notes": "Uses the Cloudflare REST API. Requires account_id in base_url.",
    },
    "aws_bedrock": {
        "display_name": "AWS Bedrock",
        "base_url": None,
        "env_key": "aws_access_key_id",
        "docs_url": "https://docs.aws.amazon.com/bedrock",
        "openai_compatible": False,
        "supports_model_list": False,
        "default_model": "anthropic.claude-3-5-sonnet-20241022-v2:0",
        "notes": "Uses boto3 (AWS SDK). Requires AWS_ACCESS_KEY_ID + AWS_SECRET_ACCESS_KEY.",
    },
    "google_vertex": {
        "display_name": "Google Vertex AI",
        "base_url": None,
        "env_key": "google_vertex_project_id",
        "docs_url": "https://cloud.google.com/vertex-ai/docs",
        "openai_compatible": False,
        "supports_model_list": False,
        "default_model": "gemini-1.5-flash",
        "notes": "Uses the google-cloud-aiplatform SDK. Requires GOOGLE_VERTEX_PROJECT_ID + GOOGLE_APPLICATION_CREDENTIALS.",
    },
    "azure_ai": {
        "display_name": "Azure AI Foundry",
        "base_url": None,
        "env_key": "azure_ai_endpoint",
        "docs_url": "https://learn.microsoft.com/azure/ai-services",
        "openai_compatible": False,
        "supports_model_list": False,
        "default_model": "gpt-4o",
        "notes": "Uses the azure-ai-ml SDK. Requires AZURE_AI_ENDPOINT + AZURE_AI_KEY.",
    },
    "ibm_watsonx": {
        "display_name": "IBM watsonx.ai",
        "base_url": "https://us-south.ml.cloud.ibm.com",
        "env_key": "ibm_watsonx_api_key",
        "docs_url": "https://dataplatform.cloud.ibm.com/docs/content/wsj/analyze-data/watsonxai.html",
        "openai_compatible": False,
        "supports_model_list": False,
        "default_model": "ibm/granite-3-8b-instruct",
        "notes": "Uses the ibm-watsonx-ai SDK. Requires IBM_WATSONX_API_KEY + IBM_WATSONX_PROJECT_ID.",
    },
    "replicate": {
        "display_name": "Replicate",
        "base_url": "https://api.replicate.com/v1",
        "env_key": "replicate_api_key",
        "docs_url": "https://replicate.com/docs",
        "openai_compatible": False,
        "supports_model_list": False,
        "default_model": "meta/llama-3.1-70b-instruct",
        "notes": "Uses the replicate SDK (predictions API).",
    },
    "stability": {
        "display_name": "Stability AI",
        "base_url": "https://api.stability.ai/v1",
        "env_key": "stability_api_key",
        "docs_url": "https://platform.stability.ai/docs",
        "openai_compatible": False,
        "supports_model_list": False,
        "default_model": "stable-image-core",
        "notes": "Uses the stability SDK (image generation). Not a chat-completions API.",
    },
    "voyage": {
        "display_name": "Voyage AI",
        "base_url": "https://api.voyageai.com/v1",
        "env_key": "voyage_api_key",
        "docs_url": "https://docs.voyageai.com",
        "openai_compatible": False,
        "supports_model_list": False,
        "default_model": "voyage-3-large",
        "notes": "Uses the voyageai SDK (embeddings API). Not a chat-completions API.",
    },
    "jina": {
        "display_name": "Jina AI",
        "base_url": "https://api.jina.ai/v1",
        "env_key": "jina_api_key",
        "docs_url": "https://jina.ai/api",
        "openai_compatible": False,
        "supports_model_list": False,
        "default_model": "jina-embeddings-v3",
        "notes": "Uses the Jina HTTP API (embeddings + rerankers).",
    },
    "nocipium": {
        "display_name": "Nocipium",
        "base_url": "https://api.nocipium.com/v1",
        "env_key": "nocipium_api_key",
        "docs_url": "https://nocipium.com/docs",
        "openai_compatible": False,
        "supports_model_list": False,
        "default_model": "nocipium-default",
        "notes": "Proprietary HTTP API. Provider specifics unverified — placeholder.",
    },
    "lepton": {
        "display_name": "Lepton AI",
        "base_url": "https://api.lepton.ai/v1",
        "env_key": "lepton_api_key",
        "docs_url": "https://www.lepton.ai/docs",
        "openai_compatible": True,
        "supports_model_list": True,
        "default_model": "llama3-70b",
        "notes": "OpenAI-compatible.",
    },
    "friendliai": {
        "display_name": "FriendliAI",
        "base_url": "https://api.friendli.ai/v1",
        "env_key": "friendliai_api_key",
        "docs_url": "https://docs.friendli.ai",
        "openai_compatible": True,
        "supports_model_list": True,
        "default_model": "meta-llama-3.1-70b-instruct",
        "notes": "OpenAI-compatible.",
    },
    "baseten": {
        "display_name": "Baseten",
        "base_url": "https://inference.baseten.co/v1",
        "env_key": "baseten_api_key",
        "docs_url": "https://docs.baseten.co",
        "openai_compatible": True,
        "supports_model_list": True,
        "default_model": "llama-3.1-70b-instruct",
        "notes": "OpenAI-compatible.",
    },
    "modal": {
        "display_name": "Modal Labs",
        "base_url": "https://modal.com/v1",
        "env_key": "modal_api_key",
        "docs_url": "https://modal.com/docs",
        "openai_compatible": True,
        "supports_model_list": True,
        "default_model": "llama-3.1-70b",
        "notes": "OpenAI-compatible endpoint (serverless GPU host).",
    },
    "anyscale": {
        "display_name": "Anyscale Endpoints",
        "base_url": "https://api.endpoints.anyscale.com/v1",
        "env_key": "anyscale_api_key",
        "docs_url": "https://docs.anyscale.com",
        "openai_compatible": True,
        "supports_model_list": True,
        "default_model": "meta-llama/Llama-3.1-70B-Instruct",
        "notes": "OpenAI-compatible.",
    },
    "databricks": {
        "display_name": "Databricks Foundation Models",
        "base_url": None,
        "env_key": "databricks_token",
        "docs_url": "https://docs.databricks.com/machine-learning/foundation-models",
        "openai_compatible": False,
        "supports_model_list": False,
        "default_model": "databricks-dbrx-instruct",
        "notes": "Uses the databricks-sdk. Requires DATABRICKS_HOST + DATABRICKS_TOKEN.",
    },
    "ai2": {
        "display_name": "Allen Institute for AI (AI2)",
        "base_url": "https://api.allenai.org/v1",
        "env_key": "ai2_api_key",
        "docs_url": "https://allenai.org",
        "openai_compatible": False,
        "supports_model_list": False,
        "default_model": "olmo-2-1124-7b-instruct",
        "notes": "Proprietary HTTP API for OLMo models.",
    },
    "aleph_alpha": {
        "display_name": "Aleph Alpha",
        "base_url": "https://api.aleph-alpha.com/v1",
        "env_key": "aleph_alpha_api_key",
        "docs_url": "https://docs.aleph-alpha.com",
        "openai_compatible": True,
        "supports_model_list": True,
        "default_model": "llama-3.1-70b-instruct",
        "notes": "OpenAI-compatible (Luminous API also exposes OpenAI-compatible endpoint).",
    },
    "writer": {
        "display_name": "Writer",
        "base_url": "https://api.writer.com/v1",
        "env_key": "writer_api_key",
        "docs_url": "https://dev.writer.com",
        "openai_compatible": True,
        "supports_model_list": True,
        "default_model": "palmyra-x-4",
        "notes": "OpenAI-compatible.",
    },
    "upstage": {
        "display_name": "Upstage",
        "base_url": "https://api.upstage.ai/v1",
        "env_key": "upstage_api_key",
        "docs_url": "https://developers.upstage.ai",
        "openai_compatible": True,
        "supports_model_list": True,
        "default_model": "solar-pro",
        "notes": "OpenAI-compatible.",
    },
    "baichuan": {
        "display_name": "Baichuan AI",
        "base_url": "https://api.baichuan-ai.com/v1",
        "env_key": "baichuan_api_key",
        "docs_url": "https://platform.baichuan-ai.com/docs",
        "openai_compatible": True,
        "supports_model_list": True,
        "default_model": "Baichuan4-Turbo",
        "notes": "OpenAI-compatible.",
    },
    "zhipu": {
        "display_name": "Zhipu AI (GLM)",
        "base_url": "https://open.bigmodel.cn/api/paas/v4",
        "env_key": "zhipu_api_key",
        "docs_url": "https://open.bigmodel.cn/dev/api",
        "openai_compatible": True,
        "supports_model_list": True,
        "default_model": "glm-4-plus",
        "notes": "OpenAI-compatible.",
    },
    "qwen": {
        "display_name": "Alibaba Qwen (DashScope)",
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "env_key": "qwen_api_key",
        "docs_url": "https://help.aliyun.com/zh/dashscope",
        "openai_compatible": True,
        "supports_model_list": True,
        "default_model": "qwen-plus",
        "notes": "OpenAI-compatible (DashScope compatible-mode).",
    },
    "siliconflow": {
        "display_name": "SiliconFlow",
        "base_url": "https://api.siliconflow.cn/v1",
        "env_key": "siliconflow_api_key",
        "docs_url": "https://docs.siliconflow.cn",
        "openai_compatible": True,
        "supports_model_list": True,
        "default_model": "Qwen/Qwen2.5-72B-Instruct",
        "notes": "OpenAI-compatible.",
    },
    "hyperbolic": {
        "display_name": "Hyperbolic",
        "base_url": "https://api.hyperbolic.xyz/v1",
        "env_key": "hyperbolic_api_key",
        "docs_url": "https://docs.hyperbolic.xyz",
        "openai_compatible": True,
        "supports_model_list": True,
        "default_model": "meta-llama/Meta-Llama-3.1-70B-Instruct",
        "notes": "OpenAI-compatible.",
    },
    "nebius": {
        "display_name": "Nebius AI",
        "base_url": "https://api.studio.nebius.ai/v1",
        "env_key": "nebius_api_key",
        "docs_url": "https://docs.nebius.com",
        "openai_compatible": False,
        "supports_model_list": False,
        "default_model": "meta-llama/Meta-Llama-3.1-70B-Instruct",
        "notes": "Proprietary HTTP API (Nebius Studio). Placeholder.",
    },
    "ollama": {
        "display_name": "Ollama (local)",
        "base_url": "http://localhost:11434",
        "env_key": None,
        "docs_url": "https://ollama.com",
        "openai_compatible": False,
        "supports_model_list": True,
        "default_model": "llama3.1",
        "notes": "Local LLM runtime. Handled by OllamaProvider (native /api/chat).",
    },
    "lm_studio": {
        "display_name": "LM Studio (local)",
        "base_url": "http://localhost:1234/v1",
        "env_key": None,
        "docs_url": "https://lmstudio.ai/docs",
        "openai_compatible": False,
        "supports_model_list": True,
        "default_model": "local-model",
        "notes": "Local OpenAI-compatible server (no API key needed). Uses native HTTP API.",
    },
    "meta": {
        "display_name": "Meta (Llama API)",
        "base_url": "https://api.llama.com/v1",
        "env_key": "meta_api_key",
        "docs_url": "https://llama.developer.meta.com",
        "openai_compatible": False,
        "supports_model_list": False,
        "default_model": "Llama-3.3-70B-Instruct",
        "notes": "Proprietary Meta Llama API. Placeholder.",
    },
    "amazon_nova": {
        "display_name": "Amazon Nova (via Bedrock)",
        "base_url": None,
        "env_key": "aws_access_key_id",
        "docs_url": "https://docs.aws.amazon.com/nova",
        "openai_compatible": False,
        "supports_model_list": False,
        "default_model": "amazon.nova-pro-v1:0",
        "notes": "Uses boto3 (AWS Bedrock Runtime). Requires AWS_ACCESS_KEY_ID + AWS_SECRET_ACCESS_KEY.",
    },
    "together_computer": {
        "display_name": "Together Computer (legacy)",
        "base_url": "https://api.together.xyz/v1",
        "env_key": "together_api_key",
        "docs_url": "https://docs.together.ai",
        "openai_compatible": True,
        "supports_model_list": True,
        "default_model": "meta-llama/Llama-3.3-70B-Instruct-Turbo",
        "notes": "OpenAI-compatible (legacy name for 'together').",
    },
    "cerebrium": {
        "display_name": "Cerebrium",
        "base_url": "https://api.cerebrium.ai/v1",
        "env_key": "cerebrium_api_key",
        "docs_url": "https://docs.cerebrium.ai",
        "openai_compatible": True,
        "supports_model_list": True,
        "default_model": "llama-3.1-70b",
        "notes": "OpenAI-compatible (serverless GPU host).",
    },
    "novita": {
        "display_name": "Novita AI",
        "base_url": "https://api.novita.ai/v1/openai",
        "env_key": "novita_api_key",
        "docs_url": "https://docs.novita.ai",
        "openai_compatible": True,
        "supports_model_list": True,
        "default_model": "meta-llama/llama-3.1-70b-instruct",
        "notes": "OpenAI-compatible.",
    },
    "sambanova_cloud": {
        "display_name": "SambaNova Cloud",
        "base_url": "https://api.sambanova.ai/v1",
        "env_key": "sambanova_api_key",
        "docs_url": "https://cloud.sambanova.ai",
        "openai_compatible": False,
        "supports_model_list": False,
        "default_model": "Meta-Llama-3.1-70B-Instruct",
        "notes": "SambaNova Cloud console (separate auth flow from API). Placeholder.",
    },
    # ---- Aggregator gateway ----
    "vercel_gateway": {
        "display_name": "Vercel AI Gateway (aggregator)",
        "base_url": "https://ai-gateway.vercel.sh/v1",
        "env_key": "vercel_ai_gateway_key",
        "docs_url": "https://vercel.com/docs/ai-gateway",
        "openai_compatible": True,
        "supports_model_list": True,
        "default_model": "openai/gpt-4o-mini",
        "notes": "Single API key routes to ALL 50 providers. Model names are prefixed: 'openai/gpt-4o', 'anthropic/claude-3-5-sonnet', etc.",
    },
}


# ---------------------------------------------------------------------------
# Convenience views
# ---------------------------------------------------------------------------


def openai_compatible_names() -> list[str]:
    """Return slugs of all providers that can use the OpenAI-compatible client."""
    return [name for name, info in PROVIDERS.items() if info.get("openai_compatible")]


def non_openai_compatible_names() -> list[str]:
    """Return slugs of all providers that require a bespoke SDK / HTTP API."""
    return [name for name, info in PROVIDERS.items() if not info.get("openai_compatible")]


def supports_model_list_names() -> list[str]:
    """Return slugs of all providers whose model-list endpoint we can call."""
    return [name for name, info in PROVIDERS.items() if info.get("supports_model_list")]


def get_display_name(name: str) -> str:
    """Return the human-readable display name for a provider slug."""
    entry = PROVIDERS.get(name)
    return entry["display_name"] if entry else name


__all__ = [
    "PROVIDERS",
    "openai_compatible_names",
    "non_openai_compatible_names",
    "supports_model_list_names",
    "get_display_name",
]
