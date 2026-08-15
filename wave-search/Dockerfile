FROM searxng/searxng:latest

# Copy custom settings
COPY searxng-settings.yml /etc/searxng/settings.yml

# Create Wave OS dark theme

# Wave OS dark theme CSS - reskin SearXNG with Wave OS aesthetic

# ============================================================
# Wave OS skin + rebrand applied to the STOCK "simple" theme.
# We do NOT register a custom theme name (that failed validation:
# ValidationException Invalid value: "wave"). Instead we keep
# ui.default_theme: simple and (a) drop our dark CSS into simple's
# static dir, (b) link it from simple/base.html, (c) swap the
# hardcoded "SearXNG" wordmark text to "Wave Search".
# RTOOT is the real runtime path (/usr/local/searxng), with a
# fallback to /usr/local/searxng-src for older base layouts.
# ============================================================

# Write the Wave dark CSS into whichever searx static dir exists.
RUN set -e; \
    for ROOT in /usr/local/searxng /usr/local/searxng-src; do \
      if [ -d "$ROOT/searx/static/themes/simple/css" ]; then \
        mkdir -p "$ROOT/searx/static/themes/simple/css"; \
        cat > "$ROOT/searx/static/themes/simple/css/wave-dark.css" << 'CSSEOF'
:root {
  --wave-bg: #0a0a0b;
  --wave-surface: #131316;
  --wave-border: #1e1e24;
  --wave-text: #e4e4e7;
  --wave-muted: #71717a;
  --wave-accent: #3b82f6;
  --wave-accent-hover: #2563eb;
  --wave-radius: 12px;
  --wave-font: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
}

* { box-sizing: border-box; }

body {
  background: var(--wave-bg) !important;
  color: var(--wave-text) !important;
  font-family: var(--wave-font) !important;
  margin: 0;
  padding: 0;
}

#search_header {
  background: var(--wave-surface) !important;
  border-bottom: 1px solid var(--wave-border) !important;
  padding: 20px 24px !important;
  position: sticky;
  top: 0;
  z-index: 100;
}

#search_header input[type="text"],
#search_header input[type="search"] {
  background: var(--wave-bg) !important;
  border: 1px solid var(--wave-border) !important;
  border-radius: var(--wave-radius) !important;
  color: var(--wave-text) !important;
  padding: 12px 16px !important;
  font-size: 15px !important;
  width: 100% !important;
  max-width: 640px !important;
  outline: none !important;
  transition: border-color 0.2s ease !important;
}

#search_header input:focus {
  border-color: var(--wave-accent) !important;
  box-shadow: 0 0 0 3px rgba(59, 130, 246, 0.15) !important;
}

#search_header button {
  background: var(--wave-accent) !important;
  color: white !important;
  border: none !important;
  border-radius: var(--wave-radius) !important;
  padding: 12px 24px !important;
  font-weight: 500 !important;
  cursor: pointer !important;
  transition: background 0.2s ease !important;
}

#search_header button:hover {
  background: var(--wave-accent-hover) !important;
}

#main_results {
  background: var(--wave-bg) !important;
  padding: 24px !important;
}

.result {
  background: var(--wave-surface) !important;
  border: 1px solid var(--wave-border) !important;
  border-radius: var(--wave-radius) !important;
  padding: 20px !important;
  margin-bottom: 12px !important;
  transition: border-color 0.2s ease !important;
}

.result:hover {
  border-color: var(--wave-accent) !important;
}

.result h3 a {
  color: var(--wave-text) !important;
  text-decoration: none !important;
  font-size: 17px !important;
  font-weight: 600 !important;
}

.result h3 a:hover {
  color: var(--wave-accent) !important;
}

.result .url {
  color: var(--wave-muted) !important;
  font-size: 13px !important;
}

.result .content,
.result .description {
  color: var(--wave-muted) !important;
  font-size: 14px !important;
  line-height: 1.6 !important;
}

#sidebar {
  background: var(--wave-surface) !important;
  border: 1px solid var(--wave-border) !important;
  border-radius: var(--wave-radius) !important;
}

