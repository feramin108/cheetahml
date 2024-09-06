import sys

sys.path.insert(0, '')

from cheetah import ManagerGRPC


mgrpc = ManagerGRPC()
mgrpc.config_from_file('tests/system_tests/configfile_grpc.ini')
mgrpc.serve()

