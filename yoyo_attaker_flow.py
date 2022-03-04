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
from typing import List, Tuple, Type, Union
import logging
import gevent
import gevent.monkey
gevent.monkey.patch_all()

dir_path = os.path.dirname(os.path.realpath(__file__))
csv_file_name = os.path.join(
    dir_path, f"{time.time()}.table.csv")

TARGET_SERVICES = ['details', 'rating', 'reviews', 'product']
HEADERS = [
    'time',
    'response_time',
    'active_pods_count',
    'cpu_load',
    'current_power_of_attack'
]


def send_probe(url: str) -> float:
    try:
        response = requests.get(url, timeout=10)
        if response.status_code != 200:
            return 10
        return response.elapsed.total_seconds()
    except requests.ReadTimeout:
        return 10


class RegularEnvironment(object):
    def __init__(self, user: Type[User], count: int, spawn_rate: int) -> None:
        # setup Environment and Runner
        self.env = Environment(user_classes=[user])
        self.env.create_local_runner()
        self.count = count
        self.spawn_rate = spawn_rate

    def start(self):
        # start the test
        self.env.runner.start(self.count, spawn_rate=self.spawn_rate)

    def stop(self):
        self.env.runner.quit()
        self.env.runner.greenlet.join()


class YoYoAttacker(object):
    def __init__(self, services: List[str]) -> None:
        self.authenticate()
        self.remote_ip = self.get_remote_ip()
        self.create_envs()
        self.services = services
        self.start_time = datetime.datetime.now(tz=tzutc())
        self.query_hpa_api()
        self.response_time = self.get_response_time()
        self.last_attack_time = None

    def create_envs(self):
        class AttackUser(HttpUser):
            host = f"http://{self.remote_ip}"
            wait_time = between(1, 3)

            @task
            def my_task(self):
                a = {
                    "memory_params": {"duration_seconds": 0.2, "kb_count": 50},
                    "cpu_params": {"duration_seconds": 0.2, "load": 0.2}
                }
                self.client.post("/load", json=a)

        self.reg_env = RegularEnvironment(AttackUser, 2, 10)
        self.attack_env = RegularEnvironment(AttackUser, 12, 1)

    def authenticate(self):
        config.load_kube_config()
        self.auto_scale_api = client.AutoscalingV1Api()
        self.cluster_api = client.CoreV1Api()

    def get_remote_ip(self) -> str:
        services = self.cluster_api.list_service_for_all_namespaces()
        for service in services.items:
            if service.metadata.name == 'product':
                ingress = service.status.load_balancer.ingress
                if not ingress:
                    continue
                remote_ip = ingress[0].ip
                remote_port = service.spec.ports[0].port
                target = f'{remote_ip}:{remote_port}'
                logging.info(f'Found remote IP at {remote_ip}:{remote_port}')
                return target
        raise RuntimeError("Failed to find remote IP")

    def response_time_loop(self) -> None:
        self.response_time = self.get_response_time()

    def get_statuses(self) -> None:
        namespace = 'default'
        self.statuses = []
        for name in self.services:
            api_response = self.auto_scale_api.read_namespaced_horizontal_pod_autoscaler(name, namespace,
                                                                                         pretty=True)
            self.statuses.append(api_response.status)

    def wait_for_start(self):
        while any(status.current_cpu_utilization_percentage is None for status in self.statuses):
            time.sleep(1)
            logging.info('Waiting for CPU metrics to initialize')
            self.get_statuses()

    def query_hpa_api(self) -> None:
        self.get_statuses()

    def get_nodes_count(self):
        nodes_count = len(list(self.cluster_api.list_node().items))
        return nodes_count

    def get_active_pods_count(self) -> int:
        label_selector = f'app in ({",".join(self.services)})'
        all_pods = self.cluster_api.list_pod_for_all_namespaces(
            label_selector=label_selector).items
        return len([pod for pod in all_pods if pod.status.phase == 'Running'])

    def start(self) -> None:
        self.wait_for_start()
        with open(csv_file_name, 'w') as f:
            w = csv.writer(f, delimiter=',')
            w.writerow(HEADERS)
            self.loop(w)

    def loop(self, w) -> None:
        # Probe test
        for index in range(1000000):
            self.inner_loop(index)
            self.response_time_loop()
            self.write_stats(w)

    @property
    def is_attacking(self) -> bool:
        return self.attack_env.env.runner.state in [STATE_SPAWNING, STATE_RUNNING, STATE_CLEANUP]

    def finish_attack(self) -> None:
        self.attack_env.stop()

    def service_count(self) -> int:
        return len(self.services)

    def inner_loop(self, index: int) -> float:
        response_time = self.get_response_time()
        try:
            self.query_hpa_api()
            active_pods_count = self.get_active_pods_count()
        except client.exceptions.ApiException:
            self.authenticate()
            self.query_hpa_api()
            active_pods_count = self.get_active_pods_count()
        # Checking
        if self.is_attacking:
            # Handle attack testing on cool down
            if (self.get_max_cpu_load() <= 60 and active_pods_count > 10) and self.seconds_since_last_attack() > 30:
                self.finish_attack()
                self.last_attack_time = datetime.datetime.now()
        else:
            if active_pods_count == self.service_count() and index > 10:  # and index > 49:
                self.attack_env.start()
                self.last_attack_time = datetime.datetime.now()
            if self.seconds_since_last_attack() > 200:
                self.attack_env.start()
                self.last_attack_time = datetime.datetime.now()

        return response_time

    def seconds_since_last_attack(self):
        if not self.last_attack_time:
            return 0
        return (datetime.datetime.now() - self.last_attack_time).seconds

    def get_last_scale_time(self) -> datetime.datetime:
        latest_scale_time = self.start_time
        for scale_time in (status.last_scale_time for status in self.statuses):
            if scale_time is not None and scale_time > latest_scale_time:
                latest_scale_time = scale_time
        return latest_scale_time

    def get_current_replicas(self) -> List[int]:
        return [status.current_replicas for status in self.statuses]

    def get_max_cpu_load(self) -> float:
        return max(self.get_cpu_loads())

    def get_cpu_loads(self) -> List[float]:
        return [status.current_cpu_utilization_percentage for status in self.statuses]

    def get_stats(self) -> List[Union[int, float, str]]:
        stats = [
            datetime.datetime.now(),  # time
            # probe response time - flatten weird results
            min(round(self.response_time, 1), 5),
            ' '.join(map(str, self.get_current_replicas())),
            ' '.join(map(str, self.get_cpu_loads())),
            self.reg_env.count + \
            (self.attack_env.count if self.is_attacking else 0)
        ]
        return stats

    def write_stats(self, w) -> None:
        stats = self.get_stats()
        w.writerow(stats)

        logging.info(dict(zip(HEADERS, stats)))

    def stop(self) -> None:
        self.attack_env.stop()
        self.reg_env.stop()

    def get_response_time(self) -> float:
        url = f'http://{self.remote_ip}/health'
        try:
            response_time = send_probe(url)
        except Exception as e:
            response_time = send_probe(url)
        return response_time


if __name__ == '__main__':
    setup_logging("INFO", None)

    y = YoYoAttacker(TARGET_SERVICES)
    y.start()
