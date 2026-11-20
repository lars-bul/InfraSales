import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { I18nextProvider } from "react-i18next";
import { i18n } from "#/i18n/i18n.ts";
import { applyTheme, storedTheme } from "#/lib/theme.ts";
import { App } from "./app.tsx";
import { createApp } from "./create-app.ts";
import "./styles.css";

const root = document.getElementById("root");
if (!root) {
  throw new Error("Missing #root element");
}
document.documentElement.lang = i18n.language;
applyTheme(storedTheme()); // before the first render, so the page starts in its theme
const { router, queryClient } = createApp();
createRoot(root).render(
  <StrictMode>
    <I18nextProvider i18n={i18n}>
      <App router={router} queryClient={queryClient} />
    </I18nextProvider>
  </StrictMode>,
);
