from rq import Worker
from os import environ
import redis
import uuid
import downloader


WORKER_ID = str(uuid.uuid4())

r = redis.Redis(host=environ["REDIS_HOSTNAME"], port=6379, db=0)
# Provide the worker with the list of queues (str) to listen to.
w = Worker([environ["QUEUE_NAME"]], connection=r, name=WORKER_ID)
w.work()