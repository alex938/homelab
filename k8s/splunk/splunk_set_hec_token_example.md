kubectl create secret generic splunk-kubernetes-objects -n splunk \
  --from-literal=splunk_hec_token='token_here'

kubectl create secret generic splunk-kubernetes-logging -n splunk \
  --from-literal=splunk_hec_token='token_here'

kubectl create secret generic splunk-kubernetes-metrics -n splunk \
  --from-literal=splunk_hec_token='token_here'