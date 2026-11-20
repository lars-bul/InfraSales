import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";

// A screen outside the app shell (signing in, an outage): InfraSales' icon and name above one
// centred box, and nothing else to choose from.
export function CentredScreen({ children }: { children: ReactNode }) {
  const { t } = useTranslation();
  return (
    <main className="flex min-h-svh flex-col items-center justify-center gap-6 bg-muted/40 p-4">
      <h1 className="flex items-center gap-2 font-semibold text-2xl">
        <img src="/favicon.svg" alt="" width={32} height={32} className="size-8 shrink-0" />
        {t("app.title")}
      </h1>
      {children}
    </main>
  );
}
