# ============================================================
# Wave Surf — Neko WebRTC + Chromium Browser + CDP API
#
# IMPORTANT: the base m1k1o/neko:chromium image (v3 API) already
# ships a complete, working supervisor setup at /etc/neko/supervisord.conf
# which [include]s /etc/neko/supervisord/*.conf. That existing setup
# already correctly launches: Xorg (dummy display driver), dbus,
# pulseaudio, openbox, chromium, and neko itself — all wired to the
# same DISPLAY (:99.0 by default) and PULSE_SERVER.
#
# Earlier revisions of this Dockerfile threw all of that away and
# reimplemented a second, parallel supervisor stack from scratch
# (own /etc/supervisor/conf.d config, own chromium launch command with
# no display/X-server wiring, own Thorium download). That's why it
# crash-looped: chromium had no X server to attach to, and every
# process kept restarting immediately.
#
# This version is purely ADDITIVE on top of the base image:
#   - chromium.conf   -> overrides the base's own chromium program
#                         definition, only to add CDP remote-debugging
#                         flags (--remote-debugging-port=9222 etc) that
#                         our automation API needs. Same display/openbox
#                         wiring as the base image, untouched.
#   - neko.yaml       -> overrides the base's own neko.yaml, switching
#                         member auth to "noauth" so our iframe embed
#                         doesn't show a login prompt.
#   - cdp-api.conf,
#     nginx-proc.conf -> NEW supervisor program files dropped into the
#                         base image's own include directory, so they
#                         start alongside (not instead of) everything
#                         the base image already runs correctly.
#   - NEKO_SERVER_BIND -> moved from the base image's default :8080 to
#                         :8081, since our nginx now owns the public
#                         8080 port (nginx.conf already expects neko on
#                         127.0.0.1:8081).
#
# We deliberately do NOT override CMD — the base image's own
# `/usr/bin/supervisord -c /etc/neko/supervisord.conf` is correct and
# is what actually starts everything (X server included).
# ============================================================

FROM m1k1o/neko:chromium AS base

USER root

# Only add what the base image doesn't already have: pip (for our
# Python CDP API), nginx (our reverse proxy / public entrypoint), and x11-xserver-utils (for xrandr).
# Everything browser/X11/audio-related is already in the base image.
RUN apt-get update && apt-get install -y \
    python3-pip \
    nginx \
    x11-xserver-utils \
    && apt-get clean

# Override the base image's chromium program def (adds CDP flags) and
# neko.yaml (adds noauth) — see header comment above.
COPY chromium.conf /etc/neko/supervisord/chromium.conf
COPY neko.yaml /etc/neko/neko.yaml

# Override the base image's managed Chrome policy. The base image ships
# /etc/chromium/policies/managed/policies.json with "DeveloperToolsAvailability": 2
# (DevTools DISABLED) — which makes Chrome return -32000 "Not allowed" on
# Target.attachToTarget and silently refuse to service page-level CDP sockets,
# breaking all automation. We overwrite it with DeveloperToolsAvailability=1
# (allowed) + RemoteDebuggingAllowed=true, and drop the force-installed
# extensions we don't want.
COPY policies.json /etc/chromium/policies/managed/policies.json

# New supervisor programs (additive — merge into the base image's own
# /etc/neko/supervisord.conf [include] directory).
COPY cdp-api.conf /etc/neko/supervisord/cdp-api.conf
COPY nginx-proc.conf /etc/neko/supervisord/nginx-proc.conf

# Python dependencies for the CDP API.
# NOTE: version floors (not exact pins) so pip resolves prebuilt wheels
# compatible with this base image's Python 3.13 — exact old pins
# (pydantic==2.5.2 / greenlet==3.0.1 via playwright==1.40.0) had no 3.13
# wheels and pip fell back to building from source, which failed.
RUN pip3 install --no-cache-dir --break-system-packages --ignore-installed \
    "fastapi>=0.115" \
    "uvicorn>=0.30" \
    "playwright>=1.47" \
    "httpx>=0.27" \
    "pydantic>=2.9" \
    "websockets>=13"

RUN mkdir -p /app/api /app/frontend

# CDP Automation API
COPY api_v2.py /app/api/api_v2.py
COPY ai_resolver.py /app/api/ai_resolver.py
COPY session_store.py /app/api/session_store.py

# Custom Wave OS frontend shell
COPY frontend/ /app/frontend/

# nginx site config (public entrypoint on :8080 — proxies to the
# frontend shell, the CDP API on :8000, Neko WebRTC on :8081, and
# Chromium's raw CDP port :9222)
COPY nginx.conf /etc/nginx/sites-available/default
# Also keep a pristine copy as a template. nginx-proc.conf renders this at
# boot, substituting __SURF_API_KEY__ so the shell's /shell-api/ path can
# authenticate to the CDP API without the key ever being in the repo or
# shipped to the browser.
COPY nginx.conf /etc/nginx/nginx.conf.template

# Move Neko off the base image's default :8080 (nginx now owns that
# port) onto :8081, matching what nginx.conf already expects.
ENV NEKO_SERVER_BIND=:8081

EXPOSE 8080 9222

USER root

# CMD intentionally not overridden — inherits the base image's own
# `/usr/bin/supervisord -c /etc/neko/supervisord.conf`, which starts
# Xorg + dbus + pulseaudio + openbox + chromium + neko together
# correctly, plus our two additive programs (cdp-api, nginx).
