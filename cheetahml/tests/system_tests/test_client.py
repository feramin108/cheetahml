import pprint
import time
import sys
import os

print(os.listdir())
sys.path.insert(0, '')
print(sys.path)
from cheetah import Sender
import threading

app = Sender(broker_url='localhost:6379/0',
             result_backend='localhost:6379/1', with_batcher=True)

app.create_connection("ModelA")


def get_response(i):
    responses[i].state
    responses[i].get()
    times[i]


responses = []
times = []
value = []
for i in range(100):
    times.append(time.time())
    res = app.send_task("ModelA", True, {"a": "some_string", "b": 2, "c": 1.5})
    responses.append(res)
pprint.pprint(responses)
for i in range(100):
    print(responses[i])
    while responses[i].state != "SUCCESS":
        # time.sleep(2)
        print(responses[i].state)

    print(responses[i].get())
