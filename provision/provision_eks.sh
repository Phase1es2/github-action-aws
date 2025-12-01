#!/bin/bash
set -e

# -------------------------
# Configurable variables
# -------------------------
CLUSTER_NAME="django-cluster"
REGION="us-east-1"
NODE_GROUP_NAME="standard-workers"
NODE_TYPE="t3.medium"
NODE_COUNT=2

echo "=============================="
echo "Creating EKS Cluster"
echo "Cluster Name: $CLUSTER_NAME"
echo "Region: $REGION"
echo "Node Group: $NODE_GROUP_NAME"
echo "Node Type: $NODE_TYPE"
echo "Nodes: $NODE_COUNT"
echo "=============================="

# -------------------------
# Check eksctl installed
# -------------------------
if ! command -v eksctl &> /dev/null
then
    echo "ERROR: eksctl not found. Install with:"
    echo "curl -s https://api.github.com/repos/weaveworks/eksctl/releases/latest \\
        | grep browser_download_url \\
        | grep $(uname)_amd64 \\
        | cut -d '\"' -f 4 \\
        | xargs curl -L -o eksctl"
    exit 1
fi

# -------------------------
# Check AWS identity
# -------------------------
echo "Checking AWS identity..."
aws sts get-caller-identity || {
    echo "ERROR: AWS credentials not configured!"
    exit 1
}

# -------------------------
# Create EKS Cluster
# -------------------------
echo "Creating EKS cluster... This may take ~15–25 minutes."

eksctl create cluster \
  --name "$CLUSTER_NAME" \
  --region "$REGION" \
  --nodegroup-name "$NODE_GROUP_NAME" \
  --node-type "$NODE_TYPE" \
  --nodes "$NODE_COUNT" \
  --managed

echo "==================================="
echo "EKS Cluster created successfully!"
echo "Run this to verify:"
echo "kubectl get nodes"
echo "==================================="