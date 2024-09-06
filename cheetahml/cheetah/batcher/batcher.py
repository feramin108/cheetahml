import grpc
import time
import typing

from celery.exceptions import Ignore

from cheetah.grpc_manager_protobuf import manager_pb2 as manager_pb2
from cheetah.grpc_manager_protobuf import manager_pb2_grpc as manager_pb2_grpc

from .scheduler import Scheduler
from cheetah.base import Base
from threading import Thread
from . import batch, last_time_sent
from cheetah.db.redis_manager import RedisManager
from cheetah.shared_utils.logger.logger import logger
from cheetah.shared_utils.status_codes.status_codes import TaskStates, StatusCodesGRPC
from cheetah.shared_utils.status_codes.status_codes_tools import update_status


class Batcher(Base):
    _model_name: str
    _PARAMETERS: typing.Final[dict] = {'model_name': 'ModelA',
                                       'broker_url': '127.0.0.1:6379/0',
                                       'result_backend': '127.0.0.1:6379/1',
                                       'grpc_url': '127.0.0.1:50051',
                                       'batch_size': 5,
                                       'timeout': 1}

    def __init__(self, model_name: str | None = None,
                 broker_url: str | None = None,
                 result_backend: str | None = None,
                 grpc_url: str | None = None,
                 timeout: int | None = None,
                 batch_size: int | None = None):
        super().__init__(broker_url, result_backend, with_batcher=True)

        self.model_name = None
        self.scheduler = None
        self.grpc_url = None
        self.timeout = None
        self.batch_size = None

        self.update_config("broker_url",
                           self._PARAMETERS["broker_url"] if broker_url is None else broker_url)

        self.update_config("result_backend",
                           self._PARAMETERS["result_backend"] if result_backend is None else result_backend)

        self.update_config("grpc_url",
                           self._PARAMETERS["grpc_url"] if grpc_url is None else grpc_url)

        self.update_config("timeout",
                           self._PARAMETERS["timeout"] if timeout is None else timeout)

        self.update_config("batch_size",
                           self._PARAMETERS["batch_size"] if batch_size is None else batch_size)

        self.update_config("model_name",
                           self._PARAMETERS["model_name"] if model_name is None else model_name)

        self.stub = None

        self._create_redis_client()

    def _create_redis_client(self):
        self._redisManager = RedisManager(url=self.broker_url)
        logger.info("Redis client was created in Batcher")

    def _create_batcher_worker(self):

        @self._celery_app.task(name=f'{self.model_name}:send_batch',
                               queue=f'{self.model_name}_prompt_queue',
                               ignore_result=True)
        def send_batch(new_batch: dict, timeout: bool, request=None):
            global last_time_sent
            global batch
            if timeout:
                sending_batch = batch
            else:
                sending_batch = new_batch

            if (time.time() - last_time_sent > self.timeout and len(sending_batch.keys()) != 0
                    or len(sending_batch.keys()) == self.batch_size):

                res = self._celery_app.send_task(f"{self.model_name}:inference",
                                                 kwargs={"batch": sending_batch},
                                                 queue=f"{self.model_name}_batch_queue", priority=1)
                for i in range(len(sending_batch)):
                    task_origin_id = sending_batch[str(i)]["task_origin_id"]
                    update_status(task_origin_id, TaskStates.IN_MODEL_QUEUE.name, worker=send_batch.request.hostname,
                                  queue=f"{self.model_name}_batch_queue",
                                  task_name=f'{self.model_name}:send_batch', new_batch=new_batch,
                                  timeout=timeout, request=request)
                logger.info("Batch sent: %s", sending_batch)
                last_time_sent = time.time()
                batch.clear()
            else:
                logger.info("Collecting batch")

        @self._celery_app.task(name=f'{self.model_name}:collect_to_batch', ignore_result=True)
        def collect_to_batch(request, watchdog_task_origin_id=None):
            try:
                global last_time_sent
                global batch

                task_origin_id = collect_to_batch.request.id if watchdog_task_origin_id is None else watchdog_task_origin_id
                next_key = len(batch.keys())

                batch[str(next_key)] = {
                    "task_origin_id": task_origin_id,
                    "request": request}
                update_status(task_origin_id, TaskStates.COLLECTED_TO_BATCH.name,
                              worker=collect_to_batch.request.hostname, task_name=f'{self.model_name}:collect_to_batch',
                              queue=f"{self.model_name}_prompt_queue", request=request)
                logger.info(f"Task {task_origin_id} was added to batch")
                logger.info(f"Current batch: {batch}")
                if len(batch.keys()) == self.batch_size:
                    send_batch.delay(batch, False, request, priority=1)
                    batch.clear()
            except Exception as ex:
                logger.error(ex)
                raise Ignore()

            finally:
                raise Ignore()

    def start_worker(self):
        self._create_celery_app()
        self._create_batcher_worker()
        try:
            channel = grpc.insecure_channel(self.grpc_url)
            self.stub = manager_pb2_grpc.ManagerStub(channel)

            message = self.stub.GetBatcherExistence(manager_pb2.ModelName(name=self.model_name), wait_for_ready=True)
            logger.info("Message status: %s", message.status)
            if message.status == StatusCodesGRPC.EXISTS.name:
                error_text = "Batcher for that model is already exist"
                raise RuntimeError(error_text)
            else:
                try:
                    self.scheduler = Scheduler(int(self.timeout),
                                               int(self.batch_size),
                                               self._celery_app,
                                               self.model_name)
                    worker = self._celery_app.Worker(pool='threads', concurrency=1, loglevel="info",
                                                     queues=('celery', f'{self.model_name}_prompt_queue'),
                                                     hostname='batcher_worker')

                    self.stub.NewBatcherInstanceRegister(manager_pb2.ModelName(name=self.model_name),
                                                         wait_for_ready=True)  # TODO: Do i need to wait? Logic of wait
                    self.scheduler.repeat_task()
                    Thread(target=self.scheduler.scheduler.run, daemon=True).start()
                    worker.start()
                finally:
                    info = self.stub.BatcherShutdown(manager_pb2.ModelName(name=self.model_name), wait_for_ready=True)
                    logger.info("Batcher shutdown result status: %s", info.status)
        except RuntimeError as e:
            logger.error(e)
