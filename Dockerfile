FROM debian:bookworm-slim

# Install system dependencies: Chromium, VNC, noVNC, Python, nginx
RUN apt-get update && \
    DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
        chromium \
        xvfb \
        x11vnc \
        novnc \
        websockify \
        python3 \
        python3-pip \
        python3-venv \
        nginx \
        supervisor \
        fonts-liberation \
        fonts-noto-cjk \
        dbus \
        x11-xserver-utils \
        xdotool \
        wmctrl \
        curl \
        ca-certificates

WORKDIR /app

# Copy Python requirements and install
COPY requirements.txt /app/requirements.txt
RUN pip3 install --no-cache-dir --break-system-packages -r /app/requirements.txt

# Install Playwright Chromium with system deps
RUN playwright install chromium --with-deps

# Configure nginx as reverse proxy
COPY nginx.conf /etc/nginx/sites-available/surf
RUN ln -sf /etc/nginx/sites-available/surf /etc/nginx/sites-enabled/surf && \
    rm -f /etc/nginx/sites-enabled/default

# Restore noVNC vnc.html
COPY vnc.html /usr/share/novnc/vnc.html

# Copy application code
COPY . /app

# Ensure start.sh is executable
RUN chmod +x /app/start.sh

# Environment variables
ENV DISPLAY=:99
ENV PORT=8080
ENV API_PORT=8000
ENV SURF_API_KEY=default
ENV THETA_API_URL="https://ai.thetaedgecloud.com/v1"
ENV THETA_API_KEY=""

EXPOSE 8080

CMD ["/app/start.sh"]
