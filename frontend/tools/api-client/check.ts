// Fails when src/client differs from what openapi.json generates: run `make api-types`.
import { spawnSync } from "node:child_process";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import process from "node:process";
import { createClient } from "@hey-api/openapi-ts";
import { clientConfig } from "./openapi-ts.config.ts";

const committed = resolve(import.meta.dirname, "../../src/client");
const scratch = mkdtempSync(join(tmpdir(), "api-client-"));
try {
  await createClient(clientConfig(scratch));
  // `git diff --no-index` prints the difference and exits 1 when the folders differ.
  const diff = spawnSync(
    "git",
    ["diff", "--no-index", "--stat", committed, join(scratch, "client")],
    {
      stdio: "inherit",
    },
  );
  if (diff.status !== 0) {
    process.exitCode = 1;
    process.stderr.write("src/client is stale: run `make api-types`\n");
  }
} finally {
  rmSync(scratch, { force: true, recursive: true });
}
