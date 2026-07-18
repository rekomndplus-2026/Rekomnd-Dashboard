#!/bin/bash

# Railway sets PORT externally — save it for Nginx
NGINX_PORT="${PORT:-80}"
export POSTER_URL="/proxy/poster"
export COMMENTER_URL="/proxy/commenter"
export BUYERS_URL="/proxy/buyers"
export WHATSAPP_URL="/proxy/wa-backend"
export WA_GATEWAY_URL="/proxy/wa-gateway"

echo "=== REKOMND+ Monorepo Container ==="
echo "Nginx PORT=$NGINX_PORT"

# 1. Configure Nginx (need PORT set for envsubst)
PORT="$NGINX_PORT" envsubst '${PORT}' < /etc/nginx/nginx.conf.template > /tmp/nginx.conf
echo "--- Nginx listen line ---"
grep listen /tmp/nginx.conf
echo "--------------------------"

# 2. Start backend services (each with explicit port, overriding Railway's PORT)

PORT=5000 python fb-auto-poster/app.py &
echo "FB Poster :5000"

PORT=5001 python fb-commenter-v2/app.py &
echo "FB Commenter :5001"

uvicorn fb_buyers_egypt.api.server:app --host 127.0.0.1 --port 8000 --no-access-log &
echo "Buyers API :8000"

(cd whatsapp-bulk-sender/whatsapp-bulk-sender/backend && uvicorn main:app --host 127.0.0.1 --port 3001 --no-access-log) &
echo "WA Backend :3001"

(cd whatsapp-bulk-sender/wa-server && PORT=8085 node server.js) &
echo "WA Gateway :8085"

(cd rekomnd_plus && uvicorn main:app --host 127.0.0.1 --port 7070 --no-access-log) &
echo "Dashboard :7070"

sleep 3

# 3. Start Nginx in foreground
echo "Starting Nginx on port $NGINX_PORT..."
exec nginx -c /tmp/nginx.conf
