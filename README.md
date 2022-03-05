This project contains the code for the final project in the course "Advanced Topics in IP networks" with Anat Bremler-Barr.
Ths project implements a YoYo DDos attack on multi service applications in different topologies running on GCP as described here.
Based of Dani Bachar's attack on a single kubernetes service here: https://github.com/danibachar/Kubernetes
# Installation

## install prerequsites (ubuntu)
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
sudo apt-get install -y python3-pip
```
## install prerequsites (Windows)
```bash
# Download from https://cloud.google.com/sdk/docs/install
gcloud components install kubectl
```
## Python
```sh
pip3 install -r requirements.txt
```
## Create GCloud environment 
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
Now you can run the chosen topology:
```sh
kubectl apply -f .\app\Topology2\
```
## now you should be able to run the script
Note that you may need to wait for the remote IP to initialize
```sh
python3 yoyo_attaker_flow.py
```
## Delete services after testing
```sh
kubectl delete -f .\app\Topology2\
```