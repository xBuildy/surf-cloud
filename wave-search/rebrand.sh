#!/bin/sh
# ============================================================
# Wave Search skin + rebrand, applied to the STOCK "simple" theme.
# We do NOT register a custom theme name — that failed SearXNG's
# theme validation (ValidationException: Invalid value "wave").
# Instead: keep ui.default_theme = simple, drop our dark CSS into
# simple's static dir, link it from simple/base.html, and swap the
# hardcoded "SearXNG" wordmark text to "Wave Search".
# Runs at build time; tolerant of both /usr/local/searxng and the
# older /usr/local/searxng-src base-image layouts.
# ============================================================
set -e

CSS_SRC="/tmp/wave-dark.css"

for ROOT in /usr/local/searxng /usr/local/searxng-src; do
  CSSDIR="$ROOT/searx/static/themes/simple/css"
  BH="$ROOT/searx/templates/simple/base.html"

  if [ -d "$CSSDIR" ]; then
    cp "$CSS_SRC" "$CSSDIR/wave-dark.css"
  fi

  if [ -f "$BH" ]; then
    # 1) link our stylesheet just before </head>
    sed -i "s#</head>#<link rel=\"stylesheet\" href=\"{{ url_for('static', filename='themes/simple/css/wave-dark.css') }}\" type=\"text/css\" /></head>#" "$BH" || true
    # 2) rebrand the wordmark + footer "Powered by" text
    sed -i "s/>SearXNG</>Wave Search</g" "$BH" || true
    sed -i "s#Powered by <a href=\"/info/en/about\">SearXNG</a>#Powered by <a href=\"/info/en/about\">Wave Search</a>#g" "$BH" || true
  fi

  # 3) swap wordmark anywhere else in the simple templates (macros etc.)
  if [ -d "$ROOT/searx/templates/simple" ]; then
    for f in $(grep -rIl ">SearXNG<" "$ROOT/searx/templates/simple" 2>/dev/null); do
      sed -i "s/>SearXNG</>Wave Search</g" "$f" || true
    done
  fi
done

echo "Wave Search rebrand applied."
