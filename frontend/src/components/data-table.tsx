import { type ReactNode, useId } from "react";

interface Props {
  caption: string;
  children: ReactNode; // the table's head and body
}

// A table of records in a bordered frame: a muted head, roomy rows and the caption (what it
// lists, often a count) as its last line. Wider than the screen, it scrolls sideways on its own,
// never the page (WCAG lets data tables keep their columns), and keyboard users can focus and
// scroll it.
export function DataTable({ caption, children }: Props) {
  const label = useId();
  return (
    <section
      className="w-full overflow-x-auto rounded-lg border bg-card focus-visible:outline-2 focus-visible:outline-ring"
      aria-labelledby={label}
      // biome-ignore lint/a11y/noNoninteractiveTabindex: a scrolling region must be reachable by keyboard
      tabIndex={0}
    >
      <table className="w-full caption-bottom text-sm [&_thead]:bg-muted/50">
        <caption id={label} className="border-t px-3 py-2 text-start text-muted-foreground text-xs">
          {caption}
        </caption>
        {children}
      </table>
    </section>
  );
}
