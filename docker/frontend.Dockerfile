# flare-frontend: React build served by nginx (non-root, port 8080); /api is proxied to the API service.
FROM node:22.23.5-alpine3.24 AS build
WORKDIR /app
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
ARG GIT_SHA=dev
ENV VITE_GIT_SHA=${GIT_SHA}
RUN npm run build

FROM nginxinc/nginx-unprivileged:1.29.8-alpine3.23
ARG GIT_SHA=dev
# OS security updates at build time, then back to the unprivileged nginx user (uid 101)
USER root
RUN apk upgrade --no-cache
USER 101
COPY docker/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 8080
HEALTHCHECK --interval=15s --timeout=4s --start-period=10s --retries=5 CMD wget -qO- http://127.0.0.1:8080/healthz || exit 1
LABEL org.opencontainers.image.source="https://github.com/veenaphadtare12-ux/Nowcasting-and-forecasting-of-soar-flare_mlops" \
      org.opencontainers.image.revision="${GIT_SHA}" \
      org.opencontainers.image.title="flare-frontend"
