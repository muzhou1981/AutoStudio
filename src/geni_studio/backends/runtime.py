"""执行期间读取 Run 保存的配置，避免配置页修改影响正在等待的轮次。"""

from contextlib import contextmanager
from contextvars import ContextVar

_config: ContextVar[dict | None] = ContextVar("geni_runtime_config", default=None)


def current_config() -> dict | None:
    return _config.get()


@contextmanager
def use_config(config: dict | None):
    token = _config.set(config)
    try:
        yield
    finally:
        _config.reset(token)
