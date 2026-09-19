// Vercel serverless function — list AI providers + models
// GET /api/providers → {providers: [{name, display_name, ...}], count}
// GET /api/ai/models → {models: [...], count} (live from gateway if key set)

const GATEWAY_KEY = process.env.VERCEL_AI_GATEWAY_KEY || '';
const GATEWAY_URL = process.env.VERCEL_AI_GATEWAY_URL || 'https://ai-gateway.vercel.sh/v1';

const DEMO_PROVIDERS = [
  { name: 'openai', display_name: 'OpenAI', openai_compatible: true, default_model: 'gpt-4o-mini' },
  { name: 'anthropic', display_name: 'Anthropic Claude', openai_compatible: false, default_model: 'claude-3-5-sonnet' },
  { name: 'google', display_name: 'Google Gemini', openai_compatible: false, default_model: 'gemini-1.5-flash' },
  { name: 'deepseek', display_name: 'DeepSeek', openai_compatible: true, default_model: 'deepseek-chat' },
  { name: 'mistral', display_name: 'Mistral AI', openai_compatible: true, default_model: 'mistral-large-latest' },
  { name: 'xai', display_name: 'xAI Grok', openai_compatible: true, default_model: 'grok-2' },
  { name: 'groq', display_name: 'Groq', openai_compatible: true, default_model: 'llama-3.3-70b-versatile' },
  { name: 'together', display_name: 'Together AI', openai_compatible: true, default_model: 'meta/llama-3.1-70b-instruct' },
  { name: 'fireworks', display_name: 'Fireworks AI', openai_compatible: true, default_model: 'accounts/fireworks/models/llama-v3-70b-instruct' },
  { name: 'perplexity', display_name: 'Perplexity', openai_compatible: true, default_model: 'llama-3.1-sonar-large-128k-online' },
  { name: 'cohere', display_name: 'Cohere', openai_compatible: false, default_model: 'command-r-plus' },
  { name: 'meta', display_name: 'Meta Llama', openai_compatible: true, default_model: 'llama-3.1-70b-instruct' },
  { name: 'vercel_gateway', display_name: 'Vercel AI Gateway (all providers)', openai_compatible: true, default_model: 'openai/gpt-4o-mini' },
];

export default async function handler(req, res) {
  res.setHeader('Access-Control-Allow-Origin', '*');
  res.setHeader('Access-Control-Allow-Methods', 'GET, OPTIONS');
  res.setHeader('Access-Control-Allow-Headers', 'Content-Type');

  if (req.method === 'OPTIONS') {
    return res.status(200).end();
  }

  // If /api/ai/models route + we have a gateway key, fetch live models
  const url = req.url || '';
  if (url.includes('models') && GATEWAY_KEY) {
    try {
      const response = await fetch(`${GATEWAY_URL}/models`, {
        headers: { Authorization: `Bearer ${GATEWAY_KEY}` },
      });
      if (response.ok) {
        const data = await response.json();
        const models = data.data || data.models || [];
        return res.status(200).json({
          models: models.slice(0, 50),
          count: models.length,
          source: 'vercel_gateway',
        });
      }
    } catch (err) {
      // fall through to demo response
    }
  }

  return res.status(200).json({
    providers: DEMO_PROVIDERS.map(p => ({
      ...p,
      has_credential: p.name === 'vercel_gateway' ? !!GATEWAY_KEY : false,
    })),
    count: DEMO_PROVIDERS.length,
    demo: !GATEWAY_KEY,
  });
}
