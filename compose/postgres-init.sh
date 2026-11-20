#!/bin/sh
# Runs once, on an empty data volume, as the superuser (docker-entrypoint-initdb.d).
# Least privilege: infrasales_owner owns the schema and runs migrations, infrasales_app serves requests,
# infrasales_retention deletes expired rows; `infrasales migrate` grants the last two what they need,
# table by table. The passwords are for this local stack only.
set -eu

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname postgres <<'SQL'
CREATE ROLE infrasales_owner LOGIN PASSWORD 'owner';
CREATE ROLE infrasales_app LOGIN PASSWORD 'app';
CREATE ROLE infrasales_retention LOGIN PASSWORD 'retention';
-- A runaway statement gives up instead of holding locks.
ALTER ROLE infrasales_app SET statement_timeout = '10s';
ALTER ROLE infrasales_retention SET statement_timeout = '5min';
CREATE DATABASE infrasales OWNER infrasales_owner;
CREATE DATABASE infrasales_test OWNER infrasales_owner;
REVOKE ALL ON DATABASE infrasales, infrasales_test FROM PUBLIC;
GRANT CONNECT ON DATABASE infrasales, infrasales_test TO infrasales_app, infrasales_retention;
SQL

for database in infrasales infrasales_test; do
  psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$database" -c 'CREATE EXTENSION IF NOT EXISTS vector;'
done
