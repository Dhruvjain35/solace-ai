#!/usr/bin/env bash
#
# upload_models.sh — push trained triage ML artifacts to S3 so the next CodeBuild
# run bakes them into the Lambda image (see buildspec.yml pre_build).
#
# Usage:
#   ./scripts/upload_models.sh <local_artifacts_dir>
#
# Expects, in <local_artifacts_dir>, the outputs of the triagegeist-clinical-ai
# pipeline notebook:
#   artifacts.pkl                  (REQUIRED — n_folds, feature_names, label encoders,
#                                    mlp_models, mlp_scalers, meta_learner, opt_thresholds,
#                                    conformal sets; without it the ensemble stays disabled)
#   lgbm_fold{0..4}.txt            (REQUIRED — LightGBM boosters; any missing => ensemble off)
#   xgb_fold{0..4}.txt             (optional — enables stacking; else lgbm_only mode)
#   cat_fold{0..4}.txt             (optional — CatBoost; .txt format via save_model)
#
# artifacts.pkl is uploaded uncompressed; fold .txt files are gzipped to match the
# loader's S3 fetch path (models/<name>.txt.gz).
set -euo pipefail

BUCKET="${MODELS_BUCKET:-solace-lambda-deploy-704229156617}"
PREFIX="${MODELS_PREFIX:-models}"
REGION="${AWS_REGION:-us-east-1}"
SRC="${1:?usage: upload_models.sh <local_artifacts_dir>}"

echo "Uploading artifacts from '$SRC' -> s3://$BUCKET/$PREFIX/ (region $REGION)"

# Required metadata pickle (uncompressed)
if [[ -f "$SRC/artifacts.pkl" ]]; then
  aws s3 cp "$SRC/artifacts.pkl" "s3://$BUCKET/$PREFIX/artifacts.pkl" --region "$REGION"
  echo "  uploaded artifacts.pkl"
else
  echo "  ERROR: $SRC/artifacts.pkl missing — the ensemble cannot load without it." >&2
  exit 1
fi

# Per-fold model files: gzip then upload as <name>.txt.gz
shopt -s nullglob
for type in lgbm xgb cat; do
  for i in 0 1 2 3 4; do
    f="$SRC/${type}_fold${i}.txt"
    if [[ -f "$f" ]]; then
      gzip -c "$f" | aws s3 cp - "s3://$BUCKET/$PREFIX/${type}_fold${i}.txt.gz" --region "$REGION"
      echo "  uploaded ${type}_fold${i}.txt.gz"
    else
      echo "  skip ${type}_fold${i}.txt (not present)"
    fi
  done
done

echo "Done. Now redeploy so the image picks them up:"
echo "  aws codebuild start-build --project-name solace-api-deploy --region $REGION"
echo "Then confirm:  curl -s https://djfjrel7b1ebi.cloudfront.net/health"
