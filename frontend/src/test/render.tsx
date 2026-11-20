import { createMemoryHistory } from "@tanstack/react-router";
import { render } from "@testing-library/react";
import type { ReactElement } from "react";
import { I18nextProvider } from "react-i18next";
import { afterEach } from "vitest";
import { App } from "#/app.tsx";
import { createApp } from "#/create-app.ts";
import { i18n } from "#/i18n/i18n.ts";
import { createQueryClient } from "#/lib/query-client.ts";

const running: (() => void)[] = [];
afterEach(() => {
  for (const disconnect of running.splice(0)) {
    disconnect(); // the generated client is shared: drop this app's interceptors
  }
});

export function renderTranslated(element: ReactElement) {
  return render(<I18nextProvider i18n={i18n}>{element}</I18nextProvider>);
}

/**
 * The whole app at `url`, as a person opens it: the real router (on a memory history), a fresh
 * query cache and the translations. Pair it with `stubApi` for the API's answers. Queries are
 * not retried here, so a failure shows at once; `lib/query-client.test.ts` covers the retry rules.
 */
export function renderApp(url: string) {
  const queryClient = createQueryClient();
  queryClient.setDefaultOptions({ queries: { retry: false }, mutations: { retry: false } });
  const app = createApp({ history: createMemoryHistory({ initialEntries: [url] }), queryClient });
  running.push(app.disconnect);
  const view = render(
    <I18nextProvider i18n={i18n}>
      <App router={app.router} queryClient={app.queryClient} />
    </I18nextProvider>,
  );
  return { ...view, ...app };
}
