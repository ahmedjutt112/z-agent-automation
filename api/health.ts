// Vercel serverless function — health check
// GET /api/health → {status, service, version, mock_mode, kill_switch, deployed_on}

export default function handler(req, res) {
  res.status(200).json({
    status: 'ok',
    service: 'z-agent-automation',
    version: '0.1.0',
    mock_mode: true,
    kill_switch: false,
    deployed_on: 'vercel',
    timestamp: new Date().toISOString(),
  });
}
