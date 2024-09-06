import redis
import json

from cheetah.shared_utils.logger.logger import logger


class Acknowledgment(dict):
    __getattr__ = dict.__getitem__
    __setattr__ = dict.__setitem__
    __delattr__ = dict.__delitem__


def compose_acknowledgment(status: str, status_code: int, done: bool, error: str = None) -> Acknowledgment:
    return Acknowledgment({'status': status,
                           'status_code': status_code,
                           'done': done,
                           'error': error})


class RedisManager:
    def __init__(self, url="localhost:6379/1"):
        host, port, db = self._serialize_url(url)
        self.r = redis.Redis(host=host, port=port, db=db, decode_responses=True)

    @staticmethod
    def _serialize_url(url):
        host, rest = url.split(":")
        port, db = rest.split("/")
        return host, port, db

    @staticmethod
    def _form_response(key, response, date):
        formed_response = {"status": "SUCCESS",
                           "result": {"traceback": "null",
                                      "children": [],
                                      "date_done": date,
                                      "task_id": key}
                           }
        for res_key in response.keys():
            formed_response["result"][res_key] = response[res_key]
        return formed_response

    def send_response(self, key, response, date) -> str:
        try:
            meta_key = f"celery-task-meta-{key}"
            self.r.set(meta_key, json.dumps(self._form_response(key, response, date)))
            return "Success"
        except Exception as e:
            logger.error("Send response to Redis failed", e)
            return "Failure"

    def update_task_status(self, key: str, status: str) -> str:
        try:
            meta_key = f"celery-task-meta-{key}"
            status_state = {"status": status}
            self.r.set(meta_key, json.dumps(status_state))
            return "Success"
        except Exception as e:
            logger.error("Updating task status failed", e)
            return "Failure"
