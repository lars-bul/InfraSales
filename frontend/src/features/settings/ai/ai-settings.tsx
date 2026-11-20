import { useSuspenseQuery } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { useId } from "react";
import { useTranslation } from "react-i18next";
import { readAiSettingsOptions } from "#/client/@tanstack/react-query.gen.ts";
import { ConnectionForm } from "./connection-form.tsx";
import { ModelsForm } from "./models-form.tsx";

function Section({
  title,
  description,
  children,
}: {
  title: string;
  description: string;
  children: (id: string) => ReactNode;
}) {
  const id = useId();
  return (
    <section aria-labelledby={id} className="grid gap-5 rounded-xl border bg-card p-4 sm:p-6">
      <header className="grid gap-1">
        <h2 id={id} className="font-heading font-medium">
          {title}
        </h2>
        <p className="text-muted-foreground text-sm">{description}</p>
      </header>
      {children(id)}
    </section>
  );
}

export function AiSettings() {
  const { t } = useTranslation();
  const { data } = useSuspenseQuery(readAiSettingsOptions());
  return (
    <>
      <Section
        title={t("settings.ai.connections")}
        description={t("settings.ai.connectionsDescription")}
      >
        {() => (
          <>
            {data.keys_storable ? null : (
              <p className="text-sm text-warning">{t("settings.ai.unstorable")}</p>
            )}
            <div className="grid gap-6">
              {data.connections.map((connection) => (
                <ConnectionForm
                  key={connection.provider}
                  connection={connection}
                  storable={data.keys_storable}
                />
              ))}
            </div>
          </>
        )}
      </Section>
      <Section title={t("settings.ai.models")} description={t("settings.ai.modelsDescription")}>
        {(id) => <ModelsForm models={data.models} labelledBy={id} />}
      </Section>
    </>
  );
}
