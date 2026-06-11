import json

import httpx
import pytest
import respx

from declaw import FileType, Sandbox, WriteEntry, WriteInfo

API_URL = "https://api.test.dev"

SANDBOX_RESP = {
    "sandbox_id": "sbx-fs",
    "template_id": "tpl-base",
    "name": "base",
    "envd_access_token": "tok-1",
    "sandbox_domain": "test.dev",
    "state": "running",
    "metadata": {},
}


@pytest.fixture(autouse=True)
def env_setup(monkeypatch):
    monkeypatch.setenv("DECLAW_API_KEY", "test-key")
    monkeypatch.setenv("DECLAW_DOMAIN", "api.test.dev")


def _create_sandbox():
    return Sandbox.create(api_key="test-key", domain="api.test.dev")


class TestFilesystemRead:
    @respx.mock
    def test_read_text(self):
        respx.post(f"{API_URL}/sandboxes").mock(return_value=httpx.Response(201, json=SANDBOX_RESP))
        respx.get(f"{API_URL}/sandboxes/sbx-fs/files").mock(
            return_value=httpx.Response(200, text="file content here")
        )
        sandbox = _create_sandbox()
        content = sandbox.files.read("/test.txt")
        assert content == "file content here"

    @respx.mock
    def test_read_bytes(self):
        respx.post(f"{API_URL}/sandboxes").mock(return_value=httpx.Response(201, json=SANDBOX_RESP))
        respx.get(f"{API_URL}/sandboxes/sbx-fs/files").mock(
            return_value=httpx.Response(200, content=b"\x00\x01\x02")
        )
        sandbox = _create_sandbox()
        content = sandbox.files.read("/bin.dat", format="bytes")
        assert isinstance(content, bytearray)
        assert content == bytearray(b"\x00\x01\x02")

    @respx.mock
    def test_read_stream(self):
        respx.post(f"{API_URL}/sandboxes").mock(return_value=httpx.Response(201, json=SANDBOX_RESP))
        respx.get(f"{API_URL}/sandboxes/sbx-fs/files").mock(
            return_value=httpx.Response(200, content=b"stream data")
        )
        sandbox = _create_sandbox()
        chunks = list(sandbox.files.read("/big.dat", format="stream"))
        assert len(chunks) > 0


class TestFilesystemWrite:
    @respx.mock
    def test_write_string(self):
        respx.post(f"{API_URL}/sandboxes").mock(return_value=httpx.Response(201, json=SANDBOX_RESP))
        route = respx.post(f"{API_URL}/sandboxes/sbx-fs/files").mock(
            return_value=httpx.Response(200, json={"path": "/out.txt", "size": 11})
        )
        sandbox = _create_sandbox()
        info = sandbox.files.write("/out.txt", "hello world")
        assert isinstance(info, WriteInfo)
        assert info.path == "/out.txt"
        req = json.loads(route.calls[0].request.content)
        assert req["data"] == "hello world"

    @respx.mock
    def test_write_files_batch(self):
        respx.post(f"{API_URL}/sandboxes").mock(return_value=httpx.Response(201, json=SANDBOX_RESP))
        respx.post(f"{API_URL}/sandboxes/sbx-fs/files/batch").mock(
            return_value=httpx.Response(
                200,
                json=[
                    {"path": "/a.txt", "size": 5},
                    {"path": "/b.txt", "size": 3},
                ],
            )
        )
        sandbox = _create_sandbox()
        entries = [
            WriteEntry(path="/a.txt", data="hello"),
            WriteEntry(path="/b.txt", data="bye"),
        ]
        results = sandbox.files.write_files(entries)
        assert len(results) == 2


