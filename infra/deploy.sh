#!/usr/bin/env bash
# Ship It deploy: one Lambda behind a public Function URL, plus the S3 / DynamoDB /
# EventBridge / Bedrock resources the engines bind to. Run from the repo root with AWS
# credentials in the environment. Safe to re-run — every step is create-or-update.
#
# ponytail: plain AWS CLI, no CDK/SAM/Terraform to install and no container to build. The
# whole app is stdlib Python, so the deployment package is a zip. Move to IaC when more than
# one person deploys it.
set -euo pipefail

NAME=${NAME:-epc-nexus}
export AWS_REGION=${AWS_REGION:-us-east-1}
ACCOUNT=$(aws sts get-caller-identity --query Account --output text)
BUCKET=${BUCKET:-$NAME-docs-$ACCOUNT}
TABLE=$NAME-audit
BUS=$NAME-bus
ROLE=$NAME-role
BUILD=$(mktemp -d)

echo "==> account $ACCOUNT / region $AWS_REGION"

# --- data plane ---------------------------------------------------------------
aws s3api create-bucket --bucket "$BUCKET" \
  $([ "$AWS_REGION" = us-east-1 ] || echo --create-bucket-configuration "LocationConstraint=$AWS_REGION") \
  >/dev/null 2>&1 || true
aws s3api put-bucket-versioning --bucket "$BUCKET" --versioning-configuration Status=Enabled
aws s3 sync sample_data "s3://$BUCKET/documents" --quiet   # tender, bids, policies, IST procedure

aws dynamodb create-table --table-name "$TABLE" --billing-mode PAY_PER_REQUEST \
  --attribute-definitions AttributeName=project,AttributeType=S AttributeName=seq,AttributeType=N \
  --key-schema AttributeName=project,KeyType=HASH AttributeName=seq,KeyType=RANGE \
  >/dev/null 2>&1 || true

aws events create-event-bus --name "$BUS" >/dev/null 2>&1 || true

# --- execution role -----------------------------------------------------------
aws iam create-role --role-name "$ROLE" --assume-role-policy-document \
  '{"Version":"2012-10-17","Statement":[{"Effect":"Allow","Principal":{"Service":"lambda.amazonaws.com"},"Action":"sts:AssumeRole"}]}' \
  >/dev/null 2>&1 || true
aws iam attach-role-policy --role-name "$ROLE" \
  --policy-arn arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole
aws iam put-role-policy --role-name "$ROLE" --policy-name epc-engines --policy-document "$(cat <<JSON
{"Version":"2012-10-17","Statement":[
 {"Effect":"Allow","Action":["s3:GetObject","s3:ListBucket"],"Resource":["arn:aws:s3:::$BUCKET","arn:aws:s3:::$BUCKET/*"]},
 {"Effect":"Allow","Action":"dynamodb:PutItem","Resource":"arn:aws:dynamodb:$AWS_REGION:$ACCOUNT:table/$TABLE"},
 {"Effect":"Allow","Action":"events:PutEvents","Resource":"arn:aws:events:$AWS_REGION:$ACCOUNT:event-bus/$BUS"},
 {"Effect":"Allow","Action":["textract:DetectDocumentText"],"Resource":"*"},
 {"Effect":"Allow","Action":["bedrock:InvokeModel","bedrock:InvokeModelWithResponseStream"],"Resource":"*"}]}
JSON
)"

# --- package ------------------------------------------------------------------
echo "==> packaging"
cp -r epc demo.py serve.py sample_data web "$BUILD/"
# Linux/x86_64 wheels explicitly: anthropic pulls pydantic-core, which is compiled, so a
# plain `pip install --target` on a mac ships wheels the Lambda runtime cannot import.
pip install -q --target "$BUILD" --only-binary=:all: \
  --platform manylinux2014_x86_64 --python-version 3.12 --implementation cp \
  'anthropic[bedrock]'   # Bedrock client; the app itself is stdlib
(cd "$BUILD" && zip -qr "$BUILD/app.zip" . -x '*.pyc' '*/__pycache__/*')

ENV="Variables={EPC_S3_BUCKET=$BUCKET,EPC_AUDIT_TABLE=$TABLE,EPC_EVENT_BUS=$BUS,EPC_LLM=1,EPC_MODEL=anthropic.claude-opus-5}"
if aws lambda get-function --function-name "$NAME" >/dev/null 2>&1; then
  aws lambda update-function-code --function-name "$NAME" --zip-file "fileb://$BUILD/app.zip" >/dev/null
  aws lambda wait function-updated --function-name "$NAME"
  aws lambda update-function-configuration --function-name "$NAME" --environment "$ENV" >/dev/null
else
  echo "==> waiting for IAM role to propagate"; sleep 12
  aws lambda create-function --function-name "$NAME" --runtime python3.12 --handler serve.handler \
    --role "arn:aws:iam::$ACCOUNT:role/$ROLE" --timeout 60 --memory-size 1024 \
    --zip-file "fileb://$BUILD/app.zip" --environment "$ENV" >/dev/null
  aws lambda wait function-active --function-name "$NAME"
fi

# --- public URL ---------------------------------------------------------------
aws lambda add-permission --function-name "$NAME" --statement-id public-url \
  --action lambda:InvokeFunctionUrl --principal '*' --function-url-auth-type NONE >/dev/null 2>&1 || true
URL=$(aws lambda create-function-url-config --function-name "$NAME" --auth-type NONE \
        --query FunctionUrl --output text 2>/dev/null \
      || aws lambda get-function-url-config --function-name "$NAME" --query FunctionUrl --output text)

rm -rf "$BUILD"
echo
echo "live: $URL"
echo "state: ${URL}api/state"
