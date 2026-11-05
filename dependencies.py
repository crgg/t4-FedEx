"""
Dependencias compartidas por los routers.

Los recursos de infraestructura se crean en main.py y se publican en
`app.state`; aquí solo se leen, así ningún router importa main.py.
"""
import redis.asyncio as redis
from celery import Celery
from fastapi import Request


def get_redis(request: Request) -> redis.Redis:
    return request.app.state.redis_client


def get_celery(request: Request) -> Celery:
    return request.app.state.celery_app


async def get_db(request: Request):
    async with request.app.state.session_factory() as session:
        yield session
