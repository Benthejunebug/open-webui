import logging
import os
import time

import tempfile
from typing import Optional

import docker
from docker import DockerClient
from pytest_docker.plugin import get_docker_ip
from fastapi.testclient import TestClient
from sqlalchemy import text, create_engine


log = logging.getLogger(__name__)


def get_fast_api_client():
    from main import app

    with TestClient(app) as c:
        return c


class AbstractIntegrationTest:
    BASE_PATH = None

    def create_url(self, path="", query_params=None):
        if self.BASE_PATH is None:
            raise Exception("BASE_PATH is not set")
        parts = self.BASE_PATH.split("/")
        parts = [part.strip() for part in parts if part.strip() != ""]
        path_parts = path.split("/")
        path_parts = [part.strip() for part in path_parts if part.strip() != ""]
        query_parts = ""
        if query_params:
            query_parts = "&".join(
                [f"{key}={value}" for key, value in query_params.items()]
            )
            query_parts = f"?{query_parts}"
        return "/".join(parts + path_parts) + query_parts

    @classmethod
    def setup_class(cls):
        pass

    def setup_method(self):
        pass

    @classmethod
    def teardown_class(cls):
        pass

    def teardown_method(self):
        pass


class AbstractPostgresTest(AbstractIntegrationTest):
    DOCKER_CONTAINER_NAME = "postgres-test-container-will-get-deleted"
    docker_client: Optional[DockerClient] = None
    using_sqlite: bool = False
    _sqlite_db_path: Optional[str] = None

    @classmethod
    def _create_db_url(cls, env_vars_postgres: dict) -> str:
        host = get_docker_ip()
        user = env_vars_postgres["POSTGRES_USER"]
        pw = env_vars_postgres["POSTGRES_PASSWORD"]
        port = 8081
        db = env_vars_postgres["POSTGRES_DB"]
        return f"postgresql://{user}:{pw}@{host}:{port}/{db}"

    @classmethod
    def setup_class(cls):
        super().setup_class()
        try:
            cls._setup_postgres()
        except Exception as ex:
            log.warning(
                "Falling back to SQLite test database because Postgres setup failed: %s",
                ex,
            )
            cls._cleanup_docker_container()
            cls._setup_sqlite()

    @classmethod
    def _setup_postgres(cls):
        try:
            env_vars_postgres = {
                "POSTGRES_USER": "user",
                "POSTGRES_PASSWORD": "example",
                "POSTGRES_DB": "openwebui",
            }
            cls.docker_client = docker.from_env()
            cls.docker_client.containers.run(
                "postgres:16.2",
                detach=True,
                environment=env_vars_postgres,
                name=cls.DOCKER_CONTAINER_NAME,
                ports={5432: ("0.0.0.0", 8081)},
                command="postgres -c log_statement=all",
            )
            time.sleep(0.5)

            database_url = cls._create_db_url(env_vars_postgres)
            os.environ["DATABASE_URL"] = database_url
            retries = 10
            db = None
            while retries > 0:
                try:
                    from open_webui.config import OPEN_WEBUI_DIR

                    db = create_engine(database_url, pool_pre_ping=True)
                    db = db.connect()
                    log.info("postgres is ready!")
                    break
                except Exception as e:
                    log.warning(e)
                    time.sleep(3)
                    retries -= 1

            if db:
                # import must be after setting env!
                cls.fast_api_client = get_fast_api_client()
                db.close()
            else:
                raise Exception("Could not connect to Postgres")
        except Exception:
            raise

    @classmethod
    def _setup_sqlite(cls):
        fd, path = tempfile.mkstemp(prefix="openwebui-test-", suffix=".db")
        os.close(fd)
        database_url = f"sqlite:///{path}"
        os.environ["DATABASE_URL"] = database_url
        os.environ.setdefault("OFFLINE_MODE", "true")
        os.environ.setdefault("HF_HUB_OFFLINE", "1")
        snapshot_stub_path = tempfile.gettempdir()
        try:
            import huggingface_hub

            def _snapshot_download_stub(*args, **kwargs):
                return snapshot_stub_path

            huggingface_hub.snapshot_download = _snapshot_download_stub
        except Exception:
            pass

        try:
            import open_webui.retrieval.utils as retrieval_utils

            def _retrieval_snapshot_stub(*args, **kwargs):
                return snapshot_stub_path

            retrieval_utils.snapshot_download = _retrieval_snapshot_stub
        except Exception:
            pass
        cls.using_sqlite = True
        cls._sqlite_db_path = path
        cls.fast_api_client = get_fast_api_client()

    @classmethod
    def _cleanup_docker_container(cls):
        if cls.docker_client:
            try:
                cls.docker_client.containers.get(cls.DOCKER_CONTAINER_NAME).remove(
                    force=True
                )
            except Exception:
                pass
        cls.docker_client = None

    def _check_db_connection(self):
        from open_webui.internal.db import Session

        retries = 10
        while retries > 0:
            try:
                Session.execute(text("SELECT 1"))
                Session.commit()
                break
            except Exception as e:
                Session.rollback()
                log.warning(e)
                time.sleep(3)
                retries -= 1

    def setup_method(self):
        super().setup_method()
        self._check_db_connection()

    @classmethod
    def teardown_class(cls) -> None:
        super().teardown_class()
        cls._cleanup_docker_container()
        if cls.using_sqlite and cls._sqlite_db_path:
            try:
                os.remove(cls._sqlite_db_path)
            except OSError:
                pass
            cls._sqlite_db_path = None
        cls.docker_client = None

    def teardown_method(self):
        from open_webui.internal.db import Session

        # rollback everything not yet committed
        Session.commit()

        # truncate all tables
        tables = [
            "auth",
            "chat",
            "chatidtag",
            "document",
            "memory",
            "model",
            "prompt",
            "tag",
            '"user"',
            "note",
        ]
        for table in tables:
            if self.using_sqlite:
                Session.execute(text(f"DELETE FROM {table}"))
            else:
                Session.execute(text(f"TRUNCATE TABLE {table}"))
        Session.commit()
