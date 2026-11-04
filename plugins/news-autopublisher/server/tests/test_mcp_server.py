import json

import pytest
from mcp import Client

from newsautopublisher import server


@pytest.fixture
def mcp_server(data_dir):
    server._app = None  # nouvelle instance sur le dossier de données du test
    yield server.mcp
    server._app = None


async def _call(client, name, args):
    r = await client.call_tool(name, args)
    return r.is_error, r.content[0].text


@pytest.mark.anyio
async def test_tools_and_guards(mcp_server):
    async with Client(mcp_server) as c:
        names = {t.name for t in (await c.list_tools()).tools}
        assert {"create_draft", "render_short", "approve_draft", "publish", "mark_published"} <= names

        err, text = await _call(c, "create_draft", {
            "project": "exode", "language": "fr", "topic": "Test",
            "discord": {"content": "Salut"}, "channels": ["discord.test"],
        })
        assert not err
        draft_id = json.loads(text)["id"]

        err, text = await _call(c, "publish", {"draft_id": draft_id})
        assert err and "approuvé" in text

        err, text = await _call(c, "create_draft", {"project": "inconnu", "language": "fr", "topic": "x"})
        assert err and "Projet inconnu" in text


@pytest.fixture
def anyio_backend():
    return "asyncio"
