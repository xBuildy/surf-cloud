/**
 * Surf Cloud v2 — Wave OS Backend Function (Per-User Sessions)
 * 
 * Each Wave OS user gets their own isolated browser context.
 * The user_id is passed on every request to route to the right session.
 * 
 * Usage:
 *   POST /api/functions/surfAutomateV2
 *   {
 *     "action": "automate",
 *     "user_id": "wave_user_123",   // REQUIRED — routes to isolated session
 *     "steps": [...],
 *     "session": "wave_os_default",
 *     "surf_url": "https://surf-cloud-production.up.railway.app",
 *     "surf_api_key": "..."
 *   }
 */

export async function surfAutomateV2(req, res) {
  const SURF_URL = req.body.surf_url || process.env.SURF_CLOUD_URL || 'https://surf-cloud-production.up.railway.app';
  const SURF_API_KEY = req.body.surf_api_key || process.env.SURF_API_KEY || 'surf-default-key';

  const action = req.body.action || 'automate';
  const userId = req.body.user_id || '';
  const session = req.body.session || '';

  if (!userId && action !== 'health') {
    return res.status(400).json({
      error: 'user_id is required for all actions (except health)',
      message: 'Each Wave OS user needs their own isolated browser session.'
    });
  }

  try {
    let response;
    const baseBody = { api_key: SURF_API_KEY, user_id: userId };

    switch (action) {
      // ═══ Session Management ═══
      case 'session-create': {
        response = await fetch(`${SURF_URL}/api/session/create`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(baseBody)
        });
        break;
      }

      case 'session-destroy': {
        response = await fetch(`${SURF_URL}/api/session/destroy`, {
          method: 'DELETE',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(baseBody)
        });
        break;
      }

      case 'sessions-list': {
        response = await fetch(`${SURF_URL}/api/sessions?api_key=${SURF_API_KEY}`);
        break;
      }

      case 'session-info': {
        response = await fetch(`${SURF_URL}/api/session/info?api_key=${SURF_API_KEY}&user_id=${userId}`);
        break;
      }

      // ═══ Page Management ═══
      case 'page-new': {
        response = await fetch(`${SURF_URL}/api/page/new`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ ...baseBody, url: req.body.url || 'about:blank' })
        });
        break;
      }

      case 'pages-list': {
        response = await fetch(`${SURF_URL}/api/pages?api_key=${SURF_API_KEY}&user_id=${userId}`);
        break;
      }

      // ═══ Multi-step automation ═══
      case 'automate': {
        const steps = req.body.steps || [];
        response = await fetch(`${SURF_URL}/api/automate`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ ...baseBody, steps, session })
        });
        break;
      }

      // ═══ AI Element Resolution ═══
      case 'observe': {
        response = await fetch(`${SURF_URL}/api/observe`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ ...baseBody, instruction: req.body.instruction || '' })
        });
        break;
      }

      case 'act': {
        response = await fetch(`${SURF_URL}/api/act`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ ...baseBody, instruction: req.body.instruction || '', value: req.body.value || '' })
        });
        break;
      }

      case 'extract': {
        response = await fetch(`${SURF_URL}/api/extract`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ ...baseBody, instruction: req.body.instruction || '' })
        });
        break;
      }

      // ═══ Basic Operations ═══
      case 'navigate': {
        response = await fetch(`${SURF_URL}/api/navigate`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ ...baseBody, url: req.body.url || '' })
        });
        break;
      }

      case 'screenshot': {
        response = await fetch(`${SURF_URL}/api/screenshot`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ ...baseBody, full_page: req.body.full_page || false })
        });
        break;
      }

      case 'content': {
        response = await fetch(`${SURF_URL}/api/content`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(baseBody)
        });
        break;
      }

      case 'fill': {
        response = await fetch(`${SURF_URL}/api/fill`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ ...baseBody, selector: req.body.selector || '', text: req.body.text || '' })
        });
        break;
      }

      case 'click': {
        response = await fetch(`${SURF_URL}/api/click`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ ...baseBody, selector: req.body.selector || '' })
        });
        break;
      }

      case 'wait': {
        response = await fetch(`${SURF_URL}/api/wait`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            ...baseBody,
            selector: req.body.selector || '',
            wait_type: req.body.wait_type || 'element',
            timeout_ms: req.body.timeout_ms || 10000
          })
        });
        break;
      }

      // ═══ Session Persistence ═══
      case 'session-save': {
        response = await fetch(`${SURF_URL}/api/session/save`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ ...baseBody, name: req.body.session_name || 'default' })
        });
        break;
      }

      case 'session-load': {
        response = await fetch(`${SURF_URL}/api/session/load`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            ...baseBody,
            name: req.body.session_name || 'default',
            url: req.body.url || ''
          })
        });
        break;
      }

      case 'session-list-saved': {
        response = await fetch(`${SURF_URL}/api/session/list?api_key=${SURF_API_KEY}&user_id=${userId}`);
        break;
      }

      // ═══ Recording ═══
      case 'record-start': {
        response = await fetch(`${SURF_URL}/api/record/start`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ ...baseBody, name: req.body.record_name || '' })
        });
        break;
      }

      case 'record-stop': {
        response = await fetch(`${SURF_URL}/api/record/stop`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ ...baseBody, name: req.body.record_name || '' })
        });
        break;
      }

      case 'record-replay': {
        response = await fetch(`${SURF_URL}/api/record/replay`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ ...baseBody, script: req.body.script || [], speed: req.body.speed || 1.0 })
        });
        break;
      }

      // ═══ PDF Export ═══
      case 'pdf': {
        response = await fetch(`${SURF_URL}/api/pdf`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            ...baseBody,
            format: req.body.format || 'A4',
            landscape: req.body.landscape || false,
            print_background: req.body.print_background !== false
          })
        });
        break;
      }

      // ═══ Health ═══
      case 'health': {
        response = await fetch(`${SURF_URL}/api/health`);
        break;
      }

      default:
        return res.status(400).json({
          error: `Unknown action: ${action}`,
          available_actions: [
            'session-create', 'session-destroy', 'sessions-list', 'session-info',
            'page-new', 'pages-list',
            'automate', 'observe', 'act', 'extract',
            'navigate', 'screenshot', 'content', 'fill', 'click', 'wait',
            'session-save', 'session-load', 'session-list-saved',
            'record-start', 'record-stop', 'record-replay',
            'pdf', 'health'
          ]
        });
    }

    const data = await response.json();
    return res.json(data);

  } catch (error) {
    console.error('surfAutomateV2 error:', error);
    return res.status(500).json({
      error: 'Surf Cloud v2 request failed',
      message: error.message,
      surf_url: SURF_URL,
      user_id: userId
    });
  }
}
