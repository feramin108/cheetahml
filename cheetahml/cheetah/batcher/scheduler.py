import sched
import time

from . import batch, last_time_sent
from cheetah.shared_utils.logger.logger import logger


class Scheduler:
    scheduler = sched.scheduler(time.time, time.sleep)

    def __init__(self, timeout: int, batch_size: int, celery_app, model_name: str):
        self._TIMEOUT = timeout
        self._BATCH_SIZE = batch_size
        self._celery_app = celery_app
        self._model_name = model_name

    def send_task_(self):
        global batch
        if len(batch.keys()) != 0:
            self._celery_app.send_task(f"{self._model_name}:send_batch",
                                             kwargs={"new_batch": batch, "timeout": True},
                                             queue=f"{self._model_name}_prompt_queue", )

    def repeat_task(self):
        self.scheduler.enter(self._TIMEOUT, 1, self.repeat_task, ())
        self.scheduler.enter(self._TIMEOUT, 1, self.send_task_, ())
