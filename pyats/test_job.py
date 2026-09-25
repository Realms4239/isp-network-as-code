import os
from pyats.easypy import run

def main(runtime):
    test_path = os.path.join(os.path.dirname(__file__), 'test_network.py')
    run(testscript=test_path, runtime=runtime)