#categories {
  background: var(--wave-surface) !important;
  border-bottom: 1px solid var(--wave-border) !important;
}

#categories label {
  color: var(--wave-muted) !important;
  background: transparent !important;
  border: 1px solid var(--wave-border) !important;
  border-radius: 8px !important;
  padding: 6px 14px !important;
  font-size: 13px !important;
  cursor: pointer !important;
  transition: all 0.2s ease !important;
}

#categories label:hover,
#categories label.active {
  color: var(--wave-accent) !important;
  border-color: var(--wave-accent) !important;
  background: rgba(59, 130, 246, 0.08) !important;
}

a {
  color: var(--wave-accent) !important;
  text-decoration: none !important;
}

a:hover {
  text-decoration: underline !important;
}

#pagination {
  text-align: center !important;
  padding: 24px 0 !important;
}

#pagination a {
  background: var(--wave-surface) !important;
  border: 1px solid var(--wave-border) !important;
  border-radius: 8px !important;
  color: var(--wave-text) !important;
  padding: 8px 16px !important;
  margin: 0 4px !important;
}

#pagination a:hover {
  border-color: var(--wave-accent) !important;
  color: var(--wave-accent) !important;
}

#logo {
  display: none !important;
}

#search_logo {
  display: none !important;
}

.wave-brand {
  font-size: 22px !important;
  font-weight: 700 !important;
  color: var(--wave-text) !important;
  letter-spacing: -0.5px !important;
}

.wave-brand span {
  color: var(--wave-accent) !important;
}

#footer {
  background: var(--wave-surface) !important;
  border-top: 1px solid var(--wave-border) !important;
  color: var(--wave-muted) !important;
  padding: 16px 24px !important;
  text-align: center !important;
  font-size: 12px !important;
}

#footer a {
  color: var(--wave-muted) !important;
}

#answer {
  background: var(--wave-surface) !important;
  border: 1px solid var(--wave-border) !important;
  border-left: 3px solid var(--wave-accent) !important;
  border-radius: var(--wave-radius) !important;
  padding: 20px !important;
  margin-bottom: 16px !important;
}

#infobox {
  background: var(--wave-surface) !important;
  border: 1px solid var(--wave-border) !important;
  border-radius: var(--wave-radius) !important;
}

@media (max-width: 768px) {
  #main_results { padding: 12px !important; }
  .result { padding: 14px !important; }
}
CSSEOF
      fi; \
    done

# Link the CSS from simple/base.html <head>, set page <title>, and
# rebrand the hardcoded SearXNG wordmark + footer to Wave Search.
RUN set -e; \
    for ROOT in /usr/local/searxng /usr/local/searxng-src; do \
      BH="$ROOT/searx/templates/simple/base.html"; \
      [ -f "$BH" ] || continue; \
      # inject stylesheet link + title override just before </head>
      sed -i 's#</head>#<link rel="stylesheet" href="{{ url_for('"'"'static'"'"', filename='"'"'themes/simple/css/wave-dark.css'"'"') }}" type="text/css" /></head>#' "$BH" || true; \
      # swap wordmark text (title h1) and footer "Powered by" line
      sed -i 's/>SearXNG</>Wave Search</g' "$BH" || true; \
      sed -i 's#Powered by <a href="/info/en/about">SearXNG</a>#Powered by <a href="/info/en/about">Wave Search</a>#g' "$BH" || true; \
    done; \
    # also swap wordmark anywhere else in simple templates (macros, etc.)
    for ROOT in /usr/local/searxng /usr/local/searxng-src; do \
      [ -d "$ROOT/searx/templates/simple" ] || continue; \
      grep -rIl ">SearXNG<" "$ROOT/searx/templates/simple" 2>/dev/null | while read f; do \
        sed -i 's/>SearXNG</>Wave Search</g' "$f" || true; \
      done; \
    done

EXPOSE 8080

CMD ["uwsgi", "--http", "0.0.0.0:8080", "--wsgi-file", "searx/webapp.py", "--master", "--processes", "4", "--threads", "2"]
