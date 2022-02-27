# -*- coding: utf-8 -*-
from concurrent.futures import thread
from flask_cors import CORS
from flask import Flask, request
import os
import sys
import aiohttp
import asyncio
import json
# from cpu_load_generator import load_single_core
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
    await asyncio.sleep(duration_seconds)
    del l
    return ""


async def generate_cpu_load(params):
    duration_seconds = params.get("duration_seconds", 0.1)  # def 100ms
    cpu_load = params.get("load", 0.1)  # def 10%
    core_num = params.get("core_num", 0)  # def 0
    load_single_core(core_num=core_num,
                     duration_s=duration_seconds,
                     target_load=cpu_load)
    await asyncio.sleep(duration_seconds)
    return ""

async def do_post(session, target, config):
    async with session.post(target, json=config) as response:
          return await response.text()

async def propogate_request(should_propogate):
    # dsts = os.environ.get("DEPENDENCIES", "")
    dsts = "{\"destinations\":[{\"target\":\"http://172.27.131.4:8081/load\",\"request_payload_kb_size\":50,\"config\":{\"propogate\":0, \"memory_params\":{\"duration_seconds\":0.2,\"kb_count\":50},\"cpu_params\":{\"duration_seconds\":0.2,\"load\":0.2}}}]}"
    if dsts == "" or not should_propogate:
        return []
    futures = []
    desinations = json.loads(dsts).get("destinations", [])
    async with aiohttp.ClientSession() as session:
        post_tasks = []
        for dst in desinations:
            target = dst.get("target", None)
            config = dst.get("config", {})
            payload_kb_size = dst.get("request_payload_kb_size", 10)  # Def 50KB
            config["dummy_paload_just_for_size"] = memory_chunk(payload_kb_size)
            post_tasks.append(do_post(session, target, config))
        responses = await asyncio.gather(*post_tasks)
        return list(filter(lambda t: t != "", responses))


@app.route('/health', methods=['GET'])
def health():
    return 'OK'


@app.route('/load', methods=['POST'])
async def load():
    load_options = request.json
    print("running load with options {}".format(str(load_options)[:1000]))

    await generate_memory_load(load_options.get('memory_params', {}))
    await generate_cpu_load(load_options.get('cpu_params', {}))
    my_name = os.environ.get("RETURN_VALUE", "NOT_SET")
    res = my_name
    if load_options.get("propogate", True):    
        propogated_services = await propogate_request(load_options.get("propogate", True))
        for ps in propogated_services:
            res += " -> {}\n".format(ps)
    return res



if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8081, threaded=True)
