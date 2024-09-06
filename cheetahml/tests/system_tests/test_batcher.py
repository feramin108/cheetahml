import sys
import os

sys.path.insert(0, '')
from cheetah import Batcher


app = Batcher()
app.config_from_file('tests/system_tests/configfile.ini')

app.start_worker()
