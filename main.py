import sys

from tosco.core.config import Config
from tosco.ui.app import run

if __name__ == "__main__":
    sys.exit(run(Config()))
