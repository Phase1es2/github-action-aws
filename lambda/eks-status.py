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
    The main Lambda handler function.
    Processes the action (get, status, describe) from the input event.
    """

    sts = boto3.client("sts")
    identity = sts.get_caller_identity()
    print("STS Identity:", identity)
    
    # Fetch image tag from event, default to 'latest'


    try:
        # Generate the temporary kubeconfig file
        kubeconfig_path = write_ca_and_kubeconfig()
    except Exception as e:
        # Return error response in API Gateway Proxy Integration format
        return {
            "statusCode": 500,
            "body": json.dumps({"message": "Failed to generate kubeconfig.", "error": str(e)})
        }

    # Get namespace and action from the event
    namespace = event.get("namespace", "prod")
    action = event.get("action", "get")
    
    result = "" 
    deployment = None

    try:
        # ------------------------------
        # GET action: kubectl get all -n <namespace>
        # ------------------------------
        if action == "get":
            result = run_kubectl(kubeconfig_path, ["get", "all", "-n", namespace])
        
        # ------------------------------
        # STATUS action: kubectl rollout status deployment/<name> -n <namespace>
        # ------------------------------
        elif action == "status":
            deployment = event.get("deployment")
            if not deployment:
                 return {
                    "statusCode": 400,
                    "body": json.dumps({"message": "Missing required parameter: 'deployment' for action 'status'."})
                }
            
            result = run_kubectl(
                kubeconfig_path,
                [
                    "rollout", "status",
                    f"deployment/{deployment}",
                    "-n", namespace,
                    "--timeout=120s" # Set a longer timeout 
                ]
            )
            
            # Return status result immediately in API Gateway format
            return {
                "statusCode": 200,
                "body": json.dumps({
                    "message": "Rollout status retrieved successfully",
                    "namespace": namespace,
                    "deployment": deployment,
                    "output": result
                })
            }
        # ------------------------------
        # DESCRIBE action: kubectl describe deployment <name> -n <namespace>
        # ------------------------------
        elif action == "describe":
            deployment = event.get("deployment")
            if not deployment:
                 return {
                    "statusCode": 400,
                    "body": json.dumps({"message": "Missing required parameter: 'deployment' for action 'describe'."})
                }
            
            # Execute kubectl describe deployment
            result = run_kubectl(
                kubeconfig_path,
                ["describe", "deployment", deployment, "-n", namespace]
            )
            # Continues to the unified return block
            
        # ------------------------------
        # UNKNOWN ACTION
        # ------------------------------
        else:
            return {
                "statusCode": 400,
                "body": json.dumps({"message": f"Unknown action: {action}"})
            }

    except Exception as e:
        # Unified error handling block
        error_context = f" for Deployment '{deployment}'" if deployment else ""
        return {
            "statusCode": 500,
            "body": json.dumps({
                "message": f"kubectl execution failed for action '{action}'{error_context}.",
                "error": str(e)
            })
        }

    # ------------------------------------------------------------------
    # >> Unified Success Return (Applicable for GET and DESCRIBE) <<
    # ------------------------------------------------------------------
    final_output = result

    # Return success response in API Gateway Proxy Integration format
    return {
        "statusCode": 200,
        "body": json.dumps({
            "message": f"kubectl executed successfully for action '{action}'",
            "namespace": namespace,
            "action": action,
            "deployment": deployment, # Only has value for 'describe'
            "output": final_output
        })
    }