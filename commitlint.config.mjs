/**
 * Conventional Commits enforcement.
 * Scopes mirror the monorepo's bounded contexts so history is machine-parseable
 * and changelogs can be generated per area later.
 */
export default {
  extends: ["@commitlint/config-conventional"],
  rules: {
    "type-enum": [
      2,
      "always",
      [
        "feat",
        "fix",
        "docs",
        "style",
        "refactor",
        "perf",
        "test",
        "build",
        "ci",
        "chore",
        "revert",
      ],
    ],
    "scope-enum": [
      1,
      "always",
      [
        "root",
        "web",
        "api",
        "ai",
        "ui",
        "sdk",
        "shared",
        "config",
        "satellite",
        "gis",
        "drone",
        "notifications",
        "compliance",
        "db",
        "docker",
        "ci",
        "docs",
        "scripts",
      ],
    ],
    "body-max-line-length": [0, "always", Infinity],
  },
};
