from declaw import (
    EntryInfo,
    FilesystemEvent,
    FilesystemEventType,
    FileType,
    WriteEntry,
    WriteInfo,
)


class TestEntryInfo:
    def test_file_entry(self):
        e = EntryInfo(name="test.py", path="/home/user/test.py", type=FileType.FILE, size=1024)
        assert e.type == FileType.FILE
        d = e.to_dict()
        assert d["type"] == "file"

    def test_dir_entry(self):
        e = EntryInfo(name="src", path="/home/user/src", type=FileType.DIR)
        assert e.type == FileType.DIR

    def test_round_trip(self):
        e = EntryInfo(name="f.txt", path="/f.txt", type=FileType.FILE, size=42)
        restored = EntryInfo.from_dict(e.to_dict())
        assert restored.name == "f.txt"
        assert restored.size == 42


class TestWriteInfo:
    def test_round_trip(self):
        w = WriteInfo(path="/out.txt", size=256)
        restored = WriteInfo.from_dict(w.to_dict())
        assert restored.path == "/out.txt"
        assert restored.size == 256


class TestWriteEntry:
    def test_str_data(self):
        w = WriteEntry(path="/hello.txt", data="hello world")
        d = w.to_dict()
        assert d["data"] == "hello world"

    def test_bytes_data_rejects_to_dict(self):
        """Bytes entries must not be serialized into the JSON batch request.
        Filesystem.write_files dispatches them to PUT /files/raw instead.
        """
        import pytest

        w = WriteEntry(path="/bin.dat", data=b"\x00\x01\x02")
        with pytest.raises(TypeError, match="requires str data"):
            w.to_dict()


class TestFilesystemEvent:
    def test_create_event(self):
        ev = FilesystemEvent(type=FilesystemEventType.CREATE, path="/new.txt", timestamp=1234.0)
        assert ev.type == FilesystemEventType.CREATE

    def test_round_trip(self):
        ev = FilesystemEvent(type=FilesystemEventType.WRITE, path="/mod.txt", timestamp=5678.0)
        restored = FilesystemEvent.from_dict(ev.to_dict())
        assert restored.type == FilesystemEventType.WRITE
        assert restored.path == "/mod.txt"
        assert restored.timestamp == 5678.0

    def test_all_event_types(self):
        for t in FilesystemEventType:
            ev = FilesystemEvent(type=t, path="/test")
            assert ev.to_dict()["type"] == t.value
