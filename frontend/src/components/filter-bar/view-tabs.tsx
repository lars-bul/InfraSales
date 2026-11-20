import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "#/components/ui/tabs.tsx";

/** One view of a list: its URL value, its name, and how many it holds. */
export interface View<V extends string> {
  value: V;
  label: string;
  count?: number | undefined;
}

export interface ViewTabsProps<V extends string> {
  views: View<V>[];
  value: V;
  onChange: (value: V) => void;
  /** Names the tab list for assistive technology; default "Views". */
  label?: string | undefined;
  /** At the end of the tabs' row: the page's main action ("Add Feed") and its status. */
  actions?: ReactNode;
  /** What the chosen view shows (the filter bar and the list): it becomes the tabs' panel. */
  children?: ReactNode;
}

/**
 * The views of a list as tabs with counts ("All 28 · Needs attention 3 · Disabled 2"). The page
 * holds which one is chosen (in its URL); the same list shows below, whichever it is.
 */
export function ViewTabs<V extends string>({
  views,
  value,
  onChange,
  label,
  actions,
  children,
}: ViewTabsProps<V>) {
  const { t, i18n } = useTranslation();
  const number = new Intl.NumberFormat(i18n.language);
  return (
    <Tabs
      value={value}
      onValueChange={(chosen: V) => {
        if (chosen !== value) {
          onChange(chosen);
        }
      }}
    >
      <div className="flex flex-wrap items-end justify-between gap-3">
        <TabsList variant="line" aria-label={label ?? t("filters.views")}>
          {views.map((view) => (
            <TabsTrigger key={view.value} value={view.value} className="flex-none px-2">
              {view.label}
              {view.count === undefined ? null : (
                <>
                  {" "}
                  <span className="rounded-full bg-muted px-1.5 text-muted-foreground text-xs tabular-nums">
                    {number.format(view.count)}
                  </span>
                </>
              )}
            </TabsTrigger>
          ))}
        </TabsList>
        {actions === undefined ? null : (
          <div className="flex flex-wrap items-center gap-3 pb-1">{actions}</div>
        )}
      </div>
      {children === undefined ? null : (
        <TabsContent value={value} className="grid gap-4 pt-2">
          {children}
        </TabsContent>
      )}
    </Tabs>
  );
}
