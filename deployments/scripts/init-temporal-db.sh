#!/bin/sh
# Create the two databases the Temporal server keeps its own records
# in, beside the one Postgres made from POSTGRES_DB. Postgres runs this
# once, when it creates its data directory.
set -e
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<-SQL
  CREATE DATABASE temporal;
  CREATE DATABASE temporal_visibility;
SQL
