import json
from ratelimit import limits, sleep_and_retry
from locust.log import setup_logging
from locust.env import Environment
from locust.runners import STATE_SPAWNING, STATE_RUNNING, STATE_CLEANUP
from locust import HttpUser, between, task, User
from kubernetes import client, config
import requests
import numpy as np
import csv
import datetime
from dateutil.tz import tzutc
import os
import time
from statistics import mean
from typing import Tuple, Type
import logging
import gevent
import gevent.monkey
gevent.monkey.patch_all()

dir_path = os.path.dirname(os.path.realpath(__file__))
csv_file_name = os.path.join(
    dir_path, f"{time.time()}.table.csv")

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

def get_power_of_attack(attack_type):
    if attack_type == 1:
        return 3
    return 10


# Probe packet
@sleep_and_retry
@limits(calls=1, period=1)
def send_probe(url: str) -> float:
    response = requests.get(url)
    if response.status_code != 200:
        response_time = 5
    else:
        response_time = response.elapsed.total_seconds()
    return response_time


setup_logging("INFO", None)


class RegularEnvironment(object):
    def __init__(self, user: Type[User], count: int, spawn_rate: int) -> None:
        # setup Environment and Runner
        self.env = Environment(user_classes=[user])
        self.env.create_local_runner()
        self.count = count
        self.spawn_rate = spawn_rate

        # start a greenlet that periodically outputs the current stats
        # gevent.spawn(stats_printer(self.env.stats))

        # start a greenlet that save current stats to history
        # gevent.spawn(stats_history, self.env.runner)

    def start(self):
        # start the test
        self.env.runner.start(self.count, spawn_rate=self.spawn_rate)

    def stop(self):
        self.env.runner.quit()
        self.env.runner.greenlet.join()


class YoYoAttacker(object):
    def __init__(self,
                 remote_ip: str,
                 auto_scale_api: client.AutoscalingV1Api,
                 cluster_api: client.CoreV1Api,
                 reg_env: RegularEnvironment,
                 attack_env: RegularEnvironment) -> None:
        self.probe_time_tuples = []
        self.probe_times_under_attack = []
        self.mean_attack_time = 0
        self.avg_attack_time = 0
        self.per90_attack_time = 0
        self.per95_attack_time = 0
        self.cpu_load = 0
        self.regular_load_process = None
        self.auto_scale_api = auto_scale_api
        self.cluster_api = cluster_api
        self.remote_ip = remote_ip
        self.reg_env = reg_env
        self.attack_env = attack_env
        self.start_time = datetime.datetime.now(tz=tzutc())
        self.query_hpa_api()

    def query_hpa_api(self) -> None:
        names = ['details-autoscaler', 'rating-autoscaler',
                 'reviews-autoscaler', 'product-autoscaler']
        namespace = 'default'
        logging.info('Updating cluster info')
        self.statuses = []
        for name in names:
            api_response = self.auto_scale_api.read_namespaced_horizontal_pod_autoscaler(name, namespace,
                                                                                         pretty=True)
            self.statuses.append(api_response.status)
        nodes_count = len(list(self.cluster_api.list_node().items))
        active_pods_count = len(
            [pod for pod in self.cluster_api.list_pod_for_all_namespaces(label_selector='app in (rating,product,details,reviews)').items
             if pod.status.phase == 'Running'])

        self.nodes_count = nodes_count
        self.active_pods_count = active_pods_count

    def start(self) -> None:
        with open(csv_file_name, 'w') as f:
            w = csv.writer(f, delimiter=',')
            w.writerow(HEADERS)
            self.loop(w)

    def loop(self, w) -> None:
        # Probe test
        for index in range(1000000):
            response_time = self.inner_loop(index)
            self.write_stats(index, response_time, w)

    @property
    def is_attacking(self) -> bool:
        return self.attack_env.env.runner.state in [ STATE_SPAWNING, STATE_RUNNING, STATE_CLEANUP]

    def finish_attack(self):
        self.attack_env.stop()
        # Resting avg
        self.avg_attack_time = 0
        self.mean_attack_time = 0
        self.per95_attack_time = 0
        self.per90_attack_time = 0
        self.probe_times_under_attack = []

    def inner_loop(self, index: int) -> float:
        response_time = get_response_time(self.remote_ip)
        # Checking
        if self.is_attacking:
            # Handle attack testing on cool down
            logging.info('We Are under attack - checking!')
            # calc avg time
            self.probe_times_under_attack.append(response_time)
            self.sample_count = len(self.probe_times_under_attack)
            self.mean_attack_time = mean(self.probe_times_under_attack)
            self.avg_attack_time = sum(
                self.probe_times_under_attack) / self.sample_count
            self.per95_attack_time = np.percentile(
                np.array(self.probe_times_under_attack), 95)
            self.per90_attack_time = np.percentile(
                np.array(self.probe_times_under_attack), 90)
            self.cpu_load = sum(
                status.current_cpu_utilization_percentage for status in self.statuses) / 4
            if (self.cpu_load <= 56 and self.active_pods_count > 10):
                self.finish_attack()
        else:
            if self.active_pods_count == 4 and index > 3: # and index > 49:
                logging.info('init attack')
                self.attack_env.start()

        self.query_hpa_api()

        # Get avarage time of the last x res and see if attack
        self.probe_time_tuples.append(response_time)
        return response_time

    def get_last_scale_time(self) -> datetime.datetime:
        latest_scale_time = self.start_time
        for scale_time in (status.last_scale_time for status in self.statuses):
            if scale_time is not None and scale_time >latest_scale_time:
                latest_scale_time = scale_time
        return latest_scale_time
    
    def get_number_of_current_replicas(self):
        return sum(status.current_replicas for status in self.statuses)

    def get_desired_replica_count(self):
        return sum(status.desired_replicas for status in self.statuses)

    def get_average_cpu_load(self):
        return sum(status.current_cpu_utilization_percentage for status in self.statuses) / 4

    def write_stats(self, index: int, response_time: float, w):
        stats = [
            index,  # time
            # probe response time - flatten weird results
            min(round(response_time, 1), 5),
            # Attack
            self.avg_attack_time,
            self.mean_attack_time,
            self.per95_attack_time,
            self.per90_attack_time,
            # probe
            # total avg res time
            (sum(self.probe_time_tuples) / len(self.probe_time_tuples)),
            mean(self.probe_time_tuples),  # total mea res time
            np.percentile(np.array(self.probe_time_tuples), 90),
            np.percentile(np.array(self.probe_time_tuples), 95),
            # HPA INFO
            # current_pods_count
            self.get_number_of_current_replicas(),
            self.active_pods_count,
            # desire_pod_count
            self.get_desired_replica_count(),
            # cpu_load,  # Normalize
            self.get_average_cpu_load(),
            self.nodes_count,
            (10),
            # is
            int(self.is_attacking),  # Nonmalize
            self.get_last_scale_time()
        ]

        w.writerow(stats)

        logging.info(dict(zip(HEADERS, stats)))

    def stop(self):
        self.attack_env.stop()
        self.reg_env.stop()


