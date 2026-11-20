import { PlusIcon } from "lucide-react";
import { type Ref, type SubmitEvent, useEffect, useId, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import type { FeedCategory, FeedKind, FeedRead, Suggestion } from "#/client/types.gen.ts";
import { Button } from "#/components/ui/button.tsx";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "#/components/ui/dialog.tsx";
import { Field, FieldDescription, FieldError, FieldLabel } from "#/components/ui/field.tsx";
import { Input } from "#/components/ui/input.tsx";
import { NativeSelect, NativeSelectOption } from "#/components/ui/native-select.tsx";
import { CATEGORIES } from "./categories.ts";
import { type Problem, useAddFeed, useFindFeed } from "./feed-requests.ts";
import { ENTERED_BY_HAND, KINDS } from "./kinds.ts";

const MAX_NAME_LENGTH = 200; // as the API allows

// Where the dialog is: the site's address, the Feed found there, or a Feed entered by hand.
type Step = { at: "site" } | { at: "found"; suggestion: Suggestion } | { at: "byHand" };

// Each step's first field has the focus once the step shows, as the dialog's first field has
// when it opens: keyboard users go on where the step starts.
function useFocusOnShow<T extends HTMLElement>() {
  const ref = useRef<T>(null);
  useEffect(() => {
    ref.current?.focus();
  }, []);
  return ref;
}

interface SiteProps {
  site: string;
  onSite: (site: string) => void;
  onFound: (suggestion: Suggestion) => void;
  onByHand: () => void;
}

// Step 1: the site's address. InfraSales looks for its feed, else its sitemap; if it finds
// neither, the admin may enter the Feed by hand.
function SiteStep({ site, onSite, onFound, onByHand }: SiteProps) {
  const { t } = useTranslation();
  const id = useId();
  const field = useFocusOnShow<HTMLInputElement>();
  const find = useFindFeed();
  const [finding, setFinding] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);

  async function submit(event: SubmitEvent<HTMLFormElement>) {
    event.preventDefault();
    setFinding(true);
    setProblem(null);
    const found = await find(site);
    setFinding(false);
    if (found.outcome === "found") {
      onFound(found.suggestion);
    } else {
      setProblem(
        found.outcome === "refused" ? found.message : t(`feeds.add.problems.${found.outcome}`),
      );
    }
  }

  return (
    <form onSubmit={submit} className="grid gap-4">
      <DialogHeader>
        <DialogTitle>{t("feeds.add.title")}</DialogTitle>
        <DialogDescription>{t("feeds.add.siteDescription")}</DialogDescription>
      </DialogHeader>
      <fieldset disabled={finding} className="grid gap-2">
        <Field data-invalid={problem !== null}>
          <FieldLabel htmlFor={`${id}-site`}>{t("feeds.add.site")}</FieldLabel>
          <Input
            ref={field}
            id={`${id}-site`}
            inputMode="url"
            autoComplete="url"
            spellCheck={false}
            placeholder={t("feeds.add.sitePlaceholder")}
            required={true}
            value={site}
            aria-invalid={problem !== null}
            aria-describedby={problem === null ? undefined : `${id}-problem`}
            onChange={(event) => onSite(event.target.value)}
          />
        </Field>
        <p role="status" className="text-muted-foreground text-sm empty:sr-only">
          {finding ? t("feeds.add.finding") : null}
        </p>
        {problem === null ? null : <FieldError id={`${id}-problem`}>{problem}</FieldError>}
      </fieldset>
      <DialogFooter className="sm:justify-between">
        <Button type="button" variant="ghost" disabled={finding} onClick={onByHand}>
          {t("feeds.add.byHand")}
        </Button>
        <Button type="submit" disabled={finding}>
          {t("feeds.add.find")}
        </Button>
      </DialogFooter>
    </form>
  );
}

