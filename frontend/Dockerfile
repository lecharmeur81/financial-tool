# syntax=docker/dockerfile:1
# Frontend image (Next.js standalone server).

FROM node:22-alpine AS base
ENV NEXT_TELEMETRY_DISABLED=1
# Pinned pnpm, same version as "packageManager" in package.json.
RUN npm install --global pnpm@10.28.0
WORKDIR /app

FROM base AS deps
COPY package.json pnpm-lock.yaml pnpm-workspace.yaml ./
RUN pnpm install --frozen-lockfile

FROM base AS build
COPY --from=deps /app/node_modules ./node_modules
COPY . .
RUN pnpm build

FROM node:22-alpine AS runtime
ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 \
    PORT=3000 \
    HOSTNAME=0.0.0.0
WORKDIR /app
RUN addgroup -S cfi && adduser -S -G cfi cfi
COPY --from=build --chown=cfi:cfi /app/public ./public
COPY --from=build --chown=cfi:cfi /app/.next/standalone ./
COPY --from=build --chown=cfi:cfi /app/.next/static ./.next/static
USER cfi
EXPOSE 3000
CMD ["node", "server.js"]
