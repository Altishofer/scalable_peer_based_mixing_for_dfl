import asyncio
import logging
import sys

import torch

from metrics.node_metrics import init_metrics, metrics
from peer_node import PeerNode
from utils.config_store import ConfigStore
from utils.logging_config import setup_logging


def _silence_shielded_connection_errors(loop, context):
    exc = context.get("exception")
    if isinstance(exc, ConnectionError):
        return
    loop.default_exception_handler(context)


async def node_main():
    config = ConfigStore()

    setup_logging(config.node_id)

    asyncio.get_running_loop().set_exception_handler(_silence_shielded_connection_errors)

    torch.set_num_threads(config.torch_threads)
    torch.set_num_interop_threads(1)

    logging.info(
        "runtime: python=%s torch_threads=%d",
        sys.version.split()[0],
        torch.get_num_threads(),
    )

    init_metrics(controller_url=config.controller_url, host_name=f"node_{config.node_id}")
    metrics().start_push_loop()

    join_round = config.my_join_round()
    if join_round > 0:
        logging.info(f"Node waiting to join at round {join_round}")
        await metrics().wait_for_round(join_round)

    node = PeerNode(config)
    await node.start()


if __name__ == "__main__":
    asyncio.run(node_main())
