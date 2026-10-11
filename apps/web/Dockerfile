# syntax=docker/dockerfile:1
# =============================================================================
# SATRAK Web — multi-stage Next.js image (standalone output)
# =============================================================================

# Node 22 is the active LTS (Node 20 is end-of-life and its image is no longer rebuilt, which is why
# its Debian packages could not be patched). The base is pinned by digest so every build uses the
# same patched image; the tag is kept for readers and for Dependabot, which proposes digest bumps.
# Reproducibility trade-off: a pin does not pick up new Debian security patches until it is bumped.
ARG NODE_IMAGE=node:22-trixie-slim@sha256:154ba2f4d6fec323d28e4f4bb86bba4677f1223391a1979cf521304e03a98dfa
FROM ${NODE_IMAGE} AS base
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
FROM ${NODE_IMAGE} AS runtime
WORKDIR /app
ENV NODE_ENV=production NEXT_TELEMETRY_DISABLED=1
RUN groupadd --system nodejs && useradd --system --gid nodejs nextjs

# The standalone server needs only the `node` binary. Remove npm, npx, corepack and yarn: they are
# package managers a running container never uses, and the copy of npm bundled in the base image
# carries its own vulnerable dependencies (tar, glob, minimatch, ...). The check fails the build
# if any of them is still resolvable.
RUN rm -rf /usr/local/lib/node_modules /usr/local/bin/npm /usr/local/bin/npx \
        /usr/local/bin/corepack /usr/local/bin/yarn /usr/local/bin/yarnpkg /opt/yarn-* \
    && for t in npm npx corepack yarn yarnpkg; do ! command -v "$t" || exit 1; done \
    && node --version

# Next.js `output: standalone` bundles a minimal server + only needed deps.
COPY --from=builder --chown=nextjs:nodejs /repo/apps/web/.next/standalone ./
COPY --from=builder --chown=nextjs:nodejs /repo/apps/web/.next/static ./apps/web/.next/static
COPY --from=builder --chown=nextjs:nodejs /repo/apps/web/public ./apps/web/public

USER nextjs
EXPOSE 3000
ENV PORT=3000 HOSTNAME=0.0.0.0
CMD ["node", "apps/web/server.js"]
