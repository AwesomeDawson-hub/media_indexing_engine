"""Shared test fixtures for integration tests."""

import tempfile
from typing import AsyncGenerator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from src.database import Base
from src.models import User
from src.api import dependencies as deps
from src.api.routes import upload as upload_mod
from src.api.routes import media as media_mod
from src.storage.file_store import LocalFileStore
from src.ingestion.upload_service import UploadService
from src.config import settings
import src.database as db_module
import src.ingestion.job_manager as job_manager_mod
import src.analysis.processor as processor_mod
from src.api.routes import search as search_mod
import src.api.routes.export as export_mod

DEV_USER_1 = "test-user-1"
DEV_USER_2 = "test-user-2"


@pytest_asyncio.fixture
async def db_engine():
    """Create an in-memory SQLite engine for tests."""
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest_asyncio.fixture
async def db_session_factory(db_engine):
    """Create a session factory bound to the test engine."""
    return async_sessionmaker(db_engine, class_=AsyncSession, expire_on_commit=False)


@pytest_asyncio.fixture
async def db(db_session_factory) -> AsyncGenerator[AsyncSession, None]:
    async with db_session_factory() as session:
        yield session


@pytest_asyncio.fixture
async def seed_users(db_session_factory):
    """Seed two test users."""
    async with db_session_factory() as session:
        session.add_all([
            User(id=DEV_USER_1, email="user1@test.com", display_name="Test User 1"),
            User(id=DEV_USER_2, email="user2@test.com", display_name="Test User 2"),
        ])
        await session.commit()


@pytest_asyncio.fixture
async def tmp_storage(tmp_path):
    """Provide a temporary storage directory."""
    return str(tmp_path)


@pytest_asyncio.fixture
async def client(db_engine, db_session_factory, seed_users, tmp_storage):
    """Create an httpx AsyncClient wired to a test FastAPI app."""
    from src.api.app import create_app

    # Override dependencies for testing
    test_session_factory = db_session_factory

    async def override_get_db():
        async with test_session_factory() as session:
            yield session

    async def override_get_user():
        return DEV_USER_1

    app = create_app()
    app.dependency_overrides[deps.get_db] = override_get_db
    app.dependency_overrides[deps.get_current_user_id] = override_get_user

    # Override the upload route's file store to use temp dir
    file_store = LocalFileStore(tmp_storage)
    upload_service = UploadService(file_store)
    upload_mod._file_store = file_store
    upload_mod._upload_service = upload_service
    # media.py imports _file_store from upload at module-level, so patch it separately
    original_media_file_store = media_mod._file_store
    media_mod._file_store = file_store

    # Inject mock vision provider (no real API calls in tests)
    from src.analysis.mock_provider import MockVisionProvider
    original_provider = upload_mod._vision_provider
    upload_mod._vision_provider = MockVisionProvider()

    # Inject test-scoped indexing + search services (temp ChromaDB)
    import tempfile as _tf
    from src.search.embedder import Embedder
    from src.search.chromadb_store import ChromaDBVectorStore
    from src.search.indexing_service import IndexingService
    from src.search.search_service import SearchService

    _chroma_tmpdir = _tf.mkdtemp()
    embedder = Embedder()
    vector_store = ChromaDBVectorStore(persist_directory=_chroma_tmpdir, collection_name="test")
    indexing_service = IndexingService(embedder, vector_store)
    search_service = SearchService(embedder, vector_store)

    original_indexing = upload_mod._indexing_service
    original_search = search_mod._search_service
    upload_mod._indexing_service = indexing_service
    search_mod._search_service = search_service

    # Patch module-level async_session so background tasks use the test DB
    original_jm_session = job_manager_mod.async_session
    original_proc_session = processor_mod.async_session
    original_export_session = export_mod.async_session
    job_manager_mod.async_session = db_session_factory
    processor_mod.async_session = db_session_factory
    export_mod.async_session = db_session_factory

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c

    job_manager_mod.async_session = original_jm_session
    processor_mod.async_session = original_proc_session
    export_mod.async_session = original_export_session
    upload_mod._vision_provider = original_provider
    upload_mod._indexing_service = original_indexing
    search_mod._search_service = original_search
    media_mod._file_store = original_media_file_store


@pytest_asyncio.fixture
async def client_user2(db_engine, db_session_factory, seed_users, tmp_storage):
    """A second client authenticated as user 2 (for per-user dedup tests)."""
    from src.api.app import create_app

    test_session_factory = db_session_factory

    async def override_get_db():
        async with test_session_factory() as session:
            yield session

    async def override_get_user():
        return DEV_USER_2

    app = create_app()
    app.dependency_overrides[deps.get_db] = override_get_db
    app.dependency_overrides[deps.get_current_user_id] = override_get_user

    file_store = LocalFileStore(tmp_storage)
    upload_service = UploadService(file_store)
    upload_mod._file_store = file_store
    upload_mod._upload_service = upload_service

    # Inject mock vision provider
    from src.analysis.mock_provider import MockVisionProvider
    original_provider = upload_mod._vision_provider
    upload_mod._vision_provider = MockVisionProvider()

    # Inject test-scoped indexing + search services
    import tempfile as _tf2
    from src.search.embedder import Embedder as _Emb2
    from src.search.chromadb_store import ChromaDBVectorStore as _CVS2
    from src.search.indexing_service import IndexingService as _IS2
    from src.search.search_service import SearchService as _SS2

    _chroma_tmpdir2 = _tf2.mkdtemp()
    _emb2 = _Emb2()
    _vs2 = _CVS2(persist_directory=_chroma_tmpdir2, collection_name="test2")
    _is2 = _IS2(_emb2, _vs2)
    _ss2 = _SS2(_emb2, _vs2)

    original_indexing = upload_mod._indexing_service
    original_search = search_mod._search_service
    upload_mod._indexing_service = _is2
    search_mod._search_service = _ss2

    # Patch module-level async_session so background tasks use the test DB
    original_jm_session = job_manager_mod.async_session
    original_proc_session = processor_mod.async_session
    original_export_session_u2 = export_mod.async_session
    job_manager_mod.async_session = db_session_factory
    processor_mod.async_session = db_session_factory
    export_mod.async_session = db_session_factory

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c

    job_manager_mod.async_session = original_jm_session
    processor_mod.async_session = original_proc_session
    export_mod.async_session = original_export_session_u2
    upload_mod._vision_provider = original_provider
    upload_mod._indexing_service = original_indexing
    search_mod._search_service = original_search


# Test data — real images that Pillow can open (needed for analysis pipeline)
import io
from PIL import Image as PILImage


def _make_image(fmt: str, size: tuple[int, int] = (100, 80), color: str = "red") -> bytes:
    """Create a minimal real image in the given format."""
    img = PILImage.new("RGB", size, color=color)
    buf = io.BytesIO()
    img.save(buf, format=fmt)
    return buf.getvalue()


JPEG_BYTES = _make_image("JPEG")
PNG_BYTES = _make_image("PNG", color="blue")
GIF_BYTES = _make_image("GIF", color="green")
PDF_BYTES = b"%PDF-1.4" + b"\x00" * 100
