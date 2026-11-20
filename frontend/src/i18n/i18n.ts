import i18next, { type TFunction } from "i18next";
import { initReactI18next } from "react-i18next";
import { en } from "#/i18n/locales/en.ts";

const instance = i18next.createInstance();

// Synchronous: the messages are bundled, so the first render is already translated.
await instance.use(initReactI18next).init({
  lng: "en",
  fallbackLng: "en",
  resources: { en: { translation: en } },
  initAsync: false,
  interpolation: { escapeValue: false }, // React escapes
});

/** `t` as the default namespace gives it: what a helper that translates takes as a parameter. */
export type Translate = TFunction<"translation">;

export const i18n = instance;
