#!/bin/bash

# Ensure the script exits immediately if any command fails
set -e

# --- Variable Definition (Modify as needed) ---
CLUSTER_NAME="django-cluster"
REGION="us-east-1"
NODEGROUP_NAME="standard-workers"
NODE_TYPE="t3.medium"
NODES="2"
NAMESPACE_PROD="prod"
NAMESPACE_QA="qa"

# --- 1. Create EKS Cluster ---
echo "--- Creating EKS Cluster: ${CLUSTER_NAME} (Region: ${REGION}) ---"

# Use eksctl to create the cluster
eksctl create cluster \
  --name "$CLUSTER_NAME" \
  --region "$REGION" \
  --nodegroup-name "$NODEGROUP_NAME" \
  --node-type "$NODE_TYPE" \
  --nodes "$NODES"

echo "✅ EKS cluster ${CLUSTER_NAME} has been successfully created or is in the process of being created."
echo "---"

# --- 2. Create Kubernetes Namespaces ---
echo "--- Creating Kubernetes Namespaces ---"

# Create the prod namespace
kubectl create namespace "$NAMESPACE_PROD" || echo "Namespace ${NAMESPACE_PROD} might already exist, skipping creation."
echo "✅ Namespace ${NAMESPACE_PROD} created/exists."

# Create the qa namespace
kubectl create namespace "$NAMESPACE_QA" || echo "Namespace ${NAMESPACE_QA} might already exist, skipping creation."
echo "✅ Namespace ${NAMESPACE_QA} created/exists."

echo "---"

# --- 3. Deploy Kubernetes Resources (Deployment & Service) ---
echo "--- Deploying Django Applications to EKS Cluster ---"

# Define the base path for your YAML files
YAML_DIR="./yaml"

# 3.1. Deploy Production Resources
echo "Deploying Production resources into namespace: ${NAMESPACE_PROD}"
kubectl apply -f "${YAML_DIR}/deployment-prod.yaml"
kubectl apply -f "${YAML_DIR}/service-prod.yaml"
echo "Production Deployment and Service complete."

# 3.2. Deploy QA Resources
echo "Deploying QA resources into namespace: ${NAMESPACE_QA}"
kubectl apply -f "${YAML_DIR}/deployment-qa.yaml"
kubectl apply -f "${YAML_DIR}/service-qa.yaml"
echo "QA Deployment and Service complete."

echo "---"

echo "All tasks complete!"
echo "You can now view your cluster nodes and namespaces using the following commands:"
echo "kubectl get nodes"
echo "kubectl get ns"
echo ""
echo "To check the deployments and external access points:"
echo "kubectl get deployment -n ${NAMESPACE_PROD}"
echo "kubectl get svc -n ${NAMESPACE_PROD}"
echo "kubectl get svc -n ${NAMESPACE_QA}"