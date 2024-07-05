from rq import Worker
from os import environ, makedirs, path
import redis
import uuid
import downloader
import logging
import json
logger = logging.getLogger(__name__)
from distutils.sysconfig import get_python_lib
# import subprocess

WORKER_ID = str(uuid.uuid4())
r = redis.Redis(host=environ["REDIS_HOSTNAME"], port=6379, db=0)
# Provide the worker with the list of queues (str) to listen to.
w = Worker([environ["QUEUE_NAME"]], connection=r, name=WORKER_ID)

ACCESS_TOKEN = environ["ACCESS_TOKEN"]
REFRESH_TOKEN = environ["REFRESH_TOKEN"]
EXPIRY = environ["EXPIRY"]
tokens_dict = {
    "expires": int(EXPIRY),
    "refresh_token": REFRESH_TOKEN,
    "access_token": ACCESS_TOKEN
}
cache_path=f"{get_python_lib()}/pytubefix/__cache__"
if not (path.exists(cache_path)):
    makedirs(cache_path)
as_json = json.dumps(tokens_dict)
with open(f"{cache_path}/tokens.json", "w") as f:
    f.write(as_json)
logger.info("Wrote tokens.json to pytubefix __cache__ folder")
w.work()