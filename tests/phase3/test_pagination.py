import httpx
import pytest
import respx

from declaw.api.async_client import AsyncApiClient
from declaw.api.client import ApiClient
from declaw.connection_config import ConnectionConfig
from declaw.sandbox_async.paginator import AsyncSandboxPaginator, AsyncSnapshotPaginator
from declaw.sandbox_sync.paginator import SandboxPaginator, SnapshotPaginator

API_URL = "https://api.test.dev"


@pytest.fixture
def config():
    return ConnectionConfig(api_key="test-key", api_url=API_URL)


@pytest.fixture
def sync_client(config):
    return ApiClient(config)


@pytest.fixture
def async_client(config):
    return AsyncApiClient(config)


def _sandbox_page(ids, next_token=None):
    return {
        "sandboxes": [
            {
                "sandbox_id": sid,
                "template_id": "tpl-1",
                "name": "base",
                "state": "running",
                "metadata": {},
            }
            for sid in ids
        ],
        "next_token": next_token,
    }


def _snapshot_page(ids, next_token=None):
    return {
        "snapshots": [{"snapshot_id": sid, "sandbox_id": "sbx-1"} for sid in ids],
        "next_token": next_token,
    }


class TestSandboxPaginator:
    @respx.mock
    def test_three_pages(self, sync_client):
        respx.get(f"{API_URL}/sandboxes").mock(
            side_effect=[
                httpx.Response(200, json=_sandbox_page(["sbx-1", "sbx-2"], next_token="page2")),
                httpx.Response(200, json=_sandbox_page(["sbx-3", "sbx-4"], next_token="page3")),
                httpx.Response(200, json=_sandbox_page(["sbx-5"])),
            ]
        )
        pag = SandboxPaginator(sync_client, limit=2)
        all_items = []
        while pag.has_next:
            items = pag.next_items()
            all_items.extend(items)
        assert len(all_items) == 5
        assert all_items[0].sandbox_id == "sbx-1"
        assert all_items[4].sandbox_id == "sbx-5"
        assert not pag.has_next

    @respx.mock
    def test_single_page(self, sync_client):
        respx.get(f"{API_URL}/sandboxes").mock(
            return_value=httpx.Response(200, json=_sandbox_page(["sbx-only"]))
        )
        pag = SandboxPaginator(sync_client)
        items = pag.next_items()
        assert len(items) == 1
        assert not pag.has_next

    @respx.mock
    def test_empty(self, sync_client):
        respx.get(f"{API_URL}/sandboxes").mock(
            return_value=httpx.Response(200, json=_sandbox_page([]))
        )
        pag = SandboxPaginator(sync_client)
        items = pag.next_items()
        assert len(items) == 0
        assert not pag.has_next


class TestSnapshotPaginator:
    @respx.mock
    def test_two_pages(self, sync_client):
        respx.get(f"{API_URL}/snapshots").mock(
            side_effect=[
                httpx.Response(200, json=_snapshot_page(["snap-1"], next_token="p2")),
                httpx.Response(200, json=_snapshot_page(["snap-2"])),
            ]
        )
        pag = SnapshotPaginator(sync_client, limit=1)
        all_items = []
        while pag.has_next:
            all_items.extend(pag.next_items())
        assert len(all_items) == 2


class TestAsyncSandboxPaginator:
    @respx.mock
    @pytest.mark.asyncio
    async def test_three_pages(self, async_client):
        respx.get(f"{API_URL}/sandboxes").mock(
            side_effect=[
                httpx.Response(200, json=_sandbox_page(["sbx-a1", "sbx-a2"], next_token="p2")),
                httpx.Response(200, json=_sandbox_page(["sbx-a3"], next_token="p3")),
                httpx.Response(200, json=_sandbox_page(["sbx-a4"])),
            ]
        )
        pag = AsyncSandboxPaginator(async_client, limit=2)
        all_items = []
        while pag.has_next:
            items = await pag.next_items()
            all_items.extend(items)
        assert len(all_items) == 4
        assert not pag.has_next

    @respx.mock
    @pytest.mark.asyncio
    async def test_exhausted_raises(self, async_client):
        respx.get(f"{API_URL}/sandboxes").mock(
            return_value=httpx.Response(200, json=_sandbox_page([]))
        )
        pag = AsyncSandboxPaginator(async_client)
        await pag.next_items()
        assert not pag.has_next
        with pytest.raises(RuntimeError, match="No more pages"):
            await pag.next_items()


class TestAsyncSnapshotPaginator:
    @respx.mock
    @pytest.mark.asyncio
    async def test_single_page(self, async_client):
        respx.get(f"{API_URL}/snapshots").mock(
            return_value=httpx.Response(200, json=_snapshot_page(["snap-a1"]))
        )
        pag = AsyncSnapshotPaginator(async_client)
        items = await pag.next_items()
        assert len(items) == 1
        assert not pag.has_next
