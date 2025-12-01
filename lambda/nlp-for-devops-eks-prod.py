import boto3
import base64
import subprocess
import os
import json

# --- Configuration ---
CLUSTER_NAME = "django-cluster"
REGION = "us-east-1"
# ---------------------


def write_ca_and_kubeconfig():
    """
    1. Get EKS cluster endpoint + CA data using Boto3.
    2. Write the CA certificate to /tmp/ca.crt.
    3. Write /tmp/kubeconfig using the aws-iam-authenticator executable.
    """
    eks = boto3.client("eks", region_name=REGION)

    print(f"Fetching EKS cluster info for {CLUSTER_NAME} in {REGION}...")
    cluster_info = eks.describe_cluster(name=CLUSTER_NAME)["cluster"]

    endpoint = cluster_info["endpoint"]
    ca_data = cluster_info["certificateAuthority"]["data"]

    # 1. Write CA file (binary)
    ca_path = "/tmp/ca.crt"
    # base64.b64decode converts the certificate authority data from Base64
    with open(ca_path, "wb") as f:
        f.write(base64.b64decode(ca_data))
    print(f"Wrote CA certificate to {ca_path}")

    # 2. Generate Kubeconfig using aws-iam-authenticator
    # Note: /opt/bin/aws-iam-authenticator is the expected path in a Lambda layer
    kubeconfig_content = f"""
apiVersion: v1
clusters:
- cluster:
    certificate-authority: {ca_path}
    server: {endpoint}
  name: eks
contexts:
- context:
    cluster: eks
    user: lambda
  name: lambda
current-context: lambda
users:
- name: lambda
  user:
    exec:
      apiVersion: "client.authentication.k8s.io/v1beta1"
      command: /opt/bin/aws-iam-authenticator  # <-- CORRECTED PATH/COMMAND
      args:
        - "token"
        - "-i"
        - "{CLUSTER_NAME}"
        # We omit the region argument, as it's often inferred or not needed
        # by the authenticator when running in the AWS environment.
"""

    kubeconfig_path = "/tmp/kubeconfig"
    print(f"Writing kubeconfig to {kubeconfig_path}")

    with open(kubeconfig_path, "w") as f:
        f.write(kubeconfig_content)

    return kubeconfig_path


def run_kubectl(kubeconfig_path, args):
    """
    Executes a kubectl command using the generated kubeconfig.
    """
    # The kubectl binary is expected to be in /opt/bin from the Lambda Layer
    cmd = ["/opt/bin/kubectl", "--kubeconfig", kubeconfig_path] + args

    print("Running command:", " ".join(cmd))

    try:
        # Check output raises CalledProcessError on non-zero exit code
        output = subprocess.check_output(cmd, stderr=subprocess.STDOUT)
        return output.decode("utf-8")

    except subprocess.CalledProcessError as e:
        print("---- KUBECTL ERROR (CalledProcessError) ----")
        # Print the output that contains the underlying error (e.g., connection fail)
        print(e.output.decode("utf-8"))
        print("---- END ERROR ----")
        raise
    except FileNotFoundError:
        # Handle case where /opt/bin/kubectl might not be present
        print("---- KUBECTL ERROR (FileNotFoundError) ----")
        print("Error: kubectl binary not found at /opt/bin/kubectl. Check your Lambda Layer.")
        print("---- END ERROR ----")
        raise


def lambda_handler(event, context):
    """
    Main Lambda entry point.
    """

    print("Execution role ARN:", context.invoked_function_arn)

    sts = boto3.client("sts")
    identity = sts.get_caller_identity()
    print("STS Identity:", identity)
    # Debugging environment info from the original logs
    print("PATH=", os.environ.get("PATH"))
    print("ls /opt/bin", subprocess.getoutput("ls -l /opt/bin"))

    try:
        kubeconfig_path = write_ca_and_kubeconfig()
    except Exception as e:
        return {
            "statusCode": 500,
            "message": "Failed to generate kubeconfig.",
            "error": str(e)
        }

    # Determine action based on the input event
    namespace = event.get("namespace", "prod")
    action = event.get("action", "get")
    result = ""

    # Action handler
    try:
        if action == "get":
            # Example: get all resources in the specified namespace
            result = run_kubectl(kubeconfig_path, ["get", "all", "-n", namespace])

        elif action == "restart":
            # Requires 'deployment' key in event
            deployment = event["deployment"]
            result = run_kubectl(
                kubeconfig_path,
                ["rollout", "restart", f"deployment/{deployment}", "-n", namespace]
            )

        elif action == "apply":
            # Requires 'yaml' key (string content) in event
            yaml_text = event["yaml"]
            yaml_path = "/tmp/tmp_apply.yaml"
            with open(yaml_path, "w") as f:
                f.write(yaml_text)
            result = run_kubectl(kubeconfig_path, ["apply", "-f", yaml_path])

        else:
            result = f"Unknown action: {action}"
            return {
                "statusCode": 400,
                "message": result,
                "namespace": namespace,
                "action": action,
            }

    except Exception as e:
        # Catch any errors during kubectl execution
        return {
            "statusCode": 500,
            "message": f"kubectl execution failed for action '{action}'.",
            "error": str(e)
        }

    # Successful response
    return {
        "statusCode": 200,
        "message": "kubectl executed successfully",
        "namespace": namespace,
        "action": action,
        "output": result
    }