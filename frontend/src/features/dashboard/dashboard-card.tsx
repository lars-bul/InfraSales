import type { UseQueryResult } from "@tanstack/react-query";
import { cn } from "cn";
import type { LucideIcon } from "lucide-react";
import { type ReactNode, useId } from "react";
import { useTranslation } from "react-i18next";
import { Skeleton } from "#/components/ui/skeleton.tsx";
import { Unavailable } from "#/components/unavailable.tsx";

interface CardProps {
  title: string;
  icon: LucideIcon;
  link?: ReactNode; // where the card leads, beside its title
  className?: string | undefined;
  children: ReactNode;
}

interface LoadedProps<T> {
  query: UseQueryResult<T, unknown>;
  skeleton?: string; // the placeholder's size while loading
  children: (data: T) => ReactNode;
}

// One of the Dashboard's cards, as Cloudflare's account home has them: a small heading with its
// icon, a link onward beside it, and what it summarises below.
export function DashboardCard({ title, icon: Icon, link, className, children }: CardProps) {
  const id = useId();
  return (
    <section
      aria-labelledby={id}
      className={cn(
        "grid grid-cols-1 content-start gap-3 rounded-xl bg-card p-4 ring-1 ring-foreground/10",
        className,
      )}
    >
      <div className="flex items-center justify-between gap-2">
        <h2 id={id} className="flex items-center gap-2 font-heading font-medium text-sm">
          <Icon aria-hidden={true} className="size-4 text-muted-foreground" />
          {title}
        </h2>
        {link}
      </div>
      {children}
    </section>
  );
}

// What a query answered, or while it loads a placeholder, or that it failed with Try again: each
// card loads on its own, so one the service cannot answer leaves the others standing.
export function Loaded<T>({ query, skeleton = "h-12", children }: LoadedProps<T>) {
  const { t } = useTranslation();
  if (query.isSuccess) {
    return children(query.data);
  }
  if (query.isError) {
    return <Unavailable onRetry={() => query.refetch()} />;
  }
  return (
    <div role="status">
      <span className="sr-only">{t("app.loading")}</span>
      <Skeleton className={skeleton} />
    </div>
  );
}