class TestFilesystemWriteBinary:
    """Pin the binary-write round-trip. Pre-fix these fail with U+FFFD corruption."""

    PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
    NON_UTF8 = bytes([0xFF, 0xFE, 0x00, 0x01, 0x80, 0x81, 0xC0, 0xC1])

    @respx.mock
    def test_write_bytes_goes_to_raw_endpoint_png_magic(self):
        respx.post(f"{API_URL}/sandboxes").mock(return_value=httpx.Response(201, json=SANDBOX_RESP))
        raw_route = respx.put(f"{API_URL}/sandboxes/sbx-fs/files/raw").mock(
            return_value=httpx.Response(200, json={"path": "/img.png", "size": len(self.PNG_MAGIC)})
        )
        sandbox = _create_sandbox()
        info = sandbox.files.write("/img.png", self.PNG_MAGIC)
        assert raw_route.called, "bytes payload must be sent to PUT /files/raw"
        assert raw_route.calls[0].request.content == self.PNG_MAGIC
        assert info.size == len(self.PNG_MAGIC)

    @respx.mock
    def test_write_bytes_non_utf8_is_byte_identical(self):
        respx.post(f"{API_URL}/sandboxes").mock(return_value=httpx.Response(201, json=SANDBOX_RESP))
        raw_route = respx.put(f"{API_URL}/sandboxes/sbx-fs/files/raw").mock(
            return_value=httpx.Response(200, json={"path": "/x.bin", "size": len(self.NON_UTF8)})
        )
        sandbox = _create_sandbox()
        sandbox.files.write("/x.bin", self.NON_UTF8)
        assert raw_route.calls[0].request.content == self.NON_UTF8

    @respx.mock
    def test_write_bytes_random_4k_roundtrips(self):
        import os as _os

        payload = _os.urandom(4096)
        respx.post(f"{API_URL}/sandboxes").mock(return_value=httpx.Response(201, json=SANDBOX_RESP))
        raw_route = respx.put(f"{API_URL}/sandboxes/sbx-fs/files/raw").mock(
            return_value=httpx.Response(200, json={"path": "/b.bin", "size": len(payload)})
        )
        sandbox = _create_sandbox()
        sandbox.files.write("/b.bin", payload)
        assert raw_route.calls[0].request.content == payload

    @respx.mock
    def test_write_bytes_request_contains_no_ffdb_fingerprint(self):
        """Explicit regression guard for the U+FFFD (0xEF 0xBF 0xBD) corruption bug."""
        respx.post(f"{API_URL}/sandboxes").mock(return_value=httpx.Response(201, json=SANDBOX_RESP))
        raw_route = respx.put(f"{API_URL}/sandboxes/sbx-fs/files/raw").mock(
            return_value=httpx.Response(200, json={"path": "/x.bin", "size": 2})
        )
        sandbox = _create_sandbox()
        sandbox.files.write("/x.bin", b"\xff\xfe")
        body = raw_route.calls[0].request.content
        assert b"\xef\xbf\xbd" not in body, "SDK lossy-decoded bytes as UTF-8 (U+FFFD fingerprint)"
        assert body == b"\xff\xfe"

    @respx.mock
    def test_write_str_still_uses_json_endpoint(self):
        """Dispatch guard: strings must NOT hit /files/raw."""
        respx.post(f"{API_URL}/sandboxes").mock(return_value=httpx.Response(201, json=SANDBOX_RESP))
        json_route = respx.post(f"{API_URL}/sandboxes/sbx-fs/files").mock(
            return_value=httpx.Response(200, json={"path": "/t.txt", "size": 5})
        )
        raw_route = respx.put(f"{API_URL}/sandboxes/sbx-fs/files/raw").mock(
            return_value=httpx.Response(200, json={"path": "/t.txt", "size": 5})
        )
        sandbox = _create_sandbox()
        sandbox.files.write("/t.txt", "hello")
        assert json_route.called
        assert not raw_route.called

    @respx.mock
    def test_write_bytes_sets_octet_stream_content_type(self):
        respx.post(f"{API_URL}/sandboxes").mock(return_value=httpx.Response(201, json=SANDBOX_RESP))
        raw_route = respx.put(f"{API_URL}/sandboxes/sbx-fs/files/raw").mock(
            return_value=httpx.Response(200, json={"path": "/x.bin", "size": 2})
        )
        sandbox = _create_sandbox()
        sandbox.files.write("/x.bin", b"\x00\x01")
        ct = raw_route.calls[0].request.headers.get("content-type", "")
        assert "application/octet-stream" in ct.lower()

    @respx.mock
    def test_write_files_mixed_types_partitions_correctly(self):
        """Bytes entries go to /files/raw; str entries stay in the JSON batch."""
        respx.post(f"{API_URL}/sandboxes").mock(return_value=httpx.Response(201, json=SANDBOX_RESP))
        batch_route = respx.post(f"{API_URL}/sandboxes/sbx-fs/files/batch").mock(
            return_value=httpx.Response(200, json=[{"path": "/a.txt", "size": 5}])
        )
        raw_route = respx.put(f"{API_URL}/sandboxes/sbx-fs/files/raw").mock(
            return_value=httpx.Response(200, json={"path": "/b.bin", "size": 2})
        )
        sandbox = _create_sandbox()
        entries = [
            WriteEntry(path="/a.txt", data="hello"),
            WriteEntry(path="/b.bin", data=b"\xff\x00"),
        ]
        results = sandbox.files.write_files(entries)
        assert len(results) == 2
        # Str entry routed through batch JSON
        assert batch_route.called
        batch_body = json.loads(batch_route.calls[0].request.content)
        batch_paths = [f["path"] for f in batch_body["files"]]
        assert batch_paths == ["/a.txt"]
        # Bytes entry routed through raw PUT
        assert raw_route.called
        assert raw_route.calls[0].request.content == b"\xff\x00"
        # Order preserved in merged results
        assert [r.path for r in results] == ["/a.txt", "/b.bin"]


