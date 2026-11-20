import type { ReactNode } from "react";
import { useId } from "react";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "#/components/ui/card.tsx";

interface Props {
  title: string;
  description: string;
  children: ReactNode;
}

// A titled card that is a region of its own: what a chart or a list on a page sits in, its title
// naming it for assistive technology and its description saying what to read from it.
export function Panel({ title, description, children }: Props) {
  const id = useId();
  return (
    <Card aria-labelledby={id} role="region">
      <CardHeader>
        <CardTitle id={id}>{title}</CardTitle>
        <CardDescription>{description}</CardDescription>
      </CardHeader>
      <CardContent>{children}</CardContent>
    </Card>
  );
}
