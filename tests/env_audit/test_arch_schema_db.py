from pathlib import Path

from .arch_builders import isolated_runtime
from .schema_check import validate


def _arch(result, root: Path) -> dict:
    assert result.rc == 0, result.stdout
    return result.data["sections"]["architecture"][str(root.resolve())]


def _revision(index: int) -> str:
    previous = "None" if index == 1 else repr(f"r{index - 1}")
    return f"revision = 'r{index}'\ndown_revision = {previous}\n"


def test_a4_create_all_in_lifespan(tmp_path: Path, run_collect) -> None:
    root = tmp_path / "alembic-app"
    versions = root / "migrations" / "versions"
    versions.mkdir(parents=True)
    (root / "alembic.ini").write_text(
        "[alembic]\nscript_location = migrations\n", encoding="utf-8"
    )
    for index in range(1, 7):
        (versions / f"r{index}.py").write_text(_revision(index), encoding="utf-8")
    (root / "app.py").write_text(
        "async def lifespan(app):\n"
        "    init_db()\n"
        "    yield\n\n"
        "def init_db():\n"
        "    try:\n"
        "        Base.metadata.create_all(bind=engine)\n"
        "    except Exception:\n"
        "        pass\n",
        encoding="utf-8",
    )
    (root / "Dockerfile").write_text(
        "FROM python:3\nCMD python app.py\n", encoding="utf-8"
    )

    arch = _arch(run_collect("--only", "architecture", "--root", root), root)
    schema = arch["schema_db"]

    assert schema["create_all_sites"][0]["in_startup"] is True
    assert arch["rule_inputs"]["A4"]["revisions"] == 6
    assert schema["upgrade_invocations"] == []
    assert arch["rule_inputs"]["A4"]["swallowed"] == 1


def test_a4_alembic_annotated_revisions(tmp_path: Path, run_collect) -> None:
    root = tmp_path / "annotated-alembic"
    versions = root / "migrations" / "versions"
    versions.mkdir(parents=True)
    (root / "alembic.ini").write_text(
        "[alembic]\nscript_location = migrations\n", encoding="utf-8"
    )
    for index in range(1, 7):
        previous = "None" if index == 1 else repr(f"r{index - 1}")
        (versions / f"r{index}.py").write_text(
            f"revision: str = 'r{index}'\n"
            f"down_revision: Union[str, None] = {previous}\n",
            encoding="utf-8",
        )

    arch = _arch(run_collect("--only", "architecture", "--root", root), root)

    assert arch["rule_inputs"]["A4"]["revisions"] == 6


def test_a4_run_sync_ref(tmp_path: Path, run_collect) -> None:
    root = tmp_path / "sync-ref"
    root.mkdir()
    (root / "app.py").write_text(
        "def init(conn):\n"
        "    conn.run_sync(Base.metadata.create_all)\n",
        encoding="utf-8",
    )

    arch = _arch(run_collect("--only", "architecture", "--root", root), root)

    assert arch["schema_db"]["create_all_sites"][0]["kind"] == "ref"


def test_a4_django_migrate_service(tmp_path: Path, run_collect) -> None:
    root = tmp_path / "django"
    migrations = root / "shop" / "migrations"
    migrations.mkdir(parents=True)
    body = (
        "from django.db import migrations\n"
        "class Migration(migrations.Migration):\n"
        "    dependencies = []\n"
        "    operations = []\n"
    )
    (migrations / "0005_first.py").write_text(body, encoding="utf-8")
    (migrations / "0005_second.py").write_text(body, encoding="utf-8")
    (migrations / "0006_merge.py").write_text(body, encoding="utf-8")
    (root / "docker-compose.yml").write_text(
        "services:\n"
        "  migrate:\n"
        "    image: app\n"
        "    command: python manage.py migrate\n",
        encoding="utf-8",
    )

    arch = _arch(run_collect("--only", "architecture", "--root", root), root)
    schema = arch["schema_db"]
    django = next(item for item in schema["migration_dirs"] if item["tool"] == "django")

    assert schema["upgrade_invocations"]
    assert django["duplicate_numbers"] == ["0005"]
    assert django["merge_migrations"] == 1


def test_a4_sql_vs_orm_tables(tmp_path: Path, run_collect) -> None:
    root = tmp_path / "tables"
    root.mkdir()
    (root / "models.py").write_text(
        "class One(Base):\n"
        "    __tablename__ = 'one'\n\n"
        "class Two(Base):\n"
        "    __tablename__ = 'two'\n\n"
        "class Three(Base):\n"
        "    __tablename__ = 'three'\n",
        encoding="utf-8",
    )
    (root / "schema.sql").write_text(
        "CREATE TABLE one (id INTEGER);\n"
        "CREATE TABLE two (id INTEGER);\n",
        encoding="utf-8",
    )

    arch = _arch(run_collect("--only", "architecture", "--root", root), root)

    assert arch["schema_db"]["orm_only"] == ["three"]


def test_schema_valid(tmp_path: Path, run_collect) -> None:
    root = tmp_path / "schema"
    root.mkdir()
    (root / "app.py").write_text(
        "def lifespan(app):\n"
        "    Base.metadata.create_all()\n",
        encoding="utf-8",
    )
    (root / "init.sql").write_text(
        "CREATE TABLE sample (id INTEGER);\n", encoding="utf-8"
    )

    result = run_collect("--only", "architecture", "--root", root)

    validate(result.data)
