#!/bin/bash

# Ensure the script exits immediately if any command fails
set -e

# --- Variable Definition (Must match the creation script) ---
CLUSTER_NAME="django-cluster"
REGION="us-east-1"
NAMESPACE_PROD="prod"
NAMESPACE_QA="qa"

echo "--- Starting EKS Resource Cleanup ---"
echo ""

# --- 1. Clean up Kubernetes Resources (Optional but Recommended) ---
# Although deleting the cluster removes the namespaces, explicitly deleting
# Kubernetes objects first can help if you had external dependency issues.
echo "--- Deleting Kubernetes Namespaces and all contained resources ---"

# Deleting the namespace automatically deletes all resources (Deployments, Services, Pods) within it.
kubectl delete namespace "$NAMESPACE_PROD" --ignore-not-found
echo "Namespace ${NAMESPACE_PROD} deletion initiated."

kubectl delete namespace "$NAMESPACE_QA" --ignore-not-found
echo "Namespace ${NAMESPACE_QA} deletion initiated."

echo "---"

# --- 2. Delete the EKS Cluster (The Main Cleanup Step) ---
echo "--- Deleting EKS Cluster: ${CLUSTER_NAME} (Region: ${REGION}) ---"
echo "This step is asynchronous and may take 10-20 minutes."

# Use eksctl to delete the cluster. This removes the control plane,
# worker node groups, associated IAM roles, and VPC resources created by eksctl.
eksctl delete cluster \
  --name "$CLUSTER_NAME" \
  --region "$REGION" \
  --wait # Wait for the deletion to complete

echo "EKS cluster ${CLUSTER_NAME} and all associated cloud resources have been successfully deleted."
echo "---"

echo "Cleanup Complete!"