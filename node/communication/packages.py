import zlib
from enum import Enum

import msgpack


class PackageType(Enum):
    MODEL_PART = 1
    COVER = 2
    PROBE = 3


def format_probe_package(content):
    return {"type": PackageType.PROBE, "content": content}


def format_model_package(current_round, chunk_idx, chunk, n_chunks):
    return {
        "type": PackageType.MODEL_PART,
        "round": current_round,
        "part_idx": chunk_idx,
        "total_parts": n_chunks,
        "content": chunk,
    }


def format_cover_package(content):
    return {"type": PackageType.COVER, "content": content}


def serialize_msg(msg) -> bytes:
    if "type" in msg and isinstance(msg["type"], PackageType):
        msg = msg.copy()
        msg["type"] = msg["type"].value
    data = msgpack.packb(msg, use_bin_type=True)
    return zlib.compress(data)


def deserialize_msg(msg: bytes) -> dict:
    result = msgpack.unpackb(zlib.decompress(msg), raw=False)
    if "type" in result and isinstance(result["type"], int):
        result["type"] = PackageType(result["type"])
    return result
