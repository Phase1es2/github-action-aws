import boto3
import base64
import subprocess
import os
import json

# --- Configuration ---
CLUSTER_NAME = "django-cluster"
REGION = "us-east-1"
# APPLY_FILES is deprecated in the new logic, but kept here for context
APPLY_FILES = ["deployment-prod.yaml", "service-prod.yaml"] 
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
    sts = boto3.client("sts")
    identity = sts.get_caller_identity()
    print("STS Identity:", identity)
    # ------------------------------------------------------------------
    # >> Fix #1: Define image_tag variable (fetch from event) <<
    # ------------------------------------------------------------------
    image = event.get("image", "latest") 
    print("Image Tag for deployment:", image)


    try:
        kubeconfig_path = write_ca_and_kubeconfig()
    except Exception as e:
        return {
            "statusCode": 500,
            "message": "Failed to generate kubeconfig.",
            "error": str(e)
        }

    namespace = event.get("namespace", "prod").lower()
    action = event.get("action", "get")
    
    # ------------------------------------------------------------------
    # >> Fix #2 & #3: Initialize result and all_results list <<
    # ------------------------------------------------------------------
    result = ""
    # all_results is mainly for the 'apply' action, but initialized here for correct scope
    all_results = [] 

    try:
        # ------------------------------
        # RESTART
        # ------------------------------
        if action == "restart":
            deployment = event["deployment"]
            result = run_kubectl(
                kubeconfig_path,
                ["rollout", "restart", f"deployment/{deployment}", "-n", namespace]
            )
            all_results.append(result) # Record the result

        # ------------------------------
        # APPLY YAML (Fixed scope issues, dynamic file selection)
        # ------------------------------
        elif action == "apply":
            
            # Dynamically determine the files based on the namespace
            files_to_deploy = [
                f"deployment-{namespace}.yaml",
                f"service-{namespace}.yaml"
            ]
            
            # Iterate and process each YAML file
            for file_name in files_to_deploy:
                # 1. Construct the full path to the read-only file (/var/task/)
                # os.path.dirname(__file__) points to /var/task/
                yaml_base_path = os.path.join(os.path.dirname(__file__), file_name)
                
                # 2. Read the raw YAML content
                print(f"Processing local YAML file: {file_name}")
                with open(yaml_base_path, 'r') as f:
                    yaml_text = f.read()
                
                # 3. Replace the image tag (only execute for files containing the placeholder)
                if "__IMAGE_TAG__" in yaml_text:
                    # Use the defined image variable
                    yaml_text = yaml_text.replace("__IMAGE_TAG__", image)
                    print(f"Replaced __IMAGE_TAG__ with: {image} in {file_name}")
                
                
                # 4. Write the final content to the writable /tmp directory
                yaml_tmp_path = f"/tmp/{file_name}" # Ensure a unique temporary filename
                with open(yaml_tmp_path, "w") as f:
                    f.write(yaml_text)
                    
                # 5. Execute kubectl apply
                result = run_kubectl(kubeconfig_path, ["apply", "-f", yaml_tmp_path])
                all_results.append(result)

        # ------------------------------
        # SET_IMAGE 
        # ------------------------------
        elif action == "set_image":
            deployment = event["deployment"]
            container = event["container"]
            new_image = event["image"]

            # Update deployment image
            result = run_kubectl(
                kubeconfig_path,
                [
                    "set", "image",
                    f"deployment/{deployment}",
                    f"{container}={new_image}",
                    "-n", namespace
                ]
            )

            rollout_status = run_kubectl(
                kubeconfig_path,
                [
                    "rollout", "status",
                    f"deployment/{deployment}",
                    "-n", namespace,
                    "--timeout=60s"
                ]
            )

            # Immediate return on success (for SET_IMAGE)
            return {
                "statusCode": 200,
                "message": "Image updated successfully",
                "namespace": namespace,
                "deployment": deployment,
                "image": new_image,
                "output": result,
                "rollout_status": rollout_status
            }

        # ------------------------------
        # UNKNOWN ACTION
        # ------------------------------
        else:
            return {
                "statusCode": 400,
                "message": f"Unknown action: {action}"
            }

    except Exception as e:
        return {
            "statusCode": 500,
            "message": f"kubectl execution failed for action '{action}'.",
            "error": str(e)
        }

    # Unified return of success results; for APPLY action, return the joined string of all results
    if action == "apply":
        final_output = "\n---\n".join(all_results)
    else:
        # For GET/RESTART, return the last 'result' string
        final_output = result

    return {
        "statusCode": 200,
        "message": f"kubectl executed successfully for action '{action}'",
        "namespace": namespace,
        "action": action,
        "output": final_output
    }