class TestFilesystemList:
    @respx.mock
    def test_list_dir(self):
        respx.post(f"{API_URL}/sandboxes").mock(return_value=httpx.Response(201, json=SANDBOX_RESP))
        respx.get(f"{API_URL}/sandboxes/sbx-fs/files/list").mock(
            return_value=httpx.Response(
                200,
                json=[
                    {"name": "file.py", "path": "/home/user/file.py", "type": "file", "size": 100},
                    {"name": "src", "path": "/home/user/src", "type": "dir", "size": 0},
                ],
            )
        )
        sandbox = _create_sandbox()
        entries = sandbox.files.list("/home/user")
        assert len(entries) == 2
        assert entries[0].type == FileType.FILE
        assert entries[1].type == FileType.DIR


class TestFilesystemOps:
    @respx.mock
    def test_exists(self):
        respx.post(f"{API_URL}/sandboxes").mock(return_value=httpx.Response(201, json=SANDBOX_RESP))
        respx.get(f"{API_URL}/sandboxes/sbx-fs/files/exists").mock(
            return_value=httpx.Response(200, json={"exists": True})
        )
        sandbox = _create_sandbox()
        assert sandbox.files.exists("/test.txt") is True

    @respx.mock
    def test_get_info(self):
        respx.post(f"{API_URL}/sandboxes").mock(return_value=httpx.Response(201, json=SANDBOX_RESP))
        respx.get(f"{API_URL}/sandboxes/sbx-fs/files/info").mock(
            return_value=httpx.Response(
                200,
                json={
                    "name": "test.txt",
                    "path": "/test.txt",
                    "type": "file",
                    "size": 42,
                },
            )
        )
        sandbox = _create_sandbox()
        info = sandbox.files.get_info("/test.txt")
        assert info.size == 42

    @respx.mock
    def test_remove(self):
        respx.post(f"{API_URL}/sandboxes").mock(return_value=httpx.Response(201, json=SANDBOX_RESP))
        respx.delete(url__regex=r".*/sandboxes/sbx-fs/files.*").mock(
            return_value=httpx.Response(200, json={})
        )
        sandbox = _create_sandbox()
        sandbox.files.remove("/trash.txt")

    @respx.mock
    def test_rename(self):
        respx.post(f"{API_URL}/sandboxes").mock(return_value=httpx.Response(201, json=SANDBOX_RESP))
        respx.patch(f"{API_URL}/sandboxes/sbx-fs/files").mock(
            return_value=httpx.Response(
                200,
                json={
                    "name": "new.txt",
                    "path": "/new.txt",
                    "type": "file",
                    "size": 10,
                },
            )
        )
        sandbox = _create_sandbox()
        info = sandbox.files.rename("/old.txt", "/new.txt")
        assert info.name == "new.txt"

    @respx.mock
    def test_make_dir(self):
        respx.post(f"{API_URL}/sandboxes").mock(return_value=httpx.Response(201, json=SANDBOX_RESP))
        respx.post(f"{API_URL}/sandboxes/sbx-fs/files/mkdir").mock(
            return_value=httpx.Response(200, json={"created": True})
        )
        sandbox = _create_sandbox()
        assert sandbox.files.make_dir("/new/dir") is True

    @respx.mock
    def test_watch_dir(self):
        respx.post(f"{API_URL}/sandboxes").mock(return_value=httpx.Response(201, json=SANDBOX_RESP))
        respx.post(f"{API_URL}/sandboxes/sbx-fs/files/watch").mock(
            return_value=httpx.Response(200, json={})
        )
        sandbox = _create_sandbox()
        handle = sandbox.files.watch_dir("/home/user")
        assert handle is not None
        handle.stop()