def get_response_time(endpoint: str) -> float:
    url = f'http://{endpoint}/health'
    try:
        logging.info('sending probe')
        response_time = send_probe(url)
        logging.info('revived probe')
    except Exception as e:
        logging.info('retry - sending probe - {}'.format(e))
        response_time = send_probe(url)
        logging.info('retry - revived probe')
    return response_time


def authenticate() -> Tuple[client.AutoscalingV1Api, client.CoreV1Api]:
    config.load_kube_config()
    auto_scale_api = client.AutoscalingV1Api()
    cluster_api = client.CoreV1Api()
    return auto_scale_api, cluster_api


auto_scale_api, cluster_api = authenticate()


def get_remote_ip() -> str:
    services = cluster_api.list_service_for_all_namespaces()
    for service in services.items:
        if service.metadata.name == 'product':
            remote_ip = service.status.load_balancer.ingress[0].ip
            remote_port = service.spec.ports[0].port
            target = f'{remote_ip}:{remote_port}'
            logging.info(f'Found remote IP at {remote_ip}:{remote_port}')
            return target
    raise RuntimeError("Failed to find remote IP")


remote_ip = get_remote_ip()
logging.info(get_response_time(remote_ip))


class RegularUser(HttpUser):
    wait_time = between(1, 3)
    host = f"http://{remote_ip}"

    @task
    def my_task(self):
        self.client.get("/health")


class AttackUser(HttpUser):
    host = f"http://{remote_ip}"
    wait_time = between(1, 3)
    @task
    def my_task(self):
        a = json.loads('''{
            "memory_params": {
                "duration_seconds": 0.2,
                "kb_count": 50
            },
            "cpu_params": {
                "duration_seconds": 0.2,
                "load": 0.2
            }
            }''')
        self.client.post("/load", json=a)

        # self.client.get("/health")
reg_env = RegularEnvironment(RegularUser, 1, 10)
attack_env = RegularEnvironment(AttackUser, 6, 1)

y = YoYoAttacker(remote_ip, auto_scale_api, cluster_api, reg_env, attack_env)
y.start()