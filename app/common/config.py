from functools import lru_cache

from app.common.env import Env


@lru_cache(maxsize=1)
def get_settings() -> Env:
    return Env()


settings = get_settings()
