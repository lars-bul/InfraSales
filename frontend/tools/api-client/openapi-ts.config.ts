import { resolve } from "node:path";
import { defineConfig, type UserConfig } from "@hey-api/openapi-ts";

const here = import.meta.dirname;

// The UI's API client, generated from the checked-in contract (never a live server: the app
// serves no /openapi.json). `src` is the UI's source folder; the check generates into a copy.
export function clientConfig(src: string): UserConfig {
  return {
    input: resolve(here, "../../../openapi.json"),
    logs: { level: "silent" },
    // The API pages back with `before` only: by default `start` (the runs' time range) would
    // count as a cursor too, and "load older" would send the last run's ID as the start.
    parser: { pagination: { keywords: ["before"] } },
    output: {
      path: resolve(src, "client"),
      tsConfigPath: resolve(here, "../../tsconfig.json"),
      // The runtime files copied from the generator (they carry no `ctx.file`) fail the UI's
      // `exactOptionalPropertyTypes`. Only they skip type checks: the generated types, SDK and
      // Query helpers are checked in full.
      header: (ctx) => (ctx.file ? ctx.defaultValue : [...ctx.defaultValue, "// @ts-nocheck"]),
    },
    plugins: [
      "@hey-api/typescript",
      "@hey-api/sdk",
      // Same origin and the request deadline come from the UI's own module.
      {
        name: "@hey-api/client-fetch",
        runtimeConfigPath: resolve(src, "api/client-config.ts"),
      },
      "@tanstack/react-query",
    ],
  };
}

export default defineConfig(clientConfig(resolve(here, "../../src")));
