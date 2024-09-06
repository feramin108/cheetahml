import json
import time
import typing
import grpc
import uvicorn
from prometheus_fastapi_instrumentator import Instrumentator

from cheetah.grpc_manager_protobuf import manager_pb2 as manager_pb2
from cheetah.grpc_manager_protobuf import manager_pb2_grpc as manager_pb2_grpc
from cheetah.shared_utils.configurator import configurator
from cheetah import Sender

from threading import Thread
from fastapi import APIRouter, FastAPI, Request, HTTPException
from pydantic import create_model, BaseModel, ConfigDict
from collections import defaultdict
from google.protobuf.json_format import MessageToDict
from multiprocessing import freeze_support

from cheetah.shared_utils.logger.logger import logger


class WebServer:
    api_router = APIRouter()
    app = FastAPI()
    _PARAMETERS: typing.Final[dict] = {'host': "127.0.0.1", 'port': 8080,
                                       'n_workers': 4, 'broker_url': '127.0.0.1:6379/0',
                                       'result_backend': '127.0.0.1:6379/1', 'grpc_url': '127.0.0.1:50051'}

    def __init__(self, broker_url=None,
                 result_backend=None,
                 grpc_url=None,
                 host=None,
                 port=None,
                 n_workers=None):

        self.broker_url = None  # TODO : not sure that best option, but made it for code analyzer
        self.result_backend = None
        self.grpc_url = None
        self.host = None
        self.port = None
        self.n_workers = None

        self.update_config("broker_url",
                           self._PARAMETERS["broker_url"] if broker_url is None else broker_url)

        self.update_config("result_backend",
                           self._PARAMETERS["result_backend"] if result_backend is None else result_backend)

        self.update_config("grpc_url",
                           self._PARAMETERS["grpc_url"] if grpc_url is None else grpc_url)

        self.update_config("host",
                           self._PARAMETERS["host"] if host is None else host)

        self.update_config("port",
                           self._PARAMETERS["port"] if port is None else port)

        self.update_config("n_workers",
                           self._PARAMETERS["n_workers"] if n_workers is None else n_workers)

        self.models = defaultdict(self._default_dict_value)
        channel = grpc.insecure_channel(self.grpc_url)
        self.stub = manager_pb2_grpc.ManagerStub(channel)

        self._build_sender()
        self._update_app()

        Instrumentator().instrument(self.app).expose(self.app)

    def _default_dict_value(self):
        return {"error": "No such model"}

    def _build_sender(self):
        self.sender = Sender(broker_url=self.broker_url, result_backend=self.result_backend)
        self.sender.create_connection()

    def _validate(self, json_data: str, model_name: str, dto_name: str):
        try:
            input_data = self.models[model_name][dto_name].model_validate(json_data, strict=True)
            return input_data
        except Exception as ex:
            logger.error(ex)

    def _build_router(self):
        router = APIRouter()

        class BasicDTO(BaseModel):
            any: str = None

        @router.post("/{request_model_name}/generate")
        async def generate(request_model_name: str, item: Request):
            if not len(await item.body()):
                raise HTTPException(status_code=400, detail="Empty body params")
            if request_model_name in self.models.keys():
                input_json = await item.json()
                logger.info("Received data: %s", input_json)
                try:
                    validated_data = self._validate(input_json, model_name=request_model_name, dto_name="input_dto")
                except Exception as e:
                    raise HTTPException(status_code=422,
                                        detail=f"Following body structure is expected: "
                                               f"{self._pydantic_to_dict_view(self.models[request_model_name]['input_dto'])}")
            else:
                raise HTTPException(status_code=404, detail="Model with such a name doesn't exist")
            batcher = self.models[request_model_name]["batcher"]
            if batcher:
                result = self.sender.send_task(request=validated_data.model_dump(), model_name=request_model_name,
                                               with_batcher=batcher)
            else:
                batch = {"0": {"task_origin_id": "None",
                               "request": validated_data.model_dump()}}
                result = self.sender.send_task(batch=batch, model_name=request_model_name,
                                               with_batcher=batcher)

            logger.info("Celery task id: %s", result.id)
            return result.id

        @router.get("/generate/{key}")
        async def get_generated_by_key(key: str):
            pass

        return router

    @staticmethod
    def _fields_to_pydantic(fields: list):
        pydantic_fields = {}
        for field in fields:
            if 'required' in field.keys():
                pydantic_fields[field['name']] = (field['annotation'], field['default'])
            else:
                pydantic_fields[field['name']] = (typing.Optional[field['annotation']], field['default'])
        return pydantic_fields

    @staticmethod
    def _pydantic_to_dict_view(model: typing.Type[BaseModel]) -> dict[str, dict[str, str | None]]:
        dict_view = {}
        schema = model.model_json_schema()
        for key in schema['properties'].keys():
            field = schema['properties'][key]
            default = None if field['default'] == 'PydanticUndefined' else field['default']
            if 'anyOf' in field.keys():
                field_type = ""
                for t in field['anyOf']:
                    field_type += t["type"] + " | "
                field_type = field_type[:-3]
            else:
                field_type = field['type']
            dict_view[key] = {'type': field_type,
                              'default': default}
        return dict_view

    def _build_dto(self, model_name: str, fields: list):
        pydantic_fields = self._fields_to_pydantic(fields)
        config = ConfigDict(extra='forbid')
        dto = create_model(__model_name=model_name, __config__=config, **pydantic_fields)
        return dto

    def _new_model(self):
        info = self.stub.NewModelRegister(manager_pb2.Subscribe(), wait_for_ready=True)
        for i in info:
            self.models[i.model_name] = {"model_info": i}
            logger.info(f"New model registered {i.model_name}")
            logger.info(f"New model input fields: {i.input_fields}")
            self.models[i.model_name]["input_dto"] = self._build_dto(i.model_name + 'RequestDTO',
                                                                     MessageToDict(i)["inputFields"])
            self.models[i.model_name]["output_dto"] = self._build_dto(i.model_name + 'ResponseDTO',
                                                                      MessageToDict(i)["outputFields"])
            self.models[i.model_name]["batcher"] = i.batcher

    def _update_app(self):
        router = self._build_router()
        Thread(target=self._new_model, daemon=True).start()
        self._get_models()
        self.app.include_router(router=router)

    def update_config(self, __name: str, __value):
        configurator.update_config(self, __name, __value)

    def config_from_file(self, config_path: str):
        configurator.config_from_file(self, config_path)

    def _get_models(self):
        models = self.stub.GetRegisteredModels(manager_pb2.GetRegisteredModelsParams(), wait_for_ready=True)
        models = MessageToDict(models).get('info')
        if models is None:
            raise HTTPException(status_code=404, detail="Registered models were not found")
        else:
            for model in models:
                self.models[model['modelName']] = {"model_info": model}
                logger.info(f"Model registered {model['modelName']}")
                logger.info(f"Model's input fields: {model['inputFields']}")
                self.models[model['modelName']]["input_dto"] = self._build_dto(model['modelName'] + 'RequestDTO',
                                                                               model["inputFields"])
                self.models[model['modelName']]["output_dto"] = self._build_dto(model['modelName'] + 'ResponseDTO',
                                                                                model["outputFields"])
                try:
                    self.models[model['modelName']]["batcher"] = model["batcher"]
                except KeyError:
                    self.models[model['modelName']]["batcher"] = False

    def start(self, loop="asyncio", reload=False):
        freeze_support()
        # num_workers = int(cpu_count() * 0.75)
        uvicorn.run("cheetah:WebServer.app", host=self.host, port=int(self.port), loop=loop,
                    workers=int(self.n_workers), reload=reload)
