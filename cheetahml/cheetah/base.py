import os
import typing

from celery import Celery
from abc import ABC, abstractmethod

from cheetah.shared_utils.logger.logger import logger
from cheetah.shared_utils.configurator import configurator


class BaseMLModel(ABC):  # TODO: make data validation
    def __init__(self):
        pass

    @abstractmethod
    def generate(self, batch: list[dict]) -> list[dict]:
        ...

    @abstractmethod
    def load_model(self):
        ...


class Base:

    def __init__(self, broker_url, result_backend, with_batcher: bool):
        self.broker_url = broker_url
        self.result_backend = result_backend
        self.with_batcher = with_batcher

    def _create_celery_app(self):
        self._celery_app = Celery()
        self._celery_app.conf.update({
            'broker_url': "redis://" + self.broker_url,
            'result_backend': "redis://" + self.result_backend,
            'broker_connection_retry_on_startup': True,
            'redis_backend_health_check_interval': 30,
            'result_expires': 60 * 60 * 6,
            'task_store_errors_even_if_ignored': True,
            'timezone': 'UTC',
            'task_routes': ('cheetah.routes.TaskBatchRouter', 'cheetah.routes.TaskPromptRouter'),
            'broker_transport_options': {
                'priority_steps': list(range(2)),  # Define priority steps
                'sep': ':',  # Define separator for priority queues
                'queue_order_strategy': 'priority',  # Set queue order strategy
            }
        })
        logger.info("Celery app was created")

    def update_config(cls, __name, __value):
        configurator.update_config(cls, __name, __value)

    def config_from_file(cls, config_path: str):
        configurator.config_from_file(cls, config_path)
