# syntax=docker/dockerfile:1

########################
# Build stage
########################
FROM node:22-bookworm-slim AS builder

WORKDIR /app

COPY package.json package-lock.json ./

RUN npm ci

COPY . .

ARG VITE_API_URL=https://api-preprocessing.computimm.com
ENV VITE_API_URL=${VITE_API_URL}

RUN npm run build

# TanStack Start SSR output
RUN test -d /app/dist/client \
    && test -f /app/dist/server/server.js \
    && echo "SSR frontend build generated successfully" \
    && find /app/dist -maxdepth 3 -type f | head -n 40

########################
# Runtime stage
########################
FROM node:22-bookworm-slim AS runtime

WORKDIR /app

COPY package.json package-lock.json ./

RUN npm ci --omit=dev \
    && npm cache clean --force

COPY --from=builder --chown=node:node /app/dist ./dist

RUN chown -R node:node /app

ENV NODE_ENV=production \
    HOST=0.0.0.0 \
    PORT=4287

USER node

EXPOSE 4287

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD node -e "fetch('http://127.0.0.1:4287/').then(r => process.exit(r.ok ? 0 : 1)).catch(() => process.exit(1))"

CMD ["npm", "run", "start"]
