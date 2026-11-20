// The little of Node.js the e2e config reads, instead of all of @types/node.
declare module "node:process" {
  const process: {
    env: {
      // biome-ignore-start lint/style/useNamingConvention: environment variable names
      E2E_PORT?: string; // the backend's port, default 8765
      CI?: string; // set by CI services
      // biome-ignore-end lint/style/useNamingConvention: environment variable names
    };
  };
  // biome-ignore lint/style/noDefaultExport: how node:process exports it
  export default process;
}
