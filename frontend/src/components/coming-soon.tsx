import { useTranslation } from "react-i18next";
import { EmptyState } from "#/components/empty-state.tsx";

// A page the sidebar already lists but that is not built yet: the empty-state pattern in a card.
// The shell's heading and line above it say what the page will show.
export function ComingSoon() {
  const { t } = useTranslation();
  return (
    <div className="rounded-xl border bg-card">
      <EmptyState title={t("app.comingSoon.title")} description={t("app.comingSoon.description")} />
    </div>
  );
}
