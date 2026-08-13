FROM jlesage/chromium

# Install Node.js 20.x, Python, nginx, and dependencies
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        curl \
        ca-certificates \
        gnupg \
        python3 \
        python3-pip \
        nginx \
        supervisor && \
    curl -fsSL https://deb.nodesource.com/setup_20.x | bash - && \
    apt-get install -y --no-install-recommends nodejs && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy Python requirements and install Python dependencies
COPY requirements.txt /app/requirements.txt
RUN pip3 install --no-cache-dir --break-system-packages -r /app/requirements.txt

# Install Playwright Chromium with system dependencies
RUN playwright install chromium --with-deps && \
    rm -rf /var/lib/apt/lists/*

# Configure nginx as reverse proxy
COPY nginx.conf /etc/nginx/sites-available/surf
RUN rm -f /etc/nginx/sites-enabled/default && \
    ln -s /etc/nginx/sites-available/surf /etc/nginx/sites-enabled/surf

# Copy application code
COPY . /app

# Add S6 services for nginx and the API
RUN mkdir -p /etc/services.d/surf-nginx /etc/services.d/surf-api

COPY services/surf-nginx/run /etc/services.d/surf-nginx/run
COPY services/surf-api/run /etc/services.d/surf-api/run
RUN chmod +x /etc/services.d/surf-nginx/run /etc/services.d/surf-api/run

# Enable CDP in Chromium (localhost only — never expose publicly) with remote allow origins
ENV CHROME_CLI_ARGS="--remote-debugging-port=9222 --remote-debugging-address=127.0.0.1 --remote-allow-origins=*"

# Default environment variables
ENV THETA_API_URL="https://ai.thetaedgecloud.com/v1" \
    THETA_API_KEY="" \
    SURF_API_KEY="default"

# Volume for persistent browser profiles
VOLUME ["/config/browser-profiles"]

# Railway uses PORT env var
ENV PORT=8080

EXPOSE 8080
