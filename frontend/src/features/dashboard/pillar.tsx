import { Link, type LinkComponentProps } from "@tanstack/react-router";
import { cn } from "cn";
import type { LucideIcon } from "lucide-react";
import { type ReactNode, useId } from "react";

interface Props {
  name: string;
  icon: LucideIcon;
  figure: ReactNode; // the pillar's number
  caption: string; // what the number counts
  link?: LinkComponentProps | undefined; // where the name leads; none: the page is not for this viewer
  active: boolean; // a job that fills it is running
  children?: ReactNode;
  className?: string;
}

// The running job's mark: a dot that pings while work happens in this pillar.
function Live() {
  return (
    <span aria-hidden={true} className="relative mt-1 flex size-2 shrink-0">
      <span className="absolute inline-flex size-full rounded-full bg-primary/60 motion-safe:animate-ping" />
      <span className="relative inline-flex size-2 rounded-full bg-primary" />
    </span>
  );
}

// One pillar of the pipeline: its name over its number, and what it holds. While a job that fills
// it runs, it rings, its mark pings and a flow runs into it from the pillar before (a pillar
// with no flow of its own, the first, has none). The number pops when it changes.
export function Pillar({
  name,
  icon: Icon,
  figure,
  caption,
  link,
  active,
  children,
  className,
}: Props) {
  const id = useId();
  const heading = (
    <>
      <Icon aria-hidden={true} className="size-3.5" />
      {name}
    </>
  );
  const headingClass = "flex items-center gap-2 text-muted-foreground text-xs";
  return (
    <li
      aria-labelledby={id}
      data-active={active}
      className={cn(
        "relative grid grid-cols-1 content-start gap-2 rounded-lg border bg-background p-3 transition-shadow duration-500",
        "data-[active=true]:border-primary/50 data-[active=true]:shadow-[0_0_0_3px_color-mix(in_oklab,var(--primary)_12%,transparent)]",
        className,
      )}
    >
      <span
        aria-hidden={true}
        className={cn(
          "-left-3 absolute top-8 hidden h-0.5 w-3 rounded-full bg-border xl:block",
          active &&
            "bg-[length:8px_100%] bg-[repeating-linear-gradient(90deg,var(--primary)_0_4px,transparent_4px_8px)] motion-safe:animate-lane",
        )}
      />
      <div className="flex items-start justify-between gap-2">
        {link ? (
          <Link
            id={id}
            {...link}
            className={cn(headingClass, "underline-offset-4 hover:text-foreground hover:underline")}
          >
            {heading}
          </Link>
        ) : (
          <p id={id} className={headingClass}>
            {heading}
          </p>
        )}
        {active ? <Live /> : null}
      </div>
      <p
        key={String(figure)}
        className="font-heading font-medium text-3xl tabular-nums motion-safe:animate-in motion-safe:fade-in motion-safe:zoom-in-90 motion-safe:duration-500"
      >
        {figure}
      </p>
      <p className="text-muted-foreground text-xs">{caption}</p>
      {children}
    </li>
  );
}
