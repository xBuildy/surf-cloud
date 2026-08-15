#!/bin/sh
# ============================================================
# Wave Search skin + rebrand, applied to the STOCK "simple" theme.
# We keep ui.default_theme = simple (a custom "wave" theme failed
# SearXNG's theme validation), drop our dark CSS FLAT into simple's
# real served static dir, link it from base.html, and swap the
# "SearXNG" wordmark text to "Wave Search".
#
# KEY FIX: SearXNG's simple theme serves its static files FLAT under
# themes/simple/ (e.g. sxng-ltr.min.css) — there is NO css/ subdir at
# the served path. Earlier builds copied to .../simple/css/wave-dark.css
# which 404'd, so NONE of the CSS applied. We now locate the real dir
# by finding sxng-ltr.min.css and place wave-dark.css right beside it.
# ============================================================
set -e

CSS_SRC="/tmp/wave-dark.css"

# Locate every real served static "simple" theme dir (where sxng-ltr.min.css lives).
THEME_DIRS="$(find / -type f -name 'sxng-ltr.min.css' 2>/dev/null | xargs -r -n1 dirname | sort -u)"

echo "Found simple-theme static dirs:"
echo "$THEME_DIRS"

for TDIR in $THEME_DIRS; do
  # Drop the CSS flat, next to sxng-ltr.min.css -> served at themes/simple/wave-dark.css
  cp "$CSS_SRC" "$TDIR/wave-dark.css"
  echo "copied wave-dark.css -> $TDIR/wave-dark.css"
done

# Link the stylesheet + rebrand wordmark in every simple/base.html template.
for BH in $(find / -type f -path '*/templates/simple/base.html' 2>/dev/null); do
  # link our flat stylesheet just before </head> (flat path, no css/ subdir)
  sed -i "s#</head>#<link rel=\"stylesheet\" href=\"{{ url_for('static', filename='themes/simple/wave-dark.css') }}\" type=\"text/css\" /></head>#" "$BH" || true
  # rebrand footer "Powered by" text
  sed -i "s#Powered by <a href=\"/info/en/about\">SearXNG</a>#Powered by <a href=\"/info/en/about\">Wave Search</a>#g" "$BH" || true
  echo "patched $BH"
done

# Swap any remaining ">SearXNG<" wordmark text across all simple templates.
for D in $(find / -type d -path '*/templates/simple' 2>/dev/null); do
  for f in $(grep -rIl ">SearXNG<" "$D" 2>/dev/null); do
    sed -i "s/>SearXNG</>Wave Search</g" "$f" || true
  done
done

echo "Wave Search rebrand applied."
