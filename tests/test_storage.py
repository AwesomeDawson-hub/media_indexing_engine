"""Unit tests for S3FileStore using a mocked boto3 client (P3-004)."""

from unittest.mock import MagicMock, patch, AsyncMock
import io
import pytest

from src.storage.file_store import S3FileStore, get_file_store, LocalFileStore
from src.config import StorageConfig


@pytest.fixture
def mock_boto3_client():
    """Return a mock S3 client that tracks calls."""
    client = MagicMock()
    # head_object exists by default
    client.head_object.return_value = {"ContentLength": 5}
    # get_object returns a stream-like object
    body = MagicMock()
    body.read.return_value = b"hello"
    client.get_object.return_value = {"Body": body}
    return client


@pytest.fixture
def s3_store(mock_boto3_client):
    store = S3FileStore(bucket="test-bucket", region="us-east-1")
    # Patch _client to return mock instead of real boto3
    store._client = lambda: mock_boto3_client
    return store, mock_boto3_client


class TestS3FileStoreSave:
    @pytest.mark.asyncio
    async def test_save_returns_correct_path(self, s3_store):
        store, client = s3_store
        path = await store.save("user1", "abc123", "photo.jpg", b"data")
        assert path == "user1/abc123/photo.jpg"

    @pytest.mark.asyncio
    async def test_save_calls_put_object(self, s3_store):
        store, client = s3_store
        await store.save("user1", "abc123", "photo.jpg", b"data")
        client.put_object.assert_called_once_with(
            Bucket="test-bucket", Key="user1/abc123/photo.jpg", Body=b"data"
        )

    @pytest.mark.asyncio
    async def test_save_truncates_long_filename(self, s3_store):
        store, client = s3_store
        long_name = "a" * 200 + ".jpg"
        path = await store.save("user1", "abc123", long_name, b"data")
        filename_part = path.split("/")[-1]
        assert len(filename_part) <= 70


class TestS3FileStoreRead:
    @pytest.mark.asyncio
    async def test_read_returns_bytes(self, s3_store):
        store, client = s3_store
        data = await store.read("user1/abc123/photo.jpg")
        assert data == b"hello"

    @pytest.mark.asyncio
    async def test_read_calls_get_object(self, s3_store):
        store, client = s3_store
        await store.read("user1/abc123/photo.jpg")
        client.get_object.assert_called_once_with(
            Bucket="test-bucket", Key="user1/abc123/photo.jpg"
        )


class TestS3FileStoreExists:
    @pytest.mark.asyncio
    async def test_exists_returns_true_when_object_present(self, s3_store):
        store, client = s3_store
        result = await store.exists("user1/abc123/photo.jpg")
        assert result is True

    @pytest.mark.asyncio
    async def test_exists_returns_false_on_exception(self, s3_store):
        store, client = s3_store
        client.head_object.side_effect = Exception("NoSuchKey")
        result = await store.exists("user1/abc123/missing.jpg")
        assert result is False


class TestS3FileStoreDelete:
    @pytest.mark.asyncio
    async def test_delete_calls_delete_object(self, s3_store):
        store, client = s3_store
        await store.delete("user1/abc123/photo.jpg")
        client.delete_object.assert_called_once_with(
            Bucket="test-bucket", Key="user1/abc123/photo.jpg"
        )

    @pytest.mark.asyncio
    async def test_delete_swallows_exception(self, s3_store):
        store, client = s3_store
        client.delete_object.side_effect = Exception("network error")
        # Should not raise
        await store.delete("user1/abc123/photo.jpg")


class TestGetFileStoreFactory:
    def test_local_provider_returns_local_store(self, tmp_path):
        cfg = StorageConfig(provider="local", local_path=str(tmp_path))
        store = get_file_store(cfg)
        assert isinstance(store, LocalFileStore)

    def test_s3_provider_returns_s3_store(self):
        cfg = StorageConfig(provider="s3", s3_bucket="my-bucket", s3_region="eu-west-1")
        store = get_file_store(cfg)
        assert isinstance(store, S3FileStore)

    def test_s3_provider_without_bucket_raises(self):
        cfg = StorageConfig(provider="s3", s3_bucket="")
        with pytest.raises(RuntimeError, match="s3_bucket"):
            get_file_store(cfg)
