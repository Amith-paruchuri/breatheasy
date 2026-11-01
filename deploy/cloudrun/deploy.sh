#!/usr/bin/env bash
# Build the image with Cloud Build and deploy it to Cloud Run.
#   ./deploy/cloudrun/deploy.sh
# Re-run for every release. Needs deploy.env from setup.sh.
set -euo pipefail
cd "$(dirname "$0")"
[ -f deploy.env ] || { echo "Run ./deploy/cloudrun/setup.sh first."; exit 1; }
source deploy.env
ROOT=$(cd ../.. && pwd)

TAG=$(cd "$ROOT" && git rev-parse --short HEAD 2>/dev/null || date +%Y%m%d-%H%M%S)
IMAGE="$REGION-docker.pkg.dev/$PROJECT_ID/$REPO/app:$TAG"
gcloud config set project "$PROJECT_ID" >/dev/null

# Street-level map layer (parks, lakes, busy roads, industrial, construction) from
# OpenStreetMap. Built once here because Cloud Shell can reach the Overpass API;
# delete backend/app/data/environment.json.gz to refresh it (every month or two).
ENV_LAYER="$ROOT/backend/app/data/environment.json.gz"
if [ ! -f "$ENV_LAYER" ]; then
  echo "== Building the street-level map layer from OpenStreetMap (first time only, about 5-10 min)"
  python3 "$ROOT/backend/scripts/build_environment.py" --contact "${CONTACT_EMAIL:-}" \
    || echo "WARNING: couldn't build the map layer; deploying without park/road context. Re-run deploy.sh later."
fi

echo "== Building $IMAGE"
gcloud builds submit "$ROOT" --tag "$IMAGE" --region="$REGION"

USER_AGENT="Breatheasy/1.0 (+${CONTACT_EMAIL:-no-contact-set})"
ENV_VARS="ENV=production,PROVIDER=google,PROVIDER_FALLBACK=true,CSP_MODE=$CSP_MODE"
ENV_VARS+=",GOOGLE_MAPS_BROWSER_KEY=$MAPS_BROWSER_KEY,GOOGLE_MAP_ID=$MAP_ID,GOOGLE_OAUTH_CLIENT_ID=$OAUTH_CLIENT_ID"
ENV_VARS+=",LOG_LEVEL=INFO"

echo "== Deploying $SERVICE to Cloud Run ($REGION)"
gcloud run deploy "$SERVICE" \
  --image="$IMAGE" \
  --region="$REGION" \
  --service-account="$SA_EMAIL" \
  --add-cloudsql-instances="$CONN_NAME" \
  --update-secrets="DATABASE_URL=breatheasy-database-url:latest,SESSION_SECRET=breatheasy-session-secret:latest,GOOGLE_MAPS_SERVER_KEY=breatheasy-maps-server-key:latest" \
  --update-env-vars="^|^${ENV_VARS//,/|}|USER_AGENT=$USER_AGENT" \
  --allow-unauthenticated \
  --cpu=1 --memory=1Gi --concurrency=40 --timeout=60 \
  --min-instances="${MIN_INSTANCES:-1}" --max-instances="${MAX_INSTANCES:-4}" \
  --cpu-boost \
  --startup-probe="httpGet.path=/healthz,initialDelaySeconds=2,periodSeconds=3,failureThreshold=20,timeoutSeconds=2" \
  --liveness-probe="httpGet.path=/healthz,periodSeconds=30,timeoutSeconds=3,failureThreshold=3"

URL=$(gcloud run services describe "$SERVICE" --region="$REGION" --format='value(status.url)')
echo
echo "== Live at $URL"

# Lock the browser key to the app's URL (plus localhost for development).
if gcloud services api-keys describe breatheasy-browser --location=global >/dev/null 2>&1; then
  # Cloud Run serves each service on two URLs; allow both.
  PROJECT_NUMBER=$(gcloud projects describe "$PROJECT_ID" --format='value(projectNumber)')
  URL2="https://$SERVICE-$PROJECT_NUMBER.$REGION.run.app"
  REFERRERS="$URL/*,$URL2/*,http://localhost:5173/*"
  [ -n "${CUSTOM_DOMAIN:-}" ] && REFERRERS="https://$CUSTOM_DOMAIN/*,$REFERRERS"
  gcloud services api-keys update breatheasy-browser --location=global --allowed-referrers="$REFERRERS" >/dev/null \
    && echo "Browser key restricted to: $REFERRERS"
fi

curl -fsS "$URL/readyz" >/dev/null && echo "Readiness check passed (database reachable)." \
  || echo "WARNING: $URL/readyz failed; check logs: gcloud run services logs read $SERVICE --region=$REGION"

cat <<MSG

If you haven't yet:
  - Add $URL and https://$SERVICE-$(gcloud projects describe "$PROJECT_ID" --format='value(projectNumber)').$REGION.run.app
    to the OAuth client's "Authorized JavaScript origins"
    (https://console.cloud.google.com/auth/clients?project=$PROJECT_ID)
  - Set the consent screen's privacy policy to $URL/privacy and terms to $URL/terms
MSG
