#!/usr/bin/env bash
# One-time Google Cloud setup for Breatheasy on Cloud Run.
#
#   ./deploy/cloudrun/setup.sh
#
# Run it from Cloud Shell (shell.cloud.google.com, gcloud already signed in) or any
# machine with gcloud installed and `gcloud auth login` done. It is safe to re-run:
# every step skips what already exists. It never prints secret values.
#
# What it creates (all in your project):
#   - required APIs enabled
#   - Artifact Registry repo for the container image
#   - Cloud SQL Postgres 16 (smallest shared-core tier, daily backups kept 7 days)
#   - service account for the app with only the roles it needs
#   - two API keys: a server key (Routes, Air Quality, Places) and a browser key
#     (Maps JavaScript API, locked to your app's URL after the first deploy)
#   - Secret Manager secrets: session secret, database URL, server key
# Then it asks you for the OAuth client ID (one console step) and writes deploy.env.
set -euo pipefail
cd "$(dirname "$0")"
ENV_FILE="deploy.env"

say() { printf '\n\033[1m== %s\033[0m\n' "$*"; }
ask() { local prompt=$1 default=${2:-} v; read -r -p "$prompt${default:+ [$default]}: " v; echo "${v:-$default}"; }

command -v gcloud >/dev/null || { echo "Install the Google Cloud CLI first: https://cloud.google.com/sdk/docs/install"; exit 1; }
[ -f "$ENV_FILE" ] && source "$ENV_FILE"

say "Project"
PROJECT_ID=${PROJECT_ID:-$(ask "Google Cloud project ID" "$(gcloud config get-value project 2>/dev/null || true)")}
REGION=${REGION:-$(ask "Region" "asia-south1")}   # Mumbai: closest to Delhi users
SERVICE=${SERVICE:-breatheasy}
SQL_INSTANCE=${SQL_INSTANCE:-breatheasy-db}
DB_NAME=breatheasy
DB_USER=breatheasy
REPO=breatheasy
SA_NAME=breatheasy-run
SA_EMAIL="$SA_NAME@$PROJECT_ID.iam.gserviceaccount.com"
gcloud config set project "$PROJECT_ID" >/dev/null
PROJECT_NUMBER=$(gcloud projects describe "$PROJECT_ID" --format='value(projectNumber)')

BILLING=$(gcloud billing projects describe "$PROJECT_ID" --format='value(billingEnabled)' 2>/dev/null || echo unknown)
if [ "$BILLING" = "False" ]; then
  echo "Billing is not enabled on $PROJECT_ID. Enable it at https://console.cloud.google.com/billing then re-run."
  exit 1
fi

say "Enabling APIs (takes a minute the first time)"
gcloud services enable \
  run.googleapis.com sqladmin.googleapis.com secretmanager.googleapis.com \
  artifactregistry.googleapis.com cloudbuild.googleapis.com iam.googleapis.com apikeys.googleapis.com \
  routes.googleapis.com airquality.googleapis.com places.googleapis.com maps-backend.googleapis.com

say "Artifact Registry"
gcloud artifacts repositories describe "$REPO" --location="$REGION" >/dev/null 2>&1 \
  || gcloud artifacts repositories create "$REPO" --repository-format=docker --location="$REGION" \
       --description="Breatheasy images"

say "Cloud SQL (Postgres 16). Creating an instance takes ~10 minutes."
if ! gcloud sql instances describe "$SQL_INSTANCE" >/dev/null 2>&1; then
  gcloud sql instances create "$SQL_INSTANCE" \
    --database-version=POSTGRES_16 --edition=enterprise --tier=db-f1-micro \
    --region="$REGION" --storage-size=10 --storage-auto-increase \
    --backup-start-time=20:30 --retained-backups-count=7 \
    --deletion-protection
fi
gcloud sql databases describe "$DB_NAME" --instance="$SQL_INSTANCE" >/dev/null 2>&1 \
  || gcloud sql databases create "$DB_NAME" --instance="$SQL_INSTANCE"
CONN_NAME=$(gcloud sql instances describe "$SQL_INSTANCE" --format='value(connectionName)')

secret_exists() { gcloud secrets describe "$1" >/dev/null 2>&1; }
put_secret() {  # name, value via stdin; never echoed
  if secret_exists "$1"; then gcloud secrets versions add "$1" --data-file=- >/dev/null
  else gcloud secrets create "$1" --replication-policy=automatic --data-file=- >/dev/null; fi
}

if ! secret_exists breatheasy-database-url; then
  DB_PASS=$(openssl rand -hex 24)
  if gcloud sql users list --instance="$SQL_INSTANCE" --format='value(name)' | grep -qx "$DB_USER"; then
    gcloud sql users set-password "$DB_USER" --instance="$SQL_INSTANCE" --password="$DB_PASS" >/dev/null
  else
    gcloud sql users create "$DB_USER" --instance="$SQL_INSTANCE" --password="$DB_PASS" >/dev/null
  fi
  printf 'postgresql+asyncpg://%s:%s@/%s?host=/cloudsql/%s' "$DB_USER" "$DB_PASS" "$DB_NAME" "$CONN_NAME" \
    | put_secret breatheasy-database-url
  unset DB_PASS
  echo "Database user created; connection string stored in Secret Manager."
fi

say "Session secret"
secret_exists breatheasy-session-secret || { openssl rand -hex 32 | tr -d '\n' | put_secret breatheasy-session-secret; echo "Created."; }

