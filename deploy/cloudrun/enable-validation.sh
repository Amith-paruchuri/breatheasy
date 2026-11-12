#!/usr/bin/env bash
# Turn on validation against CPCB monitoring stations, every 3 hours.
#   bash deploy/cloudrun/enable-validation.sh
# Needs a free data.gov.in API key (sign in at data.gov.in > My Account > Generate API Key).
# The key is typed here (hidden) and stored in Secret Manager, never in files or chat.
# Cost: about 60 Google air-quality history calls per run, 8 runs a day (~US$0.25/day).
set -euo pipefail
cd "$(dirname "$0")"
[ -f deploy.env ] && source deploy.env
PROJECT_ID=${PROJECT_ID:-breatheeasy-512409}
REGION=${REGION:-asia-south1}
SERVICE=${SERVICE:-breatheasy}
SA_EMAIL=${SA_EMAIL:-breatheasy-run@$PROJECT_ID.iam.gserviceaccount.com}
gcloud config set project "$PROJECT_ID" >/dev/null

put_secret() {  # name, value
  if gcloud secrets describe "$1" >/dev/null 2>&1; then
    printf '%s' "$2" | gcloud secrets versions add "$1" --data-file=- >/dev/null
  else
    printf '%s' "$2" | gcloud secrets create "$1" --replication-policy=automatic --data-file=- >/dev/null
  fi
  gcloud secrets add-iam-policy-binding "$1" --member="serviceAccount:$SA_EMAIL" \
    --role=roles/secretmanager.secretAccessor >/dev/null
}

read -rsp "data.gov.in API key (hidden): " DG_KEY; echo
[ -n "$DG_KEY" ] || { echo "The data.gov.in key is needed."; exit 1; }
TOKEN=$(head -c 24 /dev/urandom | base64 | tr -dc 'A-Za-z0-9' | head -c 32)
put_secret breatheasy-datagov-key "$DG_KEY"
put_secret breatheasy-validation-token "$TOKEN"

gcloud run services update "$SERVICE" --region="$REGION" \
  --update-secrets="DATAGOV_API_KEY=breatheasy-datagov-key:latest,VALIDATION_TOKEN=breatheasy-validation-token:latest"
URL=$(gcloud run services describe "$SERVICE" --region="$REGION" --format='value(status.url)')

gcloud services enable cloudscheduler.googleapis.com >/dev/null
if gcloud scheduler jobs describe breatheasy-validation --location="$REGION" >/dev/null 2>&1; then
  gcloud scheduler jobs update http breatheasy-validation --location="$REGION" --schedule="7 */3 * * *" \
    --uri="$URL/api/validation/run" --http-method=POST --update-headers="X-Validation-Token=$TOKEN" \
    --attempt-deadline=300s >/dev/null
else
  gcloud scheduler jobs create http breatheasy-validation --location="$REGION" --schedule="7 */3 * * *" \
    --time-zone="Asia/Kolkata" --uri="$URL/api/validation/run" --http-method=POST \
    --headers="X-Validation-Token=$TOKEN" --attempt-deadline=300s >/dev/null
fi

echo "== Running the first comparison now (about a minute)..."
curl -s -X POST -H "X-Validation-Token: $TOKEN" "$URL/api/validation/run"; echo
echo
echo "== Validation is on: every 3 hours. Results: $URL/validation"
