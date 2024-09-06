REDIS=redis-server
GRPC=python tests/system_tests/test_grpc_server.py
SERVER=python tests/system_tests/test_web_server.py
MODEL=python tests/system_tests/test_model.py
FLOWER=celery --broker=redis://localhost:6379// flower
BATCHER=python tests/system_tests/test_batcher.py

run_grpc:
	$(GRPC)

run_model:
	$(MODEL)

run_server:
	$(SERVER)

run_batcher:
	$(BATCHER)

run_flower:
	$(FLOWER)

run_redis:
	$(REDIS)