from typing import Type
import types
import pytest

from cheetah.base import BaseMLModel, CheetahML

from pytest import raises

from celery.exceptions import Retry

from unittest.mock import patch

from cheetah.logger import logger


def patch__create_model_worker(self):
    @self._celery_app.task(name=f'{self.model_name}:inference')
    def inference(batch):
        return self._model.generate(batch=batch)

    return inference


def patch_integrate(self, model: Type[BaseMLModel], model_name: str):
    self._model = model()
    self.model_name = model_name
    self._create_celery_app()
    return self._create_model_worker()


class TestInference:
    class MLModelTest(BaseMLModel):
        def generate(self, batch):
            return batch

        def load_model(self):
            logger.info("Loading model")

    app = CheetahML(broker_url='localhost:6379/0',
                    result_backend='localhost:6379/1',
                    with_batcher=True)

    app._create_model_worker = types.MethodType(patch__create_model_worker, app)
    app.integrate = types.MethodType(patch_integrate, app)

    inference = app.integrate(model=MLModelTest, model_name="ModelTest")

    def test_task_success_for(self):
        task = self.inference.s(batch={1: 2, 3: 4}).apply()
        assert task.result == {1: 2, 3: 4}

        task = self.inference.s(batch="123").apply()
        assert task.result == "123"

    def test_return_type(self):
        task = self.inference.s(batch={1: 2, 3: 4}).apply()
        assert isinstance(task.result, dict)

    # TODO: test task_routes and queues creation
    # TODO: mock and test sending to redis
    # TODO: patch and test batch parsing


class TestSendResponseToRedis:
    pass


class TestBaseModelInheritance:
    pass