say "Google Maps Platform API keys"
if ! secret_exists breatheasy-maps-server-key; then
  echo "Create new restricted keys now (recommended), or paste keys you already made?"
  if [ "$(ask "Create keys? (y/n)" y)" = "y" ]; then
    gcloud services api-keys describe breatheasy-server --location=global >/dev/null 2>&1 || \
      gcloud services api-keys create --key-id=breatheasy-server --display-name="Breatheasy server" \
        --api-target=service=routes.googleapis.com \
        --api-target=service=airquality.googleapis.com \
        --api-target=service=places.googleapis.com >/dev/null
    gcloud services api-keys get-key-string breatheasy-server --location=global --format='value(keyString)' \
      | tr -d '\n' | put_secret breatheasy-maps-server-key
  else
    read -r -s -p "Paste the SERVER key (Routes + Air Quality + Places; input hidden): " K; echo
    printf '%s' "$K" | put_secret breatheasy-maps-server-key; unset K
  fi
  echo "Server key stored in Secret Manager (never in the image or env files)."
fi
if [ -z "${MAPS_BROWSER_KEY:-}" ]; then
  if [ "$(ask "Create the browser key (Maps JavaScript API)? (y/n)" y)" = "y" ]; then
    gcloud services api-keys describe breatheasy-browser --location=global >/dev/null 2>&1 || \
      gcloud services api-keys create --key-id=breatheasy-browser --display-name="Breatheasy browser" \
        --api-target=service=maps-backend.googleapis.com \
        --allowed-referrers="http://localhost:5173/*" >/dev/null
    MAPS_BROWSER_KEY=$(gcloud services api-keys get-key-string breatheasy-browser --location=global --format='value(keyString)')
  else
    MAPS_BROWSER_KEY=$(ask "Browser key (Maps JavaScript API; public by design, restricted by website)")
  fi
fi
MAP_ID=${MAP_ID:-$(ask "Map ID (optional; Enter to use Google's demo map style)" "")}
CONTACT_EMAIL=${CONTACT_EMAIL:-$(ask "Contact email (sent in the User-Agent to the open-data fallback services)" "")}

say "Service account"
gcloud iam service-accounts describe "$SA_EMAIL" >/dev/null 2>&1 \
  || gcloud iam service-accounts create "$SA_NAME" --display-name="Breatheasy Cloud Run"
gcloud projects add-iam-policy-binding "$PROJECT_ID" --member="serviceAccount:$SA_EMAIL" \
  --role=roles/cloudsql.client --condition=None >/dev/null
for s in breatheasy-database-url breatheasy-session-secret breatheasy-maps-server-key; do
  gcloud secrets add-iam-policy-binding "$s" --member="serviceAccount:$SA_EMAIL" \
    --role=roles/secretmanager.secretAccessor >/dev/null
done
# Cloud Build runs as the default compute service account in newer projects; it must
# read the uploaded source, write logs and push the image.
for role in roles/artifactregistry.writer roles/storage.objectViewer roles/logging.logWriter; do
  gcloud projects add-iam-policy-binding "$PROJECT_ID" \
    --member="serviceAccount:$PROJECT_NUMBER-compute@developer.gserviceaccount.com" \
    --role="$role" --condition=None >/dev/null 2>&1 || true
done

say "Google sign-in (one manual step in the console)"
if [ -z "${OAUTH_CLIENT_ID:-}" ]; then
  cat <<MSG
 1. Open https://console.cloud.google.com/auth/branding?project=$PROJECT_ID
    App name "Breatheasy", your support email, and the privacy policy URL
    (https://YOUR-APP-URL/privacy, you can add it after the first deploy).
    Audience: External. Scopes: only the defaults (openid, email, profile).
 2. Open https://console.cloud.google.com/auth/clients?project=$PROJECT_ID
    Create client > Web application > name "Breatheasy web".
    Authorized JavaScript origins: http://localhost:5173 for now
    (the deploy script prints the production URL to add next).
 3. Copy the Client ID (ends in .apps.googleusercontent.com). No client secret is needed.
MSG
  OAUTH_CLIENT_ID=$(ask "OAuth Client ID (Enter to skip; sign-in stays off until set)" "")
fi

cat > "$ENV_FILE" <<CONF
# Written by setup.sh. Non-secret settings only; secrets live in Secret Manager.
PROJECT_ID=$PROJECT_ID
REGION=$REGION
SERVICE=$SERVICE
SQL_INSTANCE=$SQL_INSTANCE
CONN_NAME=$CONN_NAME
SA_EMAIL=$SA_EMAIL
REPO=$REPO
MAPS_BROWSER_KEY=$MAPS_BROWSER_KEY
MAP_ID=$MAP_ID
OAUTH_CLIENT_ID=$OAUTH_CLIENT_ID
CONTACT_EMAIL=${CONTACT_EMAIL:-}
MAX_INSTANCES=${MAX_INSTANCES:-4}
# 1 keeps one copy of the app always warm (no 5-10 s cold start for the first visitor),
# at a small always-on cost. Set 0 to pay only for traffic.
MIN_INSTANCES=${MIN_INSTANCES:-1}
CSP_MODE=${CSP_MODE:-report-only}
CONF

say "Done. Next: ./deploy/cloudrun/deploy.sh"
echo "Strongly recommended now (console): set a billing budget alert and per-day quotas on"
echo "Routes API, Air Quality API and Places API. See deploy/LAUNCH_CHECKLIST.md."
