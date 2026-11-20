import { ChevronRightIcon } from "lucide-react";
import { useId, useState } from "react";
import { useTranslation } from "react-i18next";
import type { AuditEventRead } from "#/client/types.gen.ts";
import { Button } from "#/components/ui/button.tsx";
import { TableCell, TableRow } from "#/components/ui/table.tsx";
import { sentence } from "./sentence.ts";

interface Props {
  event: AuditEventRead;
  reader: string; // the signed-in user's subject: their own events read "(you)"
  time: Intl.DateTimeFormat;
}

// A detail's value as text: nested values (a schedule before and after) as compact JSON.
function text(value: unknown): string {
  return typeof value === "string" ? value : JSON.stringify(value);
}

// One event: its sentence and time; the sentence is a button that shows the event's outcome,
// target, full actor and details as key–value pairs in a row below it.
export function AuditRow({ event, reader, time }: Props) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  const details = useId();
  const pairs: [string, string][] = [
    [t("audit.outcome"), t(`outcomes.${event.outcome}`)],
    [t("audit.action"), event.action],
    [t("audit.target"), event.target ?? t("audit.none")],
    [t("audit.actor"), event.actor ?? t("audit.system")],
    ...Object.entries(event.details).map(([key, value]): [string, string] => [key, text(value)]),
  ];

  return (
    <>
      <TableRow>
        <TableCell className="whitespace-normal">
          <Button
            variant="ghost"
            size="sm"
            aria-expanded={open}
            aria-controls={open ? details : undefined}
            onClick={() => setOpen(!open)}
            className="h-auto min-h-8 w-full items-start justify-start whitespace-normal py-1.5 text-start font-normal text-sm"
          >
            <ChevronRightIcon
              aria-hidden={true}
              className={`mt-0.5 size-4 shrink-0 text-muted-foreground transition-transform ${open ? "rotate-90" : ""}`}
            />
            <span>{sentence(t, event, reader)}</span>
          </Button>
        </TableCell>
        <TableCell className="text-right text-muted-foreground">
          <time dateTime={event.created_at}>{time.format(new Date(event.created_at))}</time>
        </TableCell>
      </TableRow>
      {open ? (
        <TableRow id={details} className="hover:bg-transparent">
          <TableCell colSpan={2} className="whitespace-normal bg-muted/30 ps-12">
            <dl className="grid grid-cols-[max-content_1fr] gap-x-6 gap-y-1 text-sm">
              {pairs.map(([key, value]) => (
                <div key={key} className="contents">
                  <dt className="text-muted-foreground">{key}</dt>
                  <dd className="break-all font-mono text-xs leading-5">{value}</dd>
                </div>
              ))}
            </dl>
          </TableCell>
        </TableRow>
      ) : null}
    </>
  );
}
