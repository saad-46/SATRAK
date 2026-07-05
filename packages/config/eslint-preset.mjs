/**
 * Shared ESLint flat-config preset for SATRAK TypeScript packages.
 *
 * Apps compose this with framework-specific configs (e.g. apps/web layers
 * `eslint-config-next` on top). Kept minimal at the foundation stage; rules are
 * tightened as shared conventions solidify.
 */
export const base = [
  {
    ignores: ["**/dist/**", "**/.next/**", "**/node_modules/**", "**/coverage/**"],
  },
  {
    rules: {
      "no-console": ["warn", { allow: ["warn", "error"] }],
      "no-debugger": "error",
    },
  },
];

export default base;
