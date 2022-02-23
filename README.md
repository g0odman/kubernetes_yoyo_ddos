# Installation

## 1) GCP Attcker Machine config (TODO - dockerise)
    ### a) Allow full access for gcp api for the machine ( you know that tick you need to set when the machine is off...)
    ### b) Make sure `gcloud` is configured, on gcp machines it should come built-in.
    ### c) On local machine install gcloud and run gcloud auth login - login using you gcp account

## 2) install prerequsitis (ubuntu)
```sh
# update
sudo apt-get update
# CURL
sudo apt-get install -y curl
# Kubernetes - https://kubernetes.io/docs/tasks/tools/install-kubectl/#install-kubectl-on-linux
sudo apt-get update && sudo apt-get install -y apt-transport-https
curl -s https://packages.cloud.google.com/apt/doc/apt-key.gpg | sudo apt-key add -
echo "deb https://apt.kubernetes.io/ kubernetes-xenial main" | sudo tee -a /etc/apt/sources.list.d/kubernetes.list
sudo apt-get update
sudo apt-get install -y kubectl
```
## install windows
```bash
https://cloud.google.com/sdk/docs/install
gcloud components install kubectl
```
## Python
sudo apt-get install -y python3-pip
cd attacks
pip3 install -r requirements.txt
## 4) Run - 
```sh
gcloud container clusters get-credentials microsvc-us --zone=us-central1-a
# Make sure we got the api token by running - cat ~/.kube/config
cat ~/.kube/config
```
You should see some certificate or a Bearer token similar to this
```
 context:
    cluster: gke_independent-bay-250811_us-central1-a_microsvc-us
    user: gke_independent-bay-250811_us-central1-a_microsvc-us
  name: gke_independent-bay-250811_us-central1-a_microsvc-us
current-context: gke_independent-bay-250811_us-central1-a_microsvc-us
```

## Remember to update the jmeter test cases with the new external ip address
## 7) now you should be able to run the script
``` Run the test
python3 yoyo_attaker_flow.py
optional live feed - python3 yoyo_attaker_flow.py &> live_feed.txt
```