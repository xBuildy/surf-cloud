#!/bin/bash
# Surf Cloud v2 — noVNC Branding Injection
# Run during Docker build to customize the noVNC viewer with Wave OS branding
# The jlesage/chromium base uses noVNC at /opt/noVNC

set -e

NOVNC_DIR="${1:-/opt/noVNC}"
CUSTOM_DIR="/app/novnc-custom"

echo "[Surf Cloud v2] Applying noVNC branding..."

# 1. Inject custom CSS into noVNC viewer
CSS_FILE="$NOVNC_DIR/app/styles/base.css"
if [ -f "$CSS_FILE" ]; then
    cat >> "$CSS_FILE" << 'SURF_CSS'

/* === Surf Cloud v2 Branding === */
body {
  background: #0a0a0c !important;
  font-family: 'WixMadefor', -apple-system, sans-serif !important;
}

.noVNC_status {
  background: linear-gradient(135deg, #00d8c0 0%, #0d4a5c 100%) !important;
  color: #ffffff !important;
  font-weight: 600 !important;
}

.noVNC_connect_button {
  display: none !important;
}

.noVNC_buttons {
  background: #111216 !important;
  border: 1px solid #1a1a20 !important;
  border-radius: 8px !important;
}

.noVNC_canvas {
  background: #0a0a0c !important;
}

/* Loading screen */
.surf-loading {
  position: fixed;
  top: 50%;
  left: 50%;
  transform: translate(-50%, -50%);
  text-align: center;
  color: #00d8c0;
  font-family: sans-serif;
  z-index: 9999;
}

.surf-loading p {
  margin: 8px 0;
  font-size: 18px;
}

.surf-loading .surf-loading-text {
  font-size: 14px;
  color: #666;
}

.surf-logo svg {
  animation: surf-pulse 2s ease-in-out infinite;
}

@keyframes surf-pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.5; }
}
SURF_CSS
    echo "  ✓ CSS branding injected"
else
    echo "  ⚠ noVNC CSS not found at $CSS_FILE, skipping"
fi

# 2. Inject auto-connect + loading screen into noVNC HTML
HTML_FILE="$NOVNC_DIR/vnc.html"
if [ -f "$HTML_FILE" ]; then
    # Add loading screen div
    sed -i 's|<body>|<body>\n<div class="surf-loading" id="surfLoading"><div class="surf-logo"><svg width="48" height="48" viewBox="0 0 48 48" fill="none"><path d="M4 24 Q12 12, 24 24 T44 24" stroke="#00d8c0" stroke-width="3" fill="none"/><path d="M4 30 Q12 18, 24 30 T44 30" stroke="#00d8c0" stroke-width="2" fill="none" opacity="0.6"/><path d="M4 18 Q12 6, 24 18 T44 18" stroke="#00d8c0" stroke-width="2" fill="none" opacity="0.4"/></svg></div><p>Surf Cloud</p><p class="surf-loading-text">Starting browser...</p></div>|' "$HTML_FILE"

    # Add auto-connect script before </body>
    sed -i 's|</body>|<script>setTimeout(function(){var l=document.getElementById("surfLoading");if(l)l.style.display="none";UI.connect();},1000);</script>\n</body>|' "$HTML_FILE"

    echo "  ✓ Auto-connect + loading screen injected"
else
    echo "  ⚠ noVNC HTML not found at $HTML_FILE, skipping"
fi

# 3. Update page title
INDEX_FILE="$NOVNC_DIR/index.html"
if [ -f "$INDEX_FILE" ]; then
    sed -i 's|<title>.*</title>|<title>Surf Cloud — Wave OS Browser</title>|' "$INDEX_FILE"
    echo "  ✓ Page title updated"
fi

echo "[Surf Cloud v2] Branding complete."
