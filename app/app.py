# -*- coding: utf-8 -*-

from flask.json import loads
from requests.api import delete
from flask_cors import CORS
from flask import Flask, request, jsonify
import os
import sys
import requests
import asyncio
import json
from cpu_load_generator import load_single_core
# Hack to alter sys path, so we will run from microservices package
# This hack will require us to import with absolut path from everywhere in this module
APP_ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.append(os.path.dirname(APP_ROOT))

loop = asyncio.get_event_loop()

app = Flask(__name__)
CORS(app)


def memory_chunk(size_in_kb):
    l = []
    for i in range(0, size_in_kb):
        l.append("*" * 1024)  # 1KB
    return l


async def generate_memory_load(params):
    duration_seconds = params.get("duration_seconds", 0.1)  # def 100ms
    kb_count = params.get("kb_count", 64)  # def 64KB
    l = memory_chunk(kb_count)
    asyncio.sleep(duration_seconds)
    del l
    return ""


async def generate_cpu_load(params):
    duration_seconds = params.get("duration_seconds", 0.1)  # def 100ms
    cpu_load = params.get("load", 0.1)  # def 10%
    core_num = params.get("core_num", 0)  # def 0
    load_single_core(core_num=core_num,
                     duration_s=duration_seconds,
                     target_load=cpu_load)
    asyncio.sleep(duration_seconds)
    return ""


async def propogate_request():
    dsts = os.environ.get("DEPENDENCIES", "")
    if dsts == "":
        return []
    futures = []
    for dst in json.loads(dsts).get("destinations", []):
        target = dst.get("target", None)
        if target is None:
            continue
        config = dst.get("config", {})
        payload_kb_size = dst.get("request_payload_kb_size", 10)  # Def 50KB
        config["dummy_paload_just_for_size"] = memory_chunk(payload_kb_size)
        f = loop.run_in_executor(None, requests.post, target, None, config)
        futures.append(f)
    responses = await asyncio.gather(*futures)
    return list(filter(lambda t: t != "", map(lambda res: res.text, responses)))


@app.route('/health', methods=['GET'])
def health():
    return 'OK'


@app.route('/load', methods=['POST'])
def load():
    load_options = request.json
    print("running load with options {}".format(load_options))

    responses = loop.run_until_complete(asyncio.gather(
        generate_memory_load(load_options.get('memory_params', {})),
        generate_cpu_load(load_options.get('cpu_params', {})),
        propogate_request(),
    ))
    my_name = os.environ.get("RETURN_VALUE", "NOT_SET")
    propogated_services = responses[-1]  # Note propogate_request is last
    res = ""
    if len(propogated_services) == 0:
        res = my_name
    else:
        for ps in propogated_services:
            res += "{} -> {}\n".format(my_name, ps)
    return res


if __name__ == '__main__':
    # threaded=True is a debugging feature, use WSGI for production!
    app.run(host='0.0.0.0', port='8081', threaded=False)
