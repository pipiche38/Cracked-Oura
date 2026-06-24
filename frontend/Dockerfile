FROM node:20-alpine AS builder

WORKDIR /app
COPY package*.json ./
RUN npm ci --legacy-peer-deps

COPY . .

# Web-only build — skips Electron packaging, proxies /api/ via nginx
RUN VITE_API_URL="" npx vite build --outDir dist-web

FROM nginx:alpine
COPY --from=builder /app/dist-web /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
