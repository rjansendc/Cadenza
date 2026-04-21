import sys
import os

# os.path.dirname can return empty string on Windows
# os.path.abspath fixes that
rootdir = os.path.abspath(os.path.dirname(__file__))
sys.path.insert(0, rootdir)