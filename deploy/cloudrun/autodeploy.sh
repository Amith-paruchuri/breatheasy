#!/usr/bin/env bash
# One-time setup for automatic deploys: GitHub (main branch) -> Cloud Build -> Cloud Run.
#   bash deploy/cloudrun/autodeploy.sh connect   # then open the link it prints and approve
#   bash deploy/cloudrun/autodeploy.sh trigger   # after approving
set -euo pipefail
PROJECT_ID=${PROJECT_ID:-breatheeasy-512409}
REGION=${REGION:-asia-south1}
GH_REPO=${GH_REPO:-Amith-paruchuri/breatheasy}
CONN=breatheasy-github
SA=breatheasy-deployer@$PROJECT_ID.iam.gserviceaccount.com
gcloud config set project "$PROJECT_ID" >/dev/null

case "${1:-}" in
connect)
  gcloud services enable cloudbuild.googleapis.com secretmanager.googleapis.com run.googleapis.com artifactregistry.googleapis.com
  gcloud iam service-accounts describe "$SA" >/dev/null 2>&1 \
    || gcloud iam service-accounts create breatheasy-deployer --display-name="Breatheasy auto-deploy"
  for r in roles/run.admin roles/artifactregistry.writer roles/storage.admin roles/logging.logWriter; do
    gcloud projects add-iam-policy-binding "$PROJECT_ID" --member="serviceAccount:$SA" --role="$r" --condition=None -q >/dev/null
  done
  gcloud iam service-accounts add-iam-policy-binding "breatheasy-run@$PROJECT_ID.iam.gserviceaccount.com" \
    --member="serviceAccount:$SA" --role=roles/iam.serviceAccountUser -q >/dev/null
  PN=$(gcloud projects describe "$PROJECT_ID" --format='value(projectNumber)')
  gcloud projects add-iam-policy-binding "$PROJECT_ID" \
    --member="serviceAccount:service-$PN@gcp-sa-cloudbuild.iam.gserviceaccount.com" \
    --role=roles/secretmanager.admin --condition=None -q >/dev/null
  gcloud builds connections describe "$CONN" --region="$REGION" >/dev/null 2>&1 \
    || gcloud builds connections create github "$CONN" --region="$REGION"
  echo
  echo "== Open the authorization link above (if shown), approve, and install the Google Cloud Build app on $GH_REPO."
  echo "   Then run: bash deploy/cloudrun/autodeploy.sh trigger"
  ;;
trigger)
  STATE=$(gcloud builds connections describe "$CONN" --region="$REGION" --format='value(installationState.stage)')
  [ "$STATE" = "COMPLETE" ] || { gcloud builds connections describe "$CONN" --region="$REGION" --format='value(installationState.message,installationState.actionUri)'; exit 1; }
  gcloud builds repositories describe breatheasy --connection="$CONN" --region="$REGION" >/dev/null 2>&1 \
    || gcloud builds repositories create breatheasy --remote-uri="https://github.com/$GH_REPO.git" --connection="$CONN" --region="$REGION"
  gcloud builds triggers describe breatheasy-main --region="$REGION" >/dev/null 2>&1 \
    || gcloud builds triggers create github --name=breatheasy-main --region="$REGION" \
      --repository="projects/$PROJECT_ID/locations/$REGION/connections/$CONN/repositories/breatheasy" \
      --branch-pattern='^main$' --build-config=cloudbuild.yaml \
      --service-account="projects/$PROJECT_ID/serviceAccounts/$SA"
  gcloud builds triggers run breatheasy-main --region="$REGION" --branch=main
  echo "== Done. Every push to main now deploys automatically. Watch builds at:"
  echo "   https://console.cloud.google.com/cloud-build/builds;region=$REGION?project=$PROJECT_ID"
  ;;
*) echo "Usage: $0 connect|trigger"; exit 1 ;;
esac
