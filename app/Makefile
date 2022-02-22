
##############################################
#
#
#
#               >>>>>>>
#             /         
#            /
########### /  
# Product # 
########### \ 
#         
#
#
#
#
##############################################
cleanup: delete-bookinfo

build:
	docker build -f Dockerfile -t danibachar/tester:latest .
	docker push danibachar/tester:latest

deploy-bookinfo:
	kubectl apply -f bookinfo/

delete-bookinfo:
	kubectl delete -f bookinfo/