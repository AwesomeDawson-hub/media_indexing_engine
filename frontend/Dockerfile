# Frontend Dockerfile — Media Indexing Engine
# Multi-stage build: Node.js to compile, nginx to serve.

# Stage 1: Build the React + TypeScript application
FROM node:20-slim AS build

WORKDIR /app

COPY package.json package-lock.json ./
RUN npm ci

COPY index.html tsconfig.json vite.config.ts ./
COPY src/ ./src/

# VITE_API_BASE_URL can be injected at build time if needed.
# In the Docker stack the frontend nginx proxies /api to the backend container,
# so the default relative /api path works without any override.
RUN npm run build

# Stage 2: Serve with nginx
FROM nginx:1.27-alpine

# Remove the default nginx welcome page
RUN rm /etc/nginx/conf.d/default.conf

COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 80