// What was found: its kind and address, as they will be added.
function FoundFeed({ suggestion }: { suggestion: Suggestion }) {
  const { t } = useTranslation();
  return (
    <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 rounded-lg border bg-muted/50 px-3 py-2">
      <dt className="text-muted-foreground">{t("feeds.kind")}</dt>
      <dd>{t(`feeds.kinds.${KINDS[suggestion.kind]}`)}</dd>
      <dt className="text-muted-foreground">{t("feeds.add.address")}</dt>
      <dd className="min-w-0 break-all">{suggestion.url}</dd>
    </dl>
  );
}

interface HandProps {
  id: string;
  kind: FeedKind;
  url: string;
  invalid: boolean; // the API refused the address
  onKind: (kind: FeedKind) => void;
  onUrl: (url: string) => void;
}

// A Feed entered by hand: its kind (RSS or Sitemap) and its address.
function HandFields({ id, kind, url, invalid, onKind, onUrl }: HandProps) {
  const { t } = useTranslation();
  return (
    <>
      <Field>
        <FieldLabel htmlFor={`${id}-kind`}>{t("feeds.kind")}</FieldLabel>
        <NativeSelect
          id={`${id}-kind`}
          value={kind}
          onChange={(event) => onKind(event.target.value as FeedKind)}
        >
          {ENTERED_BY_HAND.map((each) => (
            <NativeSelectOption key={each} value={each}>
              {t(`feeds.kinds.${KINDS[each]}`)}
            </NativeSelectOption>
          ))}
        </NativeSelect>
      </Field>
      <Field data-invalid={invalid}>
        <FieldLabel htmlFor={`${id}-address`}>{t("feeds.add.address")}</FieldLabel>
        <Input
          id={`${id}-address`}
          inputMode="url"
          spellCheck={false}
          placeholder={t("feeds.add.addressPlaceholder")}
          required={true}
          value={url}
          aria-invalid={invalid}
          onChange={(event) => onUrl(event.target.value)}
        />
      </Field>
    </>
  );
}

// What the Feed is: the press, a municipality's, a utility's, a tender platform's or an authority's. It has no default, so
// each Feed is put where it belongs; the choice's hint says what belongs there.
function CategoryField({
  id,
  category,
  onCategory,
}: {
  id: string;
  category: FeedCategory | "";
  onCategory: (category: FeedCategory) => void;
}) {
  const { t } = useTranslation();
  return (
    <Field>
      <FieldLabel htmlFor={`${id}-category`}>{t("feeds.add.category")}</FieldLabel>
      <NativeSelect
        id={`${id}-category`}
        required={true}
        value={category}
        aria-describedby={category ? `${id}-category-hint` : undefined}
        onChange={(event) => onCategory(event.target.value as FeedCategory)}
      >
        <NativeSelectOption value="" disabled={true}>
          {t("feeds.add.chooseCategory")}
        </NativeSelectOption>
        {CATEGORIES.map((each) => (
          <NativeSelectOption key={each} value={each}>
            {t(`feeds.categories.${each}`)}
          </NativeSelectOption>
        ))}
      </NativeSelect>
      {category ? (
        <FieldDescription id={`${id}-category-hint`}>
          {t(`feeds.categoryHints.${category}`)}
        </FieldDescription>
      ) : null}
    </Field>
  );
}

interface FeedProps {
  suggestion?: Suggestion; // what was found; without it, the Feed is entered by hand
  onBack: () => void;
  onAdded: (feed: FeedRead) => void;
}

