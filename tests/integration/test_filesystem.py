"""Integration tests: filesystem operations against the mock backend."""


class TestFilesystemOps:
    def _create_sandbox(self, mock_client):
        resp = mock_client.post(
            "/sandboxes", json={"template": "base", "timeout": 60, "secure": True}
        )
        return resp.json()["sandbox_id"]

    def test_write_and_read(self, mock_client):
        sbx_id = self._create_sandbox(mock_client)

        mock_client.post(
            f"/sandboxes/{sbx_id}/files",
            json={
                "path": "/hello.txt",
                "data": "hello world",
                "username": "user",
            },
        )

        read_resp = mock_client.get(
            f"/sandboxes/{sbx_id}/files", params={"path": "/hello.txt", "username": "user"}
        )
        assert read_resp.text == "hello world"

    def test_write_files_batch(self, mock_client):
        sbx_id = self._create_sandbox(mock_client)

        mock_client.post(
            f"/sandboxes/{sbx_id}/files/batch",
            json={
                "files": [
                    {"path": "/a.txt", "data": "aaa"},
                    {"path": "/b.txt", "data": "bbb"},
                ],
                "username": "user",
            },
        )

        a = mock_client.get(
            f"/sandboxes/{sbx_id}/files", params={"path": "/a.txt", "username": "user"}
        )
        b = mock_client.get(
            f"/sandboxes/{sbx_id}/files", params={"path": "/b.txt", "username": "user"}
        )
        assert a.text == "aaa"
        assert b.text == "bbb"

    def test_list_files(self, mock_client):
        sbx_id = self._create_sandbox(mock_client)

        mock_client.post(
            f"/sandboxes/{sbx_id}/files",
            json={"path": "/file1.txt", "data": "x", "username": "user"},
        )
        mock_client.post(
            f"/sandboxes/{sbx_id}/files",
            json={"path": "/file2.txt", "data": "y", "username": "user"},
        )

        entries = mock_client.get(
            f"/sandboxes/{sbx_id}/files/list", params={"path": "/", "username": "user"}
        ).json()
        names = [e["name"] for e in entries]
        assert "file1.txt" in names
        assert "file2.txt" in names

    def test_exists(self, mock_client):
        sbx_id = self._create_sandbox(mock_client)

        mock_client.post(
            f"/sandboxes/{sbx_id}/files",
            json={"path": "/exists.txt", "data": "yes", "username": "user"},
        )

        assert (
            mock_client.get(
                f"/sandboxes/{sbx_id}/files/exists",
                params={"path": "/exists.txt", "username": "user"},
            ).json()["exists"]
            is True
        )
        assert (
            mock_client.get(
                f"/sandboxes/{sbx_id}/files/exists",
                params={"path": "/nope.txt", "username": "user"},
            ).json()["exists"]
            is False
        )

    def test_get_info(self, mock_client):
        sbx_id = self._create_sandbox(mock_client)
        mock_client.post(
            f"/sandboxes/{sbx_id}/files",
            json={"path": "/info.txt", "data": "12345", "username": "user"},
        )

        info = mock_client.get(
            f"/sandboxes/{sbx_id}/files/info", params={"path": "/info.txt", "username": "user"}
        ).json()
        assert info["name"] == "info.txt"
        assert info["type"] == "file"
        assert info["size"] == 5

    def test_mkdir_and_list(self, mock_client):
        sbx_id = self._create_sandbox(mock_client)

        mock_client.post(
            f"/sandboxes/{sbx_id}/files/mkdir", json={"path": "/mydir", "username": "user"}
        )
        mock_client.post(
            f"/sandboxes/{sbx_id}/files",
            json={"path": "/mydir/inside.txt", "data": "inner", "username": "user"},
        )

        entries = mock_client.get(
            f"/sandboxes/{sbx_id}/files/list", params={"path": "/", "username": "user"}
        ).json()
        dir_names = [e["name"] for e in entries if e["type"] == "dir"]
        assert "mydir" in dir_names

    def test_rename(self, mock_client):
        sbx_id = self._create_sandbox(mock_client)
        mock_client.post(
            f"/sandboxes/{sbx_id}/files",
            json={"path": "/old.txt", "data": "content", "username": "user"},
        )

        rename_resp = mock_client.patch(
            f"/sandboxes/{sbx_id}/files",
            json={
                "old_path": "/old.txt",
                "new_path": "/new.txt",
                "username": "user",
            },
        )
        assert rename_resp.json()["name"] == "new.txt"

        assert (
            mock_client.get(
                f"/sandboxes/{sbx_id}/files/exists", params={"path": "/new.txt", "username": "user"}
            ).json()["exists"]
            is True
        )
        assert (
            mock_client.get(
                f"/sandboxes/{sbx_id}/files/exists", params={"path": "/old.txt", "username": "user"}
            ).json()["exists"]
            is False
        )

    def test_remove(self, mock_client):
        sbx_id = self._create_sandbox(mock_client)
        mock_client.post(
            f"/sandboxes/{sbx_id}/files",
            json={"path": "/trash.txt", "data": "bye", "username": "user"},
        )

        mock_client.delete(f"/sandboxes/{sbx_id}/files?path=/trash.txt&username=user")

        assert (
            mock_client.get(
                f"/sandboxes/{sbx_id}/files/exists",
                params={"path": "/trash.txt", "username": "user"},
            ).json()["exists"]
            is False
        )
