# SATRAK Web

Officer / commissioner / admin web application (and the shared shell the citizen
portal will reuse). **Engineering foundation only** — no product screens.

## Stack

Next.js 15 (App Router) · React 19 · TypeScript · Tailwind CSS v4 · shadcn/ui ·
TanStack Query · Zustand · React Hook Form · Zod.

## Structure

```
src/
├── app/
│   ├── layout.tsx           # root layout: fonts, providers, metadata
│   ├── providers.tsx        # theme + query client composition
│   ├── globals.css          # Tailwind v4 + design tokens (light/dark)
│   ├── loading.tsx          # route-level loading UI
│   ├── error.tsx            # route error boundary
│   ├── global-error.tsx     # root error boundary
│   ├── not-found.tsx        # 404
│   ├── (public)/            # route group: unauthenticated (landing)
│   └── (app)/               # route group: authenticated shell + /system status
├── components/
│   ├── providers/           # theme-provider, query-provider
│   └── ui/                  # shadcn primitives (button)
├── lib/
│   ├── api/                 # typed fetch client + endpoints + error types
│   ├── query-client.ts      # TanStack Query factory
│   └── utils.ts             # cn()
├── stores/                  # Zustand UI stores
└── env.ts                   # validated environment (t3-env + zod)
```

Route groups map to access boundaries; the auth guard (middleware) and full
`(app)` shell arrive with the Authentication epic.

## Commands

```bash
pnpm install            # from repo root (workspace install)
cp .env.example .env.local
pnpm --filter @satrak/web dev        # http://localhost:3000
pnpm --filter @satrak/web typecheck
pnpm --filter @satrak/web test       # vitest (unit/component)
pnpm --filter @satrak/web test:e2e   # playwright
pnpm --filter @satrak/web build
```

## Officer console

Routes, API matrix, authentication limits and open items: [`docs/OFFICER_CONSOLE.md`](../../docs/OFFICER_CONSOLE.md).

- Sign-in is a **development-only** pasted bearer token (kept in `sessionStorage`, refused when `NEXT_PUBLIC_APP_ENV=production`); there is no IdP client in the repository yet.
- `pnpm test:e2e` runs the stubbed-API journeys. `e2e/fullstack.spec.ts` runs against the real API only when `E2E_STACK_FILE` points at the file written by `python -m tests.e2e_stack.serve` (apps/api). If the bundled Chromium revision is not installed, set `PLAYWRIGHT_CHROMIUM_EXECUTABLE` to an installed Chromium.
