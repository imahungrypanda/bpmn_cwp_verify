## Current Lambda Code

See [`lambda_function.py`](../lambda_function.py) for the current Lambda handler implementation.

## Deploying as a Lambda to AWS

This project supports two deployment methods:

### Option 1: Container Image (Recommended)

The project includes a Dockerfile that builds a container image with Spin, gcc, and the Python package. This is the recommended approach for production deployments.

**See [Docker Build Guide](docker-build.md) for detailed instructions.**

Quick start:

```bash
# Build Lambda image
docker buildx build --platform linux/amd64 --target lambda -t bpmn-cwp-verify:lambda --load .

# Deploy to AWS (see docker-build.md for full steps)
export PROFILE=teacher # Replace this with whatever you named the role you are assuming
export REGION=us-east-1
export ACCOUNT_ID=$(aws sts get-caller-identity --profile "$PROFILE" --query Account --output text)
export REPO=bpmn-cwp-verify-docker
export FUNC_NAME=bpmn-cwp-verify-function

# Push to ECR and update Lambda function
aws ecr get-login-password --profile "$PROFILE" --region "$REGION" | \
  docker login --username AWS --password-stdin ${ACCOUNT_ID}.dkr.ecr.${REGION}.amazonaws.com

docker tag bpmn-cwp-verify:lambda ${ACCOUNT_ID}.dkr.ecr.${REGION}.amazonaws.com/${REPO}:latest
docker push ${ACCOUNT_ID}.dkr.ecr.${REGION}.amazonaws.com/${REPO}:latest

aws lambda update-function-code --profile "$PROFILE" --region "$REGION" \
  --function-name "$FUNC_NAME" \
  --image-uri ${ACCOUNT_ID}.dkr.ecr.${REGION}.amazonaws.com/${REPO}:latest
```

### Option 2: Zip-based Deployment (Legacy)

The following are steps on how to set up your lambda function so that it can use this package as a dependency using zip-based layers

### Steps to create the Zip

1. Make sure that the `build` package is installed in the python environment you have created for `bpmn_cwp_verify`
   - This can be done by simply using the command `pip install build`
1. Use the command `python -m build`. Once the command is executed, you should see a new directory named `dist`. Inside this new directory there should be several new files. The one you want to pay attention to is the one that ends with the file extension `.whl`
1. Now either in a terminal or your file explorer create a new directory with this specific directory structure `[any name] -> python -> lib -> [python version] -> site-packages`
   - The top layer directory can be named anything as long as it is not in the `bpmn_cwp_verify` directory. The subdirectory of `lib` should be the python version being used in the lambda function. At this moment, we are using a runtime of Python 3.12 so the directory should be named `python3.12`
1. In a python environment, run the command `pip install --upgrade [path to .whl file] -t [path to site-packages directory]`
1. Then zip everything from `python` and below (so excluding the parent directory)

Once you have the zip there are two paths to actually deploying the code to the lambda

### To deploy the lambda for the first time

#### Using the AWS UI

1. go to your AWS console and search up Lambda and click on the top result
1. Navigate to where it says `Layers`
1. If you already have a custom made layer, simply click on the custom layer and click on `Create Version`. If this is the first time creating a layer, simply click on `Create Layer`
1. Upload the zip file and select the runtime. Allow it some time to upload after clicking on `Create`
1. Once it is finished creating, navigate to the `Functions` tab of the Lambda console
1. Click on the function and scroll down to where it is titled `Layers`
1. If you already added the layer before, simply click on `Edit` then click on the drop down menu underneath the `Layer Version` section of the table and select the desired version. If you have not added the layer yet to the function, click on `Add layer` then select `Custom layers` from the different options it provides. Then your custom layer should appear from the dropdown menu. Select the layer. Your function is now ready to use the `bpmn_cwp_verify` package

#### Using the command line with AWS installed locally

1. Make sure you have the aws command line tools installed.
1. Setup a profile that connects to the AWS instant you want to deploy this to.
1. Run the command to create the function:

```shell
export REGION=us-east-1 # this is just an example and could be any location
export FUNC_NAME=bpmn-cwp-verify-function
export PROFILE=NAME_OF_THE_AWS_PROFILE

aws lambda create-function \
  --region "$REGION" \
  --profile "$PROFILE" \
  --function-name "$FUNC_NAME" \
  --runtime python3.12 \
  --role "IAM_ROLE_ARN/LambdaExec-bpmn-cwp-verify" \
  --handler lambda_function.lambda_handler \
  --zip-file fileb://bpmn-cwp-verify.zip
```

#### Testing the lambda

The following shell script demonstrates how to test your deployed Lambda function by constructing a test payload (using Python to read example files and encode them in JSON) and invoking the Lambda using the AWS CLI.

It first prepares a JSON payload from three test files (state.txt, test_cwp.xml, test_bpmn.bpmn) located in `test/resources/simple_example`. The payload is constructed by embedding the contents of these files in a JSON structure expected by the Lambda. The script then exports necessary environment variables for AWS CLI authentication and Lambda function identification.

Finally, it sends the payload to your Lambda function and saves the response to `/tmp/verify-response.json`. You should adjust the IAM profile name and other environment variables as needed for your specific deployment.

Review and update any file paths or parameters if your environment differs from the example.

```shell
PAYLOAD=$(python - <<'PY'
import json, pathlib
base = pathlib.Path("test/resources/simple_example")
state = (base / "state.txt").read_text()
cwp = (base / "test_cwp.xml").read_text()
bpmn = (base / "test_bpmn.bpmn").read_text()
event = {"body": json.dumps({"files": [state, cwp, bpmn]})}
print(json.dumps(event))
PY
)
export PROFILE=teacher # Replace this with whatever you named the role you are assuming
export REGION=us-east-1
export FUNC_NAME=bpmn-cwp-verify-function

aws lambda invoke \
  --profile "$PROFILE" \
  --region "$REGION" \
  --function-name "$FUNC_NAME" \
  --cli-binary-format raw-in-base64-out \
  --payload "$PAYLOAD" \
  /tmp/verify-response.json
```
