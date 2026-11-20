import { SearchIcon } from "lucide-react";
import { type RefObject, useEffect, useId, useState } from "react";
import { useTranslation } from "react-i18next";
import { InputGroup, InputGroupAddon, InputGroupInput } from "#/components/ui/input-group.tsx";
import { Label } from "#/components/ui/label.tsx";

const TYPING_MS = 300; // the search waits for a pause in typing
const NOTHING = Symbol("nothing sent"); // since the words last came back

/**
 * The search box: it keeps what is typed and passes it on after a pause, and takes the words
 * from outside when they change there (going back, "Clear filters").
 */
export function SearchBox({
  search,
  onSearch,
  placeholder,
  input,
}: {
  search: string | undefined;
  onSearch: (search: string | undefined) => void;
  placeholder: string | undefined;
  input: RefObject<HTMLInputElement | null>;
}) {
  const { t } = useTranslation();
  const id = useId();
  const [typed, setTyped] = useState(search ?? "");
  const [seen, setSeen] = useState(search);
  const [sent, setSent] = useState<string | undefined | typeof NOTHING>(NOTHING);
  if (search !== seen) {
    setSeen(search);
    setSent(NOTHING);
    if (search !== sent) {
      setTyped(search ?? ""); // changed from outside, not the echo of what was typed
    }
  }

  useEffect(() => {
    const next = typed.trim() || undefined;
    if (next === search) {
      return;
    }
    const wait = setTimeout(() => {
      setSent(next);
      onSearch(next);
    }, TYPING_MS);
    return () => clearTimeout(wait);
  }, [typed, search, onSearch]);

  return (
    <div>
      <Label htmlFor={id} className="sr-only">
        {t("filters.search")}
      </Label>
      <InputGroup className="w-64">
        <InputGroupAddon>
          <SearchIcon aria-hidden={true} />
        </InputGroupAddon>
        <InputGroupInput
          ref={input}
          id={id}
          type="search"
          value={typed}
          placeholder={placeholder}
          onChange={(event) => setTyped(event.target.value)}
        />
      </InputGroup>
    </div>
  );
}
