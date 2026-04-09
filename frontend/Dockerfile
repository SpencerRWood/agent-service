FROM node:22-alpine AS build

WORKDIR /app

COPY frontend/package.json ./
COPY frontend/tsconfig.json ./
COPY frontend/tsconfig.app.json ./
COPY frontend/vite.config.ts ./
COPY frontend/index.html ./
COPY frontend/src ./src

ARG VITE_API_BASE_URL=/api
ENV VITE_API_BASE_URL=$VITE_API_BASE_URL

RUN npm install
RUN npm run build

FROM caddy:2-alpine

COPY frontend/Caddyfile /etc/caddy/Caddyfile
COPY --from=build /app/dist /srv

EXPOSE 80
