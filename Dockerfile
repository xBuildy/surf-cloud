FROM jlesage/chromium

# Install Python, nginx, and dependencies
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        python3 \
        python3-pip \
        nginx \
        supervisor && \
    pip3 install --no-cache-dir --break-system-packages \
        fastapi \
        uvicorn[standard] \
        websocket-client \
        httpx && \
    rm -rf /var/lib/apt/lists/*

# Configure nginx as reverse proxy
COPY nginx.conf /etc/nginx/sites-available/surf
RUN rm -f /etc/nginx/sites-enabled/default && \
    ln -s /etc/nginx/sites-available/surf /etc/nginx/sites-enabled/surf

# Copy the automation API
COPY api.py /app/api.py

# Add S6 services for nginx and the API
RUN mkdir -p /etc/services.d/surf-nginx /etc/services.d/surf-api

COPY services/surf-nginx/run /etc/services.d/surf-nginx/run
COPY services/surf-api/run /etc/services.d/surf-api/run
RUN chmod +x /etc/services.d/surf-nginx/run /etc/services.d/surf-api/run

# Enable CDP in Chromium (localhost only — never expose publicly)
ENV CHROME_CLI_ARGS="--remote-debugging-port=9222 --remote-debugging-address=127.0.0.1"

# Railway uses PORT env var
ENV PORT=8080

EXPOSE 8080
