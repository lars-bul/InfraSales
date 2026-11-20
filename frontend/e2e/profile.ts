import process from "node:process";

// The test profile the e2e web server runs with. Made-up values only.

// The backend's port: E2E_PORT, so parallel runs on one machine can each have their own.
const port = process.env.E2E_PORT ?? "8765";

export const baseUrl = `http://127.0.0.1:${port}`;

// Built-in sign-in: the sample users alice (admin) and vera (viewer) share it.
export const password = "e2e-password";

// The rest of the profile; e2e/server.sh adds the throwaway database.
export const environment = {
  // biome-ignore-start lint/style/useNamingConvention: environment variable names
  LOG_FORMAT: "console",
  WEB__HOST: "127.0.0.1",
  WEB__PORT: port,
  WEB__PUBLIC_URL: baseUrl,
  WEB__FRONTEND_DIR: "frontend/dist",
  AUTH__PROVIDER: "basic",
  AUTH__PASSWORD: password,
  SCHEDULER__ENABLED: "false", // no job runs on its own while the specs look
  // biome-ignore-end lint/style/useNamingConvention: environment variable names
};
