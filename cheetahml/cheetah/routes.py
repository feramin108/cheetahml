class TaskBatchRouter:
    def route_for_task(self, task, *args, **kwargs):
        if ':' not in task:
            return {'queue': 'celery'}

        namespace, _ = task.split(':')
        return {'queue': f'{namespace}_batch_queue',
                'exchange': f'{namespace}_exchange',
                'exchange_type': 'direct'}


class TaskPromptRouter:
    def route_for_task(self, task, *args, **kwargs):
        if ':' not in task:
            return {'queue': 'celery'}

        namespace, _ = task.split(':')
        return {'queue': f'{namespace}_prompt_queue',
                'exchange': f'{namespace}_exchange',
                'exchange_type': 'direct'}
