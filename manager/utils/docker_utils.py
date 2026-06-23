import logging
import os
import pickle
import warnings

import docker
from sphinxmix.SphinxParams import SphinxParams

from manager.config import settings
from manager.utils.cert_utils import generate_certificates

logger = logging.getLogger(__name__)

_docker_client = None


def get_docker_client():
    global _docker_client
    if _docker_client is not None:
        return _docker_client
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            _docker_client = docker.from_env()
            _docker_client.ping()
            _docker_client.containers.list(limit=1)
        try:
            _docker_client.images.get(settings.IMAGE_NAME)
        except docker.errors.ImageNotFound:
            logger.critical(
                "Docker image '%s' not found. Build it with: docker build -t %s ./node",
                settings.IMAGE_NAME,
                settings.IMAGE_NAME,
            )
            raise SystemExit(1)
        return _docker_client
    except Exception as e:
        logger.critical("Docker is not available: %s", e)
        raise SystemExit(1) from e


def generate_keys(n: int):
    params = SphinxParams()
    group = params.group
    pkiPriv_raw = {}
    pkiPub_raw = {}

    for node_id in range(n):
        x = group.gensecret()
        y = group.expon(group.g, [x])
        pkiPriv_raw[node_id] = (node_id, x.binary(), y.export())
        pkiPub_raw[node_id] = (node_id, y.export())

    os.makedirs("./secrets", exist_ok=True)
    with open("./secrets/pki_priv.pkl", "wb") as f:
        pickle.dump(pkiPriv_raw, f)
    with open("./secrets/pki_pub.pkl", "wb") as f:
        pickle.dump(pkiPub_raw, f)

    generate_certificates(n, "./secrets/certs")


def stop_all_nodes():
    client = get_docker_client()
    containers = client.containers.list(all=True)
    for container in containers:
        if container.name.startswith("node_"):
            try:
                if container.status == "running":
                    container.stop(timeout=5)
                container.remove(force=True)
            except docker.errors.APIError:
                continue
