import asyncio
import functools
import logging

from metrics.node_metrics import metrics, MetricField


def log_exceptions(func):
    if asyncio.iscoroutinefunction(func):

        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            try:
                return await func(*args, **kwargs)
            except Exception:
                metrics().increment(MetricField.ERRORS)
                logging.error(f"Exception in {func.__qualname__}", exc_info=True)
                raise
    else:

        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            try:
                return func(*args, **kwargs)
            except Exception:
                metrics().increment(MetricField.ERRORS)
                logging.error(f"Exception in {func.__qualname__}", exc_info=True)
                raise

    return wrapper
