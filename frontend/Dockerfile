# VibePrompt frontend — static SPA served by nginx, /api proxied to API service.

FROM node:22-bookworm-slim AS build
WORKDIR /src
COPY package.json package-lock.json* ./
RUN npm ci || npm install
COPY . .
RUN npm run build

FROM nginx:1.27-alpine
RUN addgroup -g 10001 -S vibeprompt \
    && adduser -S -D -H -u 10001 -G vibeprompt vibeprompt \
    && mkdir -p /var/cache/nginx /var/run /var/log/nginx \
    && chown -R vibeprompt:vibeprompt /var/cache/nginx /var/run /var/log/nginx /usr/share/nginx/html
COPY --from=build /src/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/nginx.conf
USER vibeprompt:vibeprompt
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD wget -q -O /dev/null http://127.0.0.1:8080/ || exit 1
CMD ["nginx", "-g", "daemon off;"]
