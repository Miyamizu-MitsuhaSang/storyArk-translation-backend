# 全局 Redis 客户端
from typing import Optional, AsyncGenerator

import redis.asyncio as redis

redis_client: Optional[redis.Redis] = None


# 初始化 Redis（应用启动时调用）
async def init_redis():
    global redis_client
    if redis_client is None:
        redis_client = redis.Redis(
            host="127.0.0.1",
            port=6379,
            decode_responses=True,  # 返回 str 而不是 Bytes
        )
    await redis_client.ping()

    return redis_client


async def close_redis():
    global redis_client
    if redis_client:
        try:
            await redis_client.close()
        except Exception:
            pass
        redis_client = None


# FastAPI 依赖注入用的获取方法
async def get_redis() -> AsyncGenerator[redis.Redis, None]:
    global redis_client
    if redis_client is None:
        await init_redis()  # 懒加载，避免 NoneType
    yield redis_client