// Step 2: the Feed to add. A Feed found keeps its kind and address, and only its name may be
// corrected; one entered by hand takes all three, its kind RSS or Sitemap. Either way the admin
// chooses its category.
function FeedStep({ suggestion, onBack, onAdded }: FeedProps) {
  const { t } = useTranslation();
  const id = useId();
  const field = useFocusOnShow<HTMLInputElement>();
  const add = useAddFeed();
  const [name, setName] = useState(suggestion?.name ?? "");
  const [kind, setKind] = useState<FeedKind>(suggestion?.kind ?? "rss");
  const [url, setUrl] = useState(suggestion?.url ?? "");
  const [category, setCategory] = useState<FeedCategory | "">("");
  const [adding, setAdding] = useState(false);
  const [problem, setProblem] = useState<Problem | null>(null);

  async function submit(event: SubmitEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!category) {
      return; // the browser asks for one first: the select is required
    }
    setAdding(true);
    setProblem(null);
    const added = await add({ name, kind, url, category });
    setAdding(false);
    if (added.outcome === "added") {
      onAdded(added.feed);
    } else {
      setProblem(added.outcome);
    }
  }

  return (
    <form onSubmit={submit} className="grid gap-4">
      <DialogHeader>
        <DialogTitle>{t("feeds.add.title")}</DialogTitle>
        <DialogDescription>
          {suggestion ? t("feeds.add.foundDescription") : t("feeds.add.byHandDescription")}
        </DialogDescription>
      </DialogHeader>
      <fieldset disabled={adding} className="grid gap-4">
        <Field>
          <FieldLabel htmlFor={`${id}-name`}>{t("feeds.name")}</FieldLabel>
          <Input
            ref={field}
            id={`${id}-name`}
            required={true}
            maxLength={MAX_NAME_LENGTH}
            value={name}
            onChange={(event) => setName(event.target.value)}
          />
        </Field>
        <CategoryField id={id} category={category} onCategory={setCategory} />
        {suggestion ? (
          <FoundFeed suggestion={suggestion} />
        ) : (
          <HandFields
            id={id}
            kind={kind}
            url={url}
            invalid={problem === "invalid"}
            onKind={setKind}
            onUrl={setUrl}
          />
        )}
        <p role="status" className="text-muted-foreground text-sm empty:sr-only">
          {adding ? t("feeds.add.adding") : null}
        </p>
        {problem === null ? null : <FieldError>{t(`feeds.add.problems.${problem}`)}</FieldError>}
      </fieldset>
      <DialogFooter>
        <Button type="button" variant="outline" disabled={adding} onClick={onBack}>
          {t("feeds.add.back")}
        </Button>
        <Button type="submit" disabled={adding}>
          {t("feeds.add.submit")}
        </Button>
      </DialogFooter>
    </form>
  );
}

// The dialog's steps. They start again each time it opens: closing it drops them.
function AddFeedSteps({ onAdded }: { onAdded: (feed: FeedRead) => void }) {
  const [step, setStep] = useState<Step>({ at: "site" });
  const [site, setSite] = useState(""); // kept for going back from step 2
  const back = () => setStep({ at: "site" });

  if (step.at === "found") {
    return <FeedStep key="found" suggestion={step.suggestion} onBack={back} onAdded={onAdded} />;
  }
  if (step.at === "byHand") {
    return <FeedStep key="byHand" onBack={back} onAdded={onAdded} />;
  }
  return (
    <SiteStep
      site={site}
      onSite={setSite}
      onFound={(suggestion) => setStep({ at: "found", suggestion })}
      onByHand={() => setStep({ at: "byHand" })}
    />
  );
}

interface Props {
  ref?: Ref<HTMLButtonElement>; // "Add Feed" itself
  onOpen: () => void;
  onAdded: (feed: FeedRead) => void;
}

// "Add Feed" and its dialog (admins): InfraSales suggests the site's feed or sitemap, or the
// admin enters one by hand. Once added, the dialog closes and focus is back on "Add Feed"; the
// page says what was added.
export function AddFeed({ ref, onOpen, onAdded }: Props) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        setOpen(next);
        if (next) {
          onOpen();
        }
      }}
    >
      <DialogTrigger
        render={
          <Button ref={ref}>
            <PlusIcon aria-hidden={true} data-icon="inline-start" />
            {t("feeds.add.open")}
          </Button>
        }
      />
      <DialogContent className="sm:max-w-md">
        <AddFeedSteps
          onAdded={(feed) => {
            setOpen(false);
            onAdded(feed);
          }}
        />
      </DialogContent>
    </Dialog>
  );
}
