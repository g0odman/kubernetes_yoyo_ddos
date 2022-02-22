import csv
import datetime
import errno
import os
import subprocess
from statistics import mean
from typing import Type

import gevent
import gevent.monkey
gevent.monkey.patch_all()
import numpy as np
import requests
from kubernetes import client, config
from locust import HttpUser, between, task, User
from locust.env import Environment
from locust.log import setup_logging
from locust.stats import stats_history, stats_printer
from ratelimit import limits, sleep_and_retry
import json
import requests

dir_path = os.path.dirname(os.path.realpath(__file__))
csv_file_name = str(dir_path) + "/{}.table.csv".format(str(datetime.datetime.now()))

HEADERS = [
        'time',
        'current response time',
        # Under attack
        'avg response time under attack',
        'mean response time under attack',
        '95th percentile under attack response time',
        '90th percentile under attack response time',
        # Total
        'probe packet avg response time',
        'probe packet mean response time',
        'probe packet 95th percentile response time',
        'probe packet 90th percentile response time',
        # HPA info
        'current_pods_count',
        'active_pods_count',
        'desire_pod_count',
        'cpu_load',
        'node_count',
        'current_power_off_attack',
        #
        'is running attach'

    ]
# Helper Functions
def safe_open(file_name_with_dierctory: str, permision="wb+"):
    if not os.path.exists(os.path.dirname(file_name_with_dierctory)):
        try:
            os.makedirs(os.path.dirname(file_name_with_dierctory))
        except OSError as exc:  # Guard against race condition
            if exc.errno != errno.EEXIST:
                raise

    return open(file_name_with_dierctory, permision)

def get_power_of_attack(attack_type):
    if attack_type == 1:
        return 3
    return 10

# GLOBALS
'''
    The Endpoint to attack!
'''
HOST = "http://35.188.13.155"
END_POINT = '{}:31001/service/1000'.format(HOST)
'''
    1 - Experiment 1, where we attack without trigger the Cluster Autoscaling
    2 - Experiment 2 - Naive
    3 - Experiment 2 - Sophisticated
'''
ATTACK_TYPE = 3


# Probe packet
@sleep_and_retry
@limits(calls=1, period=1)
def send_probe(url):
    response = requests.get(url)
    if response.status_code != 200:
        response_time = 5
    else:
        response_time = response.elapsed.total_seconds()
    return response_time


setup_logging("INFO", None)


class RegularUser(HttpUser):
    wait_time = between(1, 3)
    host = "http://35.238.213.208"

    @task
    def my_task(self):
        self.client.get("/health")

class AttackUser(HttpUser):
    wait_time = between(1, 3)
    host = "http://35.238.213.208"
    @task
    def my_task(self):
            a = json.loads('''{
            "memory_params": {
                "duration_seconds": 1,
                "kb_count": 50000
            },
            "cpu_params": {
                "duration_seconds": 1,
                "load": 1
            }
            }''')
            # self.client.post("/load", json=a)
            self.client.get("/health")


class RegularEnvironment(object):
    def __init__(self, user : Type[User], count : int, spawn_rate : int) -> None:
        # setup Environment and Runner
        self.env = Environment(user_classes=[user])
        self.env.create_local_runner()
        self.count = count
        self.spawn_rate = spawn_rate

        # start a greenlet that periodically outputs the current stats
        gevent.spawn(stats_printer(self.env.stats))

        # start a greenlet that save current stats to history
        gevent.spawn(stats_history, self.env.runner)

    def start(self):
        # start the test
        self.env.runner.start(self.count, spawn_rate=self.spawn_rate)

    def stop(self):
        self.env.runner.quit()
        self.env.runner.greenlet.join()

def test():
    reg_env = RegularEnvironment(RegularUser, 1, 10)
    attack_env = RegularEnvironment(AttackUser, 100, 10)
    attack_env.start()
    reg_env.start()
    import time
    time.sleep(10)
    attack_env.stop()
    reg_env.stop()

