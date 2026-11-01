#!/usr/bin/env bash
# Turn on Breatheasy Plus (Free/Plus plans + Razorpay payments) on the live service.
#   bash deploy/cloudrun/enable-payments.sh
# Run in Cloud Shell, after creating in the Razorpay dashboard (Test mode first):
#   1. API keys (Settings > API Keys): Key ID + Key Secret
#   2. Two subscription plans (Subscriptions > Plans): monthly 149 INR, yearly 1199 INR
#   3. A webhook (Settings > Webhooks): URL https://YOUR-APP-URL/api/billing/webhook,
#      a secret you choose, events subscription.activated, subscription.charged,
#      subscription.resumed, subscription.cancelled, subscription.halted
# Secrets are typed here (hidden), stored in Secret Manager, never in files or chat.
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

read -rp  "Razorpay Key ID (rzp_test_... or rzp_live_...): " KEY_ID
read -rsp "Razorpay Key Secret (hidden): " KEY_SECRET; echo
read -rsp "Razorpay webhook secret (hidden): " HOOK_SECRET; echo
read -rp  "Monthly plan ID (plan_..., blank to skip): " PLAN_M
read -rp  "Yearly plan ID (plan_..., blank to skip): " PLAN_Y
[ -n "$KEY_ID" ] && [ -n "$KEY_SECRET" ] && [ -n "$HOOK_SECRET" ] && { [ -n "$PLAN_M" ] || [ -n "$PLAN_Y" ]; } \
  || { echo "Key ID, Key Secret, webhook secret and at least one plan ID are needed."; exit 1; }

put_secret breatheasy-razorpay-key-secret "$KEY_SECRET"
put_secret breatheasy-razorpay-webhook-secret "$HOOK_SECRET"

gcloud run services update "$SERVICE" --region="$REGION" \
  --update-secrets="RAZORPAY_KEY_SECRET=breatheasy-razorpay-key-secret:latest,RAZORPAY_WEBHOOK_SECRET=breatheasy-razorpay-webhook-secret:latest" \
  --update-env-vars="PLANS_ENABLED=true,RAZORPAY_KEY_ID=$KEY_ID,RAZORPAY_PLAN_MONTHLY=$PLAN_M,RAZORPAY_PLAN_YEARLY=$PLAN_Y"

URL=$(gcloud run services describe "$SERVICE" --region="$REGION" --format='value(status.url)')
echo
echo "== Plans and payments are on. Webhook URL for Razorpay: $URL/api/billing/webhook"
echo "   Signed-out visitors now get open data; signed-in users get their monthly street-level searches."
echo "   To switch plans off again: gcloud run services update $SERVICE --region=$REGION --update-env-vars=PLANS_ENABLED=false"
