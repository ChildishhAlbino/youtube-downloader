from rq import Worker
from os import environ
import redis

import downloader

r = redis.Redis(host=environ["REDIS_HOSTNAME"], port=6379, db=0)
# Provide the worker with the list of queues (str) to listen to.
w = Worker([environ["QUEUE_NAME"]], connection=r)
w.work()