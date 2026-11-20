#!/bin/sh
# The e2e web server, run from the repo root with the test profile (playwright.config.ts):
# the production build, a fresh SQLite database that goes away with the server, `infrasales web`.
set -eu
pnpm --dir frontend build
data="$(mktemp -d)"
trap 'rm -rf "$data"' EXIT
trap 'exit 143' INT TERM
export DATABASE_URL="sqlite+aiosqlite:///$data/infrasales.db"
uv run infrasales migrate
uv run infrasales web &
wait $!