class YoYoAttacker(object):
    def __init__(self) -> None:
        print('a')
        self.probe_time_tuples = []
        self.probe_times_under_attack = []
        self.attack_process = None
        self.mean_attack_time = 0
        self.avg_attack_time = 0
        self.per90_attack_time = 0
        self.per95_attack_time = 0
        self.cpu_load = 0
        self.regular_load_process = None
        self.authenticate()
        print('b')
        self.query_hpa_api()    
        print('c')

    def authenticate(self) -> None:
        config.load_kube_config()
        self.auto_scale_api = client.AutoscalingV1Api()
        self.cluster_api = client.CoreV1Api()

    def query_hpa_api(self):
        names = ['details-autoscaler', 'rating-autoscaler', 'reviews-autoscaler', 'product-autoscaler']
        namespace = 'default'
        print('Updating cluster info')
        self.statuses = []
        for name in names:
            api_response = self.auto_scale_api.read_namespaced_horizontal_pod_autoscaler(name, namespace,
                                                                                                        pretty=True)
            self.statuses.append(api_response.status)
        nodes_count = len(list(self.cluster_api.list_node().items))
        active_pods_count = len(
                        [pod for pod in self.cluster_api.list_pod_for_all_namespaces(label_selector='app=hpa-example').items
                        if pod.status.phase == 'Running'])

        self.nodes_count = nodes_count
        self.active_pods_count = active_pods_count
        print('Done Updating cluster info\nactive: {}'.format(active_pods_count))
    
    def start(self):        
        with safe_open(csv_file_name, 'w') as f:
            w = csv.writer(f, delimiter=',')
            w.writerow(HEADERS)
            self.loop(w)

    def loop(self, w):
        # Probe test
        for index in range(1000000):
            response_time = self.inner_loop(index)
            self.write_stats(index, response_time, w)

    
    @property
    def is_attacking(self):
        return self.attack_process is not None

    def finish_attack(self):
        kill_process(self.attack_process)
        self.attack_process = None
        # Resting avg
        self.avg_attack_time = 0
        self.mean_attack_time = 0
        self.per95_attack_time = 0
        self.per90_attack_time = 0
        self.probe_times_under_attack = []

    def inner_loop(self, index):        
        response_time = get_response_time()
        # Checking
        if self.is_attacking:
            # Handle attack testing on cool down
            print('We Are under attack - checking!')
            # calc avg time
            self.probe_times_under_attack.append(response_time)
            self.sample_count = len(self.probe_times_under_attack)
            self.mean_attack_time = mean(self.probe_times_under_attack)
            self.avg_attack_time = sum(self.probe_times_under_attack) / self.sample_count
            self.per95_attack_time = np.percentile(np.array(self.probe_times_under_attack), 95)
            self.per90_attack_time = np.percentile(np.array(self.probe_times_under_attack), 90)
            self.cpu_load = sum(status.current_cpu_utilization_percentage for status in self.statuses) / 4
            if (index > 120 and self.cpu_load <= 56 and self.nodes_count > 2):
                self.finish_attack()
        else:
            if self.nodes_count == 3 and index > 49:
                print('init first attack')
                attack_process = start_on_attack_phase()

        if index % 9 == 0:
            self.query_hpa_api()

        # Get avarage time of the last x res and see if attack
        self.probe_time_tuples.append(response_time)
        return response_time

    def write_stats(self, index, response_time, w):
        stats = [
            index,  # time
            min(round(response_time, 1), 5),  # probe response time - flatten weird results
            # Attack
            self.avg_attack_time,
            self.mean_attack_time,
            self.per95_attack_time,
            self.per90_attack_time,
            # probe
            (sum(self.probe_time_tuples) / len(self.probe_time_tuples)),  # total avg res time
            mean(self.probe_time_tuples),  # total mea res time
            np.percentile(np.array(self.probe_time_tuples), 90),
            np.percentile(np.array(self.probe_time_tuples), 95),
            # HPA INFO
            sum(status.current_replicas for status in self.statuses), # current_pods_count
            self.active_pods_count,
            sum(status.desired_replicas for status in self.statuses), # desire_pod_count
            sum(status.current_cpu_utilization_percentage for status in self.statuses), # cpu_load,  # Normalize
            self.nodes_count,
            (10),
            # is
            int(self.is_attacking),  # Nonmalize
            max(status.last_scale_time for status in self.statuses)
        ]

        w.writerow(stats)

        print(dict(zip(HEADERS, stats)))


    def stop(self):
        if self.regular_load_process is not None:
            kill_process(self.regular_load_process)
        if self.attack_process is not None:
            kill_process(self.attack_process)

def kill_process(attack_process):
    try:
        print("killing attack process")
        attack_process.kill()
        attack_process = None
    except Exception as e:
        print("kill attack fail - {}".format(e))


def get_response_time():
    try:
        print('sending probe')
        response_time = send_probe(END_POINT)
        print('revived probe')
    except Exception as e:
        print('retry - sending probe - {}'.format(e))
        response_time = send_probe(END_POINT)
        print('retry - revived probe')
    return response_time


y = YoYoAttacker()