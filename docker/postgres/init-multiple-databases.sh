#!/bin/sh
set -eu

if [ -z "${OPENCLONING_POSTGRES_MULTIPLE_DATABASES:-}" ]; then
  exit 0
fi

OLD_IFS=$IFS
IFS=','
for db_name in $OPENCLONING_POSTGRES_MULTIPLE_DATABASES; do
  if [ -z "$db_name" ]; then
    continue
  fi

  psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<SQL
SELECT 'CREATE DATABASE "$db_name"'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = '$db_name')\gexec
SQL
done
IFS=$OLD_IFS
