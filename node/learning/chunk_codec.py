import numpy as np

from utils.config_store import ConfigStore


def quantize_chunk(values: np.ndarray):
    min_val = float(values.min())
    max_val = float(values.max())

    if min_val == max_val:
        return np.zeros(len(values), dtype=np.uint8), min_val, max_val

    scale = 255.0 / (max_val - min_val)
    normalized = (values - min_val) * scale

    floor = np.floor(normalized).astype(np.float32)
    frac = normalized - floor
    rounded = floor + (np.random.random(len(values)).astype(np.float32) < frac).astype(np.float32)
    return np.clip(rounded, 0, 255).astype(np.uint8), min_val, max_val


def dequantize_chunk(quantized: np.ndarray, min_val: float, max_val: float) -> np.ndarray:
    if min_val == max_val:
        return np.full(len(quantized), min_val, dtype=np.float32)
    return (min_val + quantized.astype(np.float32) * (max_val - min_val) / 255.0).astype(np.float32)


def decode_dense_chunk(chunk: dict) -> np.ndarray:
    start, end = chunk["start"], chunk["end"]
    if "qmin" in chunk:
        quantized = np.frombuffer(chunk["data"], dtype=np.uint8, count=end - start)
        return dequantize_chunk(quantized, chunk["qmin"], chunk["qmax"])
    return np.frombuffer(chunk["data"], dtype=np.float32, count=end - start)


def _encode_values(values: np.ndarray, quantize: bool) -> dict:
    if quantize:
        quantized, qmin, qmax = quantize_chunk(values)
        return {"data": quantized.tobytes(), "qmin": qmin, "qmax": qmax}
    return {"data": values.astype(np.float32).tobytes()}


def _chunk_capacity(bytes_per_chunk: int, quantize: bool) -> int:
    metadata_bytes = 8 if quantize else 0
    entry_bytes = 1 if quantize else 4
    return max(1, (bytes_per_chunk - metadata_bytes) // entry_bytes)


def create_chunks(flat_weights: np.ndarray, bytes_per_chunk: int = None) -> list:
    if bytes_per_chunk is None:
        # sphinx envelope: ~263 B nymtuple+petlib frame + ~95 B inner msgpack
        bytes_per_chunk = ConfigStore.sphinx_body_len - 512

    quantize = ConfigStore.quantization_bits == 8
    chunk_len = _chunk_capacity(bytes_per_chunk, quantize)

    chunks = []
    for start in range(0, len(flat_weights), chunk_len):
        end = min(start + chunk_len, len(flat_weights))
        chunk = {"start": start, "end": end}
        chunk.update(_encode_values(flat_weights[start:end], quantize))
        chunks.append(chunk)

    return chunks
