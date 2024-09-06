import time

from cheetah.base import Base
from cheetah.shared_utils.logger.logger import logger


class Sender(Base):
    """
   :param broker_url: url of redis-server in format 'ip:port/db_number'.
   Example: 127.0.0.1:6379/0
   :param result_backend: url of redis-server in format 'ip:port/db_number'. Should be different from broker_url.
   Example: 127.0.0.1:6379/1
   """
    _model_name: str

    def __init__(self, broker_url, result_backend, with_batcher: bool = True):
        super().__init__(broker_url, result_backend, with_batcher)

    def _create_queue(self, model_name):
        pass

    def get_celery_app(self):
        return self._celery_app

    def send_task(self, model_name: str | None = None, with_batcher: bool | None = None,
                  *args,
                  **kwargs):
        name: str = self._model_name
        batcher_flag: bool = self.with_batcher
        if model_name is not None:
            if with_batcher is None:
                error_message = "Batcher value must be passed in manual sending mode"
                logger.error(error_message)
                raise ValueError(error_message)

            name = model_name
            batcher_flag = with_batcher
        if batcher_flag:
            task_name = f"{name}:collect_to_batch"
        else:
            task_name = f"{name}:inference"
        send_queue = f"{name}_prompt_queue"
        try:
            res = self._celery_app.send_task(name=task_name, args=args, kwargs=kwargs,
                                             queue=send_queue, priority=1)
            logger.info(f"Task {task_name} was sent to queue {send_queue}")
            return res
        except Exception as ex:
            logger.error(f"An error occurred while sending Celery task: {str(ex)}")

    def create_connection(self, model_name: str = None):
        self._model_name = model_name
        self._create_celery_app()
        logger.info("Connection in Sender was established")
