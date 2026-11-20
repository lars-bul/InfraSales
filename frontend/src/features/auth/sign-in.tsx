import { CircleAlert, Info } from "lucide-react";
import { useId } from "react";
import { useTranslation } from "react-i18next";
import type { SessionInfo } from "#/client/types.gen.ts";
import { Alert, AlertDescription, AlertTitle } from "#/components/ui/alert.tsx";
import { Button, buttonVariants } from "#/components/ui/button.tsx";
import { Card, CardContent, CardHeader, CardTitle } from "#/components/ui/card.tsx";
import { Input } from "#/components/ui/input.tsx";
import { Label } from "#/components/ui/label.tsx";
import type { Problem } from "./sign-in-problem.ts";

interface Props {
  provider: SessionInfo["provider"];
  problem?: Problem | undefined;
  sessionEnded?: boolean | undefined; // the session ended while the page was open
}

type Notice = Problem | "ended";

// Why the visitor is here, at the top of the card. One reason only, a problem before an ended
// session: the problem is what just happened. An ended session is news, not an error.
function Callout({ notice }: { notice: Notice }) {
  const { t } = useTranslation();
  const ended = notice === "ended";
  return (
    <Alert variant={ended ? "default" : "destructive"}>
      {ended ? <Info aria-hidden={true} /> : <CircleAlert aria-hidden={true} />}
      <AlertTitle>{t(`signIn.callouts.${notice}.title`)}</AlertTitle>
      <AlertDescription>{t(`signIn.callouts.${notice}.description`)}</AlertDescription>
    </Alert>
  );
}

// The one way to sign in this deployment offers, never both. Native navigation only: a form post
// (basic) or a link to the identity provider (oidc); the browser follows the redirects and keeps
// the session cookie.
export function SignIn({ provider, problem, sessionEnded = false }: Props) {
  const { t } = useTranslation();
  const heading = useId();
  const username = useId();
  const password = useId();
  const notice: Notice | undefined = problem ?? (sessionEnded ? "ended" : undefined);
  return (
    <section aria-labelledby={heading} className="w-full max-w-sm">
      <Card className="[--card-spacing:--spacing(6)]">
        <CardHeader>
          <CardTitle>
            <h2 id={heading} className="font-semibold text-lg">
              {t("signIn.title")}
            </h2>
          </CardTitle>
        </CardHeader>
        <CardContent className="grid gap-4">
          {notice ? <Callout notice={notice} /> : null}
          {provider === "oidc" ? (
            <a
              href="/api/auth/login"
              className={buttonVariants({ size: "lg", className: "w-full" })}
            >
              {t("signIn.withProvider")}
            </a>
          ) : (
            <form method="post" action="/api/auth/login" className="grid gap-4">
              <div className="grid gap-1.5">
                <Label htmlFor={username}>{t("signIn.username")}</Label>
                <Input id={username} name="username" autoComplete="username" required={true} />
              </div>
              <div className="grid gap-1.5">
                <Label htmlFor={password}>{t("signIn.password")}</Label>
                <Input
                  id={password}
                  name="password"
                  type="password"
                  autoComplete="current-password"
                  required={true}
                />
              </div>
              <Button type="submit" size="lg" className="w-full">
                {t("signIn.submit")}
              </Button>
            </form>
          )}
        </CardContent>
      </Card>
    </section>
  );
}
