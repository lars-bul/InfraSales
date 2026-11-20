import { cn } from "cn";

interface Props {
  title: string;
  description: string;
  className?: string;
}

// What a page or list shows while it has nothing to show: a short title and one line saying what
// will appear here, text only. Every empty list uses it, so empty never looks broken.
export function EmptyState({ title, description, className }: Props) {
  return (
    <div className={cn("grid w-full gap-1 px-6 py-8 text-center", className)}>
      <p className="font-medium">{title}</p>
      <p className="text-muted-foreground text-sm">{description}</p>
    </div>
  );
}
