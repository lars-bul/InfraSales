import { createLink, type LinkComponentProps } from "@tanstack/react-router";
import { cn } from "cn";
import { ArrowRightIcon } from "lucide-react";
import type { ComponentProps } from "react";

// A card's link onward, at the end of its heading line: "All jobs →".
function OnwardAnchor({ children, className, ...props }: ComponentProps<"a">) {
  return (
    <a
      {...props}
      className={cn(
        "inline-flex items-center gap-1 text-muted-foreground text-xs underline-offset-4 hover:text-foreground hover:underline",
        className,
      )}
    >
      {children}
      <ArrowRightIcon aria-hidden={true} className="size-3" />
    </a>
  );
}

const OnwardLink = createLink(OnwardAnchor);

export function Onward(props: LinkComponentProps<typeof OnwardAnchor>) {
  return <OnwardLink {...props} />;
}
