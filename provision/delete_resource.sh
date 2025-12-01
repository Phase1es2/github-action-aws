kubectl delete -f deployment-prod.yaml                                                          
kubectl delete -f service-prod.yaml

kubectl delete namespace pr
eksctl delete cluster --name django-cluster --region us-east-1