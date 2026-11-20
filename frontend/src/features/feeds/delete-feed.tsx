import { useQueryClient } from "@tanstack/react-query";
import { Trash2Icon } from "lucide-react";
import { type RefObject, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import type { FeedRead } from "#/client/types.gen.ts";
import {
  AlertDialog,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger,
} from "#/components/ui/alert-dialog.tsx";
import { Button } from "#/components/ui/button.tsx";
import { FieldError } from "#/components/ui/field.tsx";
import { refreshFeeds, useDeleteFeed } from "./feed-requests.ts";

interface Props {
  feed: FeedRead;
  // Where focus goes once the Feed is deleted: its row, and this button with it, are gone.
  focusAfter: RefObject<HTMLElement | null>;
  onDeleted: (feed: FeedRead) => void;
}

// Delete, for a Feed's row (admins), on Feeds that have collected no Sources yet: one added by
// mistake, or at an address that never worked. It asks first. While it deletes, the question
// stays open; if the Feed cannot be deleted, it says why there. One that collected Sources
// meanwhile loses its Delete once the question closes: the list is read again then.
export function DeleteFeed({ feed, focusAfter, onDeleted }: Props) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const remove = useDeleteFeed();
  const [open, setOpen] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [problem, setProblem] = useState<"hasSources" | "failed" | null>(null);
  const deleted = useRef<boolean>(false);

  async function confirm() {
    setDeleting(true);
    setProblem(null);
    const { outcome } = await remove(feed);
    setDeleting(false);
    if (outcome === "deleted") {
      deleted.current = true;
      setOpen(false);
      onDeleted(feed);
    } else {
      setProblem(outcome);
    }
  }

  return (
    <AlertDialog
      open={open}
      onOpenChange={(next) => {
        if (deleting) {
          return;
        }
        if (!next && problem === "hasSources") {
          refreshFeeds(queryClient);
        }
        setOpen(next);
        setProblem(null);
      }}
    >
      <AlertDialogTrigger
        render={
          <Button
            variant="ghost"
            size="icon-sm"
            aria-label={t("feeds.delete.named", { name: feed.name })}
          >
            <Trash2Icon aria-hidden={true} />
          </Button>
        }
      />
      <AlertDialogContent finalFocus={() => (deleted.current ? focusAfter.current : true)}>
        <AlertDialogHeader>
          <AlertDialogTitle>{t("feeds.delete.title", { name: feed.name })}</AlertDialogTitle>
          <AlertDialogDescription>{t("feeds.delete.description")}</AlertDialogDescription>
        </AlertDialogHeader>
        <p role="status" className="text-muted-foreground text-sm empty:sr-only">
          {deleting ? t("feeds.delete.deleting") : null}
        </p>
        {problem === null ? null : <FieldError>{t(`feeds.delete.problems.${problem}`)}</FieldError>}
        <AlertDialogFooter>
          <AlertDialogCancel disabled={deleting}>{t("feeds.delete.cancel")}</AlertDialogCancel>
          <Button variant="destructive" disabled={deleting} onClick={confirm}>
            {t("feeds.delete.confirm")}
          </Button>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );
}
