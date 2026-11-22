# Docker Build Guide

This guide explains how to build the different Docker images for this project. The Dockerfile uses multi-stage builds with different targets for different use cases.

## Available Build Targets

### 1. `base` - Base image with Spin binary

Contains the Lambda Python runtime, Spin model checker, and gcc (for compiling pan when Spin runs).

### 2. `dev` - Development environment

Extends `base` and installs the Python package in editable mode for local development with hot reload.

### 3. `lambda` - Production Lambda image

Extends `base` and installs the Python package in production mode with the Lambda handler.

### 4. `spin-layer` - Lambda layer with just Spin binary

Creates a Lambda layer zip containing only the Spin binary (for use with zip-based Lambda functions).

### 5. `artifact` - Spin layer artifact

A minimal stage that extracts the Spin layer zip file from `spin-layer` for easy publishing to AWS Lambda. Uses `scratch` as the base to minimize size.

## Building Images

### Development Image (for local testing)

```bash
docker build --target dev -t bpmn-cwp-verify:dev .
```

**Usage:**

```bash
# Run interactive shell (override Lambda entrypoint)
docker run --rm -it --entrypoint /bin/bash -v $(pwd):/app bpmn-cwp-verify:dev

# Test Spin
docker run --rm --entrypoint /bin/bash bpmn-cwp-verify:dev -c "spin -V"

# Test Python imports
docker run --rm --entrypoint /bin/bash bpmn-cwp-verify:dev -c "python -c 'from bpmncwpverify.cli import web_verify; print(\"Import successful\")'"
```

### Lambda Image (for AWS deployment)

```bash
docker buildx build --platform linux/amd64 --target lambda -t bpmn-cwp-verify:lambda --load .
```

**Note:** The `--load` flag is required to load the image into your local Docker daemon. Without it, the image only exists in the buildx cache. This builds for x86_64 architecture, which matches the Lambda function configuration.

### Spin Layer (for Lambda layer deployment)

**Build the layer artifact:**

```bash
docker buildx build --platform linux/amd64 --target artifact -o type=local,dest=. .
```

This creates `spin-layer.zip` in the current directory.

**Publish to Lambda:**

```bash
aws lambda publish-layer-version \
  --region us-east-1 \
  --layer-name spin-binary \
  --zip-file fileb://spin-layer.zip \
  --compatible-runtimes python3.12 \
  --compatible-architectures x86_64
```

## Deploying Lambda Image to AWS

### Prerequisites

- AWS CLI configured with appropriate profile
- ECR permissions (your role needs `ecr:*` permissions to push images)
- Lambda function already created (or permissions to create one)

### Deployment Steps

```bash
# Set your variables
export PROFILE=teacher  # or your AWS profile
export REGION=us-east-1
export ACCOUNT_ID=$(aws sts get-caller-identity --profile "$PROFILE" --query Account --output text)
export REPO=bpmn-cwp-verify
export FUNC_NAME=bpmn-cwp-verify-function

# 1. Create ECR repository (if it doesn't exist)
aws ecr create-repository \
  --profile "$PROFILE" \
  --region "$REGION" \
  --repository-name "$REPO" || true

# 2. Login to ECR
aws ecr get-login-password --profile "$PROFILE" --region "$REGION" | \
  docker login --username AWS --password-stdin ${ACCOUNT_ID}.dkr.ecr.${REGION}.amazonaws.com

# 3. Tag the image
docker tag bpmn-cwp-verify:lambda \
  ${ACCOUNT_ID}.dkr.ecr.${REGION}.amazonaws.com/${REPO}:latest

# 4. Push to ECR
docker push ${ACCOUNT_ID}.dkr.ecr.${REGION}.amazonaws.com/${REPO}:latest

# 5. Update Lambda function
aws lambda update-function-code \
  --profile "$PROFILE" \
  --region "$REGION" \
  --function-name "$FUNC_NAME" \
  --image-uri ${ACCOUNT_ID}.dkr.ecr.${REGION}.amazonaws.com/${REPO}:latest
```

### Update Function Configuration (optional)

Lambda functions have default settings that may need adjustment for Spin verification:

- **Timeout**: Maximum execution time (default: 3 seconds, max: 900 seconds/15 minutes). Spin verification can take time, so increase this if functions timeout.
- **Memory**: RAM allocation (default: 128MB, max: 10GB). More memory also gives more CPU proportionally. Spin's gcc compilation benefits from more memory/CPU.

Recommended settings for Spin verification:

```bash
aws lambda update-function-configuration \
  --profile "$PROFILE" \
  --region "$REGION" \
  --function-name "$FUNC_NAME" \
  --memory-size 1024 \
  --timeout 60
```

## Testing the Lambda Function

```bash
# Create test payload (if you don't have one)
python3 << 'EOF'
import json
import pathlib

root = pathlib.Path('.')
files = [
  (root/'test/resources/simple_example/test_bpmn.bpmn').read_text(),
  (root/'test/resources/simple_example/test_cwp.xml').read_text(),
  (root/'test/resources/simple_example/state.txt').read_text(),
]
print(json.dumps({"body": json.dumps({"files": files})}))
EOF > test-payload.json

# Invoke Lambda
aws lambda invoke \
  --profile "$PROFILE" \
  --region "$REGION" \
  --function-name "$FUNC_NAME" \
  --cli-binary-format raw-in-base64-out \
  --payload file://test-payload.json \
  response.json

# Check response
cat response.json
```

## Troubleshooting

### Can't push to ECR: "not authorized to perform: ecr:InitiateLayerUpload"

- Your role needs ECR permissions. Request the teacher/admin to add ECR permissions to your role.

### Lambda function fails with "Unable to import module"

- Make sure you're building the `lambda` target, not just `base` or `dev`.
- Verify the Lambda handler file (`lambda_function.py`) is copied in the Dockerfile.

### Spin not found in Lambda

- The Lambda image includes Spin in `/opt/bin/spin`. The PATH is set automatically.
- If using a layer instead, ensure the layer is attached and PATH includes `/opt/bin`.

## Architecture Notes

- **Base stage**: Uses Amazon Linux 2023 (Lambda Python 3.12 base image)
- **Spin version**: 6.5.2 (built from source because the AWS Lambda base image doesn't have Spin available as a package)
- **Build tools**: gcc, make, bison (for yacc compatibility), wget
- **Runtime dependencies**: gcc (for Spin's `-run` mode which compiles pan.c)

The Lambda image is ~500MB+ due to including:

- Python runtime
- All Python dependencies
- Spin binary
- gcc and make (for Spin's runtime compilation)
