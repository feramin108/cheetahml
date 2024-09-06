import datetime
import time

import grpc
import typing

from cheetah.base import Base
from cheetah.base import BaseMLModel
from pydantic import BaseModel
from celery.exceptions import Ignore

from cheetah.db.redis_manager import RedisManager
from cheetah.grpc_manager_protobuf import manager_pb2 as manager_pb2
from cheetah.grpc_manager_protobuf import manager_pb2_grpc as manager_pb2_grpc
from cheetah.shared_utils.logger.logger import logger
from cheetah.shared_utils.status_codes.status_codes import TaskStates
from cheetah.shared_utils.status_codes.status_codes_tools import update_status


class CheetahML(Base):
    """
    :param broker_url: url of redis-server in format 'ip:port/db_number'. Example: 127.0.0.1:6379/0
    :param result_backend: url of redis-server in format 'ip:port/db_number'. Must be different from broker_url. Example: 127.0.0.1:6379/1
    :param with_batcher: bool value, shows whether a batch collection is needed for a model
    """
    _model: BaseMLModel
    model_name: str
    _PARAMETERS: typing.Final[dict] = {'broker_url': '127.0.0.1:6379/0',
                                       'result_backend': '127.0.0.1:6379/1',
                                       'grpc_url': '127.0.0.1:50051',
                                       'with_batcher': False,
                                       'model_name': 'test'}

    def __init__(self,
                 broker_url: str | None = None,
                 result_backend: str | None = None,
                 grpc_url: str | None = None
                 ):

        super().__init__(broker_url=broker_url,
                         result_backend=result_backend,
                         with_batcher=False)
        self.input_dto = None
        self.output_dto = None
        self.grpc_url = None
        self.stub = None
        self.with_batcher = False

        self.update_config("broker_url",
                           self._PARAMETERS["broker_url"] if broker_url is None else broker_url)

        self.update_config("result_backend",
                           self._PARAMETERS["result_backend"] if result_backend is None else result_backend)

        self.update_config("grpc_url",
                           self._PARAMETERS["grpc_url"] if grpc_url is None else grpc_url)

    def change_status(self, task_origin_id: str, state: str):
        self._redisManager.update_task_status(task_origin_id, state)

    def _create_model_worker(self):
        @self._celery_app.task(name=f'{self.model_name}:inference')  # ignore_result=False)
        def inference(batch: dict):
            try:
                for i in range(len(batch)):
                    task_id = inference.request.id if batch[str(i)]['task_origin_id'] == 'None' else batch[str(i)][
                        'task_origin_id']
                    batch[str(i)]['task_origin_id'] = task_id
                    request = batch[str(i)]['request']
                    hostname = inference.request.hostname
                    queue = f"{self.model_name}_batch_queue" if self.with_batcher else f"{self.model_name}_prompt_queue"
                    update_status(task_id, TaskStates.IN_MODEL_GENERATING.name, request=request, worker=hostname,
                                  task_name=f'{self.model_name}:inference', batch=batch, queue=queue)

                response_keys = []
                inference_batch = []
                if self.with_batcher:
                    """{'0': 
                             {'task_origin_id': 'fe06f1af-29db-48ce-a833-749fabd62e56', 
                              'request': {'request': 'Hello there', 
                                          'system_prompt': "I'm your father", 
                                          'min_tokens': 30, 
                                          'max_tokens': 512}}}"""
                    for i in range(len(batch.keys())):
                        response_keys.append(batch[str(i)]['task_origin_id'])
                        inference_batch.append(batch[str(i)]['request'])
                    logger.info(f"Response keys: {response_keys}")

                else:
                    logger.info(f"Inference request id: {task_id}")
                    response_keys.append(task_id)
                    inference_batch = [batch['0']['request']]
                response = self._model.generate(batch=inference_batch)
                self._send_response_to_redis(response_keys=response_keys, response=response)
            except Exception:
                raise Ignore()

    def _send_response_to_redis(self, response_keys: list, response: list[dict]) -> None:
        for i, key in enumerate(response_keys):
            date = datetime.datetime.now().strftime("%Y-%m-%dT%H:%M:%S.%f")
            ok = self._redisManager.send_response(key, response[i], date)
            if ok:
                logger.info("Task %s was sent to Redis with status: %s", key, ok)
            else:
                logger.error("Error sending task %s to Redis", key)

    def _create_redis_client(self):
        self._redisManager = RedisManager(url=self.result_backend)
        logger.info("Redis client was created in Model Wrapper")

    def get_celery_app(self):
        return self._celery_app

    def _collect_dto_fields(self, api: dict) -> list:
        api_list = []
        for key in api.keys():
            fields = api[key]
            if type(fields.annotation) is typing._UnionGenericAlias:
                annotation = fields.annotation.__args__[0].__name__
            else:
                annotation = fields.annotation.__name__
            field = manager_pb2.APIField(name=str(key),
                                         annotation=str(annotation),
                                         required=fields.is_required(),
                                         default=str(fields.default))
            api_list.append(field)
        return api_list

    def _construct_grpc_model_info_message(self):
        input_list = self._collect_dto_fields(self.input_dto.model_fields)
        output_list = self._collect_dto_fields(self.output_dto.model_fields)

        model_info = manager_pb2.ModelInfo(**{"model_name": self.model_name,
                                              "batcher": self.with_batcher,
                                              "input_fields": input_list,
                                              "output_fields": output_list})

        return model_info

    def _register_model(self):
        message = self._construct_grpc_model_info_message()
        response = self.stub.NewModelInstanceRegister(message, wait_for_ready=True)
        logger.info("New model register result:\n%s", response)
        # {'a': FieldInfo(annotation=str, required=True), 'b': FieldInfo(annotation=int, required=False, default=5),
        # 'c': FieldInfo(annotation=Union[float, NoneType], required=False, default=1.5)}

    def integrate(self, model: typing.Type[BaseMLModel],
                  model_name: str,
                  input_dto: typing.Type[BaseModel],
                  output_dto: typing.Type[BaseModel],
                  with_batcher: bool = False
                  ):
        logger.info(f"Model {model_name} is integrating")
        self._model = model()
        self.model_name = model_name
        self.input_dto = input_dto
        self.output_dto = output_dto
        self.with_batcher = with_batcher

        self._create_celery_app()
        self._create_model_worker()
        self._create_redis_client()

    def start_worker(self):
        channel = grpc.insecure_channel(self.grpc_url)
        self.stub = manager_pb2_grpc.ManagerStub(channel)

        self._register_model()
        self._model.load_model()
        try:
            if self.with_batcher:
                queue_name = f"{self.model_name}_batch_queue"
            else:
                queue_name = f"{self.model_name}_prompt_queue"
            worker = self._celery_app.Worker(pool='threads', concurrency=1, loglevel="info",
                                             queues=('celery', queue_name), hostname="model_worker")
            # TODO:  чем сейчас подумал пока кодил. В куде есть GPU threads и чисто из логики можно трансформер
            # запустить в тредах, и пока один тред считает n слой трансформера,
            # другой тред может считать n-1 слой для другого батча условно.
            # Да, размер занимаемой памяти увеличится, за счет мултипоточного обсчета,
            # но сами веса модели останутся одни, но общие
            logger.info(
                f"Worker {worker} has been started on queue {queue_name} with batcher status = {self.with_batcher}")
            worker.start()

        finally:
            logger.info(f"{self.stub.ModelShutDown(manager_pb2.ModelName(name=self.model_name), wait_for_ready=True)}")
