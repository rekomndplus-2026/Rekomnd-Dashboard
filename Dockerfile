FROM mcr.microsoft.com/playwright/python:v1.44.0-jammy

RUN apt-get update && \
    curl -fsSL https://deb.nodesource.com/setup_20.x | bash - && \
    apt-get install -y nodejs nginx gettext-base && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

ARG CACHE_DATE=20260717

# Force fresh copy with --link to bypass Railway stale cache
COPY --link . /app

# Flatten: copy all requirements to a known location so we never hit missing-path errors
RUN mkdir -p /reqs && \
    cp /app/rekomnd_plus/requirements.txt                    /reqs/rekomnd_plus.txt       2>/dev/null || true && \
    cp /app/fb-auto-poster/requirements.txt                  /reqs/fb_poster.txt          2>/dev/null || true && \
    cp /app/fb-commenter-v2/requirements.txt                 /reqs/fb_commenter.txt       2>/dev/null || true && \
    cp /app/fb_buyers_egypt/requirements.txt                 /reqs/fb_buyers.txt          2>/dev/null || true && \
    find /app/whatsapp-bulk-sender -name "requirements.txt" -exec cp {} /reqs/wa_sender.txt \; 2>/dev/null || true

# Install all dependencies
RUN pip install --no-cache-dir -r /reqs/rekomnd_plus.txt || true
RUN pip install --no-cache-dir -r /reqs/fb_poster.txt || true
RUN pip install --no-cache-dir -r /reqs/fb_commenter.txt || true
RUN pip install --no-cache-dir -r /reqs/fb_buyers.txt || true
RUN pip install --no-cache-dir -r /reqs/wa_sender.txt

# Force compatible versions (base image ships old fastapi)
RUN pip install --no-cache-dir "fastapi==0.111.0" "pydantic==2.7.1" "pydantic-settings==2.2.1" "uvicorn==0.29.0"

# Install Node dependencies and Playwright browsers
RUN cd /app/whatsapp-bulk-sender/wa-server && npm install
RUN playwright install --with-deps chromium || true

# Configure Nginx
RUN cp /app/nginx.conf.template /etc/nginx/nginx.conf.template
RUN cp /app/start.sh /start.sh && chmod +x /start.sh

EXPOSE 80

CMD ["/start.sh"]
