import { createEnv } from "@t3-oss/env-nextjs";
import { z } from "zod";

/**
 * Type-safe, validated environment access.
 *
 * Importing `env` anywhere guarantees the variables exist and are well-formed;
 * a missing/invalid value throws at startup instead of surfacing as `undefined`
 * deep in the UI. Only `NEXT_PUBLIC_*` vars are declared (this is a client app
 * shell); server-only secrets would go under `server` and never reach the bundle.
 */
export const env = createEnv({
  client: {
    NEXT_PUBLIC_API_URL: z.string().url(),
    NEXT_PUBLIC_APP_ENV: z
      .enum(["development", "staging", "production", "test"])
      .default("development"),
  },
  runtimeEnv: {
    NEXT_PUBLIC_API_URL: process.env.NEXT_PUBLIC_API_URL,
    NEXT_PUBLIC_APP_ENV: process.env.NEXT_PUBLIC_APP_ENV,
  },
  // Allow the build to proceed in CI without a real .env (skips validation when
  // explicitly requested); normal dev/prod runs validate.
  skipValidation: process.env.SKIP_ENV_VALIDATION === "true",
  emptyStringAsUndefined: true,
});
