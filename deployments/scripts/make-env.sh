#!/bin/sh
# Prepare a local run: write .env from .env.example with generated
# secrets, then render the settings templates from it into env/.
#
# Usage: make-env.sh
#
# An existing .env is left unchanged, and env/ is rendered from it
# again.

set -eu

cd "$(dirname "$0")/../.."

random_hex() {
  od -An -tx1 -N32 /dev/urandom | tr -d ' \n'
}

if [ -e .env ]; then
  echo ".env exists; left unchanged"
else
  umask 077
  tmp=".env.tmp.$$"
  trap 'rm -f "$tmp"' EXIT
  sed -e "s/^vault_bugflow_postgres_password=.*/vault_bugflow_postgres_password=$(random_hex)/" \
      -e "s/^vault_bugflow_webhook_secret=.*/vault_bugflow_webhook_secret=$(random_hex)/" \
      -e "s/^vault_bugflow_litellm_master_key=.*/vault_bugflow_litellm_master_key=sk-$(random_hex)/" \
      .env.example > "$tmp"
  mv "$tmp" .env
  trap - EXIT
  cat <<MSG
Wrote .env with a generated Postgres password, webhook secret and proxy
key. The rest is yours to fill in; docs/deploying.md describes each
variable. Run make env again after changing .env.

Postgres reads its password only when it creates its data volume. If a
volume from an earlier run exists, set vault_bugflow_postgres_password
in .env to the password that volume was created with, or remove the
volume.
MSG
fi

uv run python deployments/scripts/render_env.py .env env
