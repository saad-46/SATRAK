# syntax=docker/dockerfile:1
# =============================================================================
# SATRAK Web — multi-stage Next.js image (standalone output)
# =============================================================================

FROM node:20-slim AS base
ENV PNPM_HOME="/pnpm" PATH="/pnpm:$PATH"
RUN corepack enable

# --- Dependencies ------------------------------------------------------------
FROM base AS deps
WORKDIR /repo
# Copy only what pnpm needs to resolve the web app's dependency graph.
COPY pnpm-lock.yaml pnpm-workspace.yaml package.json ./
COPY apps/web/package.json apps/web/package.json
RUN --mount=type=cache,id=pnpm,target=/pnpm/store \
    pnpm install --filter @satrak/web... --frozen-lockfile

# --- Build -------------------------------------------------------------------
FROM base AS builder
WORKDIR /repo
COPY --from=deps /repo/node_modules ./node_modules
COPY --from=deps /repo/apps/web/node_modules ./apps/web/node_modules
COPY . .
# BUILD_STANDALONE enables Next's standalone output (Linux symlinks are fine here).
ENV SKIP_ENV_VALIDATION=true NEXT_TELEMETRY_DISABLED=1 BUILD_STANDALONE=true
RUN pnpm --filter @satrak/web build

# --- Runtime -----------------------------------------------------------------
FROM node:20-slim AS runtime
WORKDIR /app
ENV NODE_ENV=production NEXT_TELEMETRY_DISABLED=1
RUN groupadd --system nodejs && useradd --system --gid nodejs nextjs

# Next.js `output: standalone` bundles a minimal server + only needed deps.
COPY --from=builder --chown=nextjs:nodejs /repo/apps/web/.next/standalone ./
COPY --from=builder --chown=nextjs:nodejs /repo/apps/web/.next/static ./apps/web/.next/static
COPY --from=builder --chown=nextjs:nodejs /repo/apps/web/public ./apps/web/public

USER nextjs
EXPOSE 3000
ENV PORT=3000 HOSTNAME=0.0.0.0
CMD ["node", "apps/web/server.js"]
