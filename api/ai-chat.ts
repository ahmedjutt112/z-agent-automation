// Vercel serverless function — AI chat via Vercel AI Gateway
// POST /api/ai/chat
// body: {messages: [{role, content}], model?, temperature?, max_tokens?}
// → {content, model, usage}
//
// Routes to any of 50+ providers via the single Vercel AI Gateway API key.

const GATEWAY_URL = process.env.VERCEL_AI_GATEWAY_URL || 'https://ai-gateway.vercel.sh/v1';
const GATEWAY_KEY = process.env.VERCEL_AI_GATEWAY_KEY || '';

export default async function handler(req, res) {
  // Enable CORS
  res.setHeader('Access-Control-Allow-Origin', '*');
  res.setHeader('Access-Control-Allow-Methods', 'POST, OPTIONS');
  res.setHeader('Access-Control-Allow-Headers', 'Content-Type');

  if (req.method === 'OPTIONS') {
    return res.status(200).end();
  }

  if (req.method !== 'POST') {
    return res.status(405).json({ error: 'Method not allowed. Use POST.' });
  }

  const { messages, model, temperature, max_tokens } = req.body || {};

  if (!messages || !Array.isArray(messages) || messages.length === 0) {
    return res.status(400).json({ error: 'messages array is required' });
  }

  const useModel = model || 'openai/gpt-4o-mini';
  const useTemp = typeof temperature === 'number' ? temperature : 0.7;
  const useMaxTokens = typeof max_tokens === 'number' ? max_tokens : 1000;

  // Demo mode — no API key configured
  if (!GATEWAY_KEY) {
    const lastMessage = messages[messages.length - 1]?.content || '';
    return res.status(200).json({
      content: `[Demo mode — no VERCEL_AI_GATEWAY_KEY set] You said: ${String(lastMessage).slice(0, 200)}`,
      model: useModel,
      usage: { total_tokens: 0 },
      demo: true,
    });
  }

  // Call Vercel AI Gateway
  try {
    const response = await fetch(`${GATEWAY_URL}/chat/completions`, {
      method: 'POST',
      headers: {
        Authorization: `Bearer ${GATEWAY_KEY}`,
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        model: useModel,
        messages,
        temperature: useTemp,
        max_tokens: useMaxTokens,
      }),
    });

    if (!response.ok) {
      const errorText = await response.text();
      return res.status(response.status).json({
        error: `AI Gateway error: ${response.statusText}`,
        details: errorText.slice(0, 500),
      });
    }

    const data = await response.json();
    const content = data.choices?.[0]?.message?.content || '';
    return res.status(200).json({
      content,
      model: data.model || useModel,
      usage: data.usage || {},
      demo: false,
    });
  } catch (err) {
    return res.status(500).json({
      error: `Failed to call AI Gateway: ${err.message}`,
    });
  }
}
