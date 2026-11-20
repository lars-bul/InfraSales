import "i18next";
import type { en } from "#/i18n/locales/en.ts";

// Translation keys are type-checked: `t("app.titel")` does not compile.
declare module "i18next" {
  interface CustomTypeOptions {
    resources: { translation: typeof en };
  }
}
