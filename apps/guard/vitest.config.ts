import { defineConfig } from "vitest/config";

// Pure logic only (src/lib/{alerts,geo}.ts): no React Native runtime in unit tests.
export default defineConfig({ test: { include: ["src/**/*.test.ts"], environment: "node" } });
