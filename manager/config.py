import os
from pathlib import Path


class Settings:
    METRICS_DIR = Path(os.environ.get("METRICS_DIR", "./metrics"))
    IMAGE_NAME = os.environ.get("IMAGE_NAME", "dfl_node")
    QUIC_BASE_PORT = int(os.environ.get("QUIC_BASE_PORT", "4433"))
    METRICS_INTERVAL = int(os.environ.get("METRICS_INTERVAL", "15"))
    SECRETS_PATH = os.path.abspath(os.environ.get("SECRETS_PATH", "./secrets"))
    NODE_PATH = os.path.abspath(os.environ.get("NODE_PATH", "./node"))
    DATA_PATH = os.path.abspath(os.environ.get("DATA_PATH", "./data"))
    MGR_URL = os.environ.get("MGR_URL", "http://127.0.0.1:8000")
    HOST_RESERVED_CORES = int(os.environ.get("MIXDFL_HOST_RESERVED_CORES", "4"))
    NODE_CORES = max(1, (os.cpu_count() or 1) - HOST_RESERVED_CORES)

    def __init__(self):
        self.METRICS_DIR.mkdir(exist_ok=True)


settings = Settings()
