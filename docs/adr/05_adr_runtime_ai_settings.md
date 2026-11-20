# ADR 05: AI connections and models are runtime settings

Status: **Accepted**. Amends ADR 02: InfraSales names the services it uses.

## Context

Choosing a model through environment variables means editing the server's environment and
restarting for every change. Models change often, and keys must not lie around in plain text.

## Decision

- **Connections:** one API key per service. Today there is one service, OpenRouter. Its endpoint
  is fixed in `infrasales.ai.providers`, so a stored key is only ever sent to its own service.
- **Two model choices:** chat (extraction and the other reading jobs, ADR 06 §5) on OpenRouter
  or the mock, and embeddings (matching projects) on OpenRouter. Each is a provider and a model
  id. A purpose whose connection has no key is off; chat then fails its runs.
- **Stored** in `config_entry` (`ai_connection_openrouter`, `ai_models`) with revisions
  (`If-Match`), and audited without secrets. Admins edit them on the Settings page through
  `/api/ai`. They are never part of `/api/config`, which viewers read.
- **Keys are encrypted** with Fernet under `SECRETS_KEY` (`infrasales secrets-key` makes one) and are
  write-only: the API says whether a key is set, never what it is. A key that no longer decrypts
  (the secret changed) shows as unreadable and counts as unset.
- **The environment seeds once:** `OPENROUTER__API_KEY`, `LLM__PROVIDER`, `LLM__MODEL`,
  `EMBEDDING__PROVIDER` and `EMBEDDING__MODEL` are stored at startup where nothing is stored yet.
  After that the Settings page decides. Tuning (timeouts, retries) stays in the environment.
- **Models are picked from each service's list**, read through
  `/api/ai/connections/{provider}/models` with the stored key and searched as one types. A model
  the service does not list can still be typed, so a list that fails never blocks a choice.
- **Every run reads the settings when it starts:** a change applies from the next run, no
  restart.
- **Embeddings name their model:** vectors are compared only with those embedded by the same
  model, so changing it starts afresh instead of mixing vector spaces.

## Consequences

A deployment needs `SECRETS_KEY` and, for its first start, the key; everything else about models
is chosen in the app. Losing `SECRETS_KEY` means entering the key again. Another service is one
more entry in `infrasales.ai.providers`. Rotating `SECRETS_KEY` is not supported yet: Fernet's
`MultiFernet` would add it.
