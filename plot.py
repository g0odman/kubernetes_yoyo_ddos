import sys
import os
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib
from matplotlib.ticker import (AutoMinorLocator, MultipleLocator)
import numpy as np
from datetime import datetime

from dateutil import parser
from psutil import cpu_count
from sklearn import cluster
matplotlib.rcParams['agg.path.chunksize'] = 10000

HEADERS = [
    'time',
    'response_time',
    'current_power_of_attack',
    'active_pods_count',
    'cpu_load'
]
TARGET_SERVICES = ['details', 'rating', 'reviews', 'product', 'prices']

times_key, response_times_key, power_key, pods_key, cpu_key = HEADERS

# Data for plotting
df = pd.read_csv(os.path.join(os.path.dirname(__file__), sys.argv[1]))


def transpose_list(l):
    return list(map(list, zip(*l)))


def plt_combine():
    colors = ["b", "r", "g", "c", "m"]
    times = list(map(parser.parse, df[times_key]))
    response_times = df[response_times_key]
    power = df[power_key]
    pods = transpose_list(map(lambda x: map(int, str.split(x)), df[pods_key]))
    cpus = transpose_list(map(lambda x: map(int, str.split(x)), df[cpu_key]))

    fig, ax = plt.subplots(nrows=3, sharex=True)
    cluster_plot = ax[2]
    cpu_count = ax[1]
    pod_count = ax[0]
    # Original Plotting
    plt.yscale('linear')
    cluster_plot.plot(times, response_times, "b-", label='Response times', linewidth=1)
    cluster_plot.plot(times, power, "r-", label='Attack Power', linewidth=1)
    cluster_plot.fill_between(times, power, step="pre", alpha=0.4)
    for index, pod in enumerate(pods):
        pod_count.plot(times, pod, colors[index], label=TARGET_SERVICES[index], linewidth=1)
    for index, cpu in enumerate(cpus):
        cpu_count.plot(times, cpu, colors[index], label=TARGET_SERVICES[index], linewidth=1)
    cpu_max = cpu_count.get_ylim()[1]
    locs = list(range(0, int(cpu_max + 1), int(cpu_max / 5)))
    cpu_count.set_yticks(locs)
    cluster_plot.set(
        ylim=0
    )
    pod_count.set(
        ylabel='Pod Count',
        ylim=0
    )
    cpu_count.set(
        xlabel='Time',
        ylabel='CPU Usage',
        ylim=0
    )
    for axe in ax:
        axe.legend()

plt_combine()
plt.gcf().autofmt_xdate()
plt.show()
