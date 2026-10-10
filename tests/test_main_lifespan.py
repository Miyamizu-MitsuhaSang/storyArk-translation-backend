import pytest

from translation_backend import main


@pytest.mark.anyio
async def test_lifespan_enables_tortoise_global_fallback(monkeypatch):
    init_kwargs = {}

    async def fake_init(**kwargs):
        init_kwargs.update(kwargs)

    async def fake_close_connections():
        return None

    monkeypatch.setattr(main.Tortoise, "init", fake_init)
    monkeypatch.setattr(main.Tortoise, "close_connections", fake_close_connections)

    async with main.lifespan(main.app):
        pass

    assert init_kwargs["_enable_global_fallback"] is True
