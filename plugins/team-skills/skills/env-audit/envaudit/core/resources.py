from pathlib import Path


BUNDLED_DATA: dict[str, str] | None = None


def read_data(name: str) -> str | None:
    if BUNDLED_DATA is not None:
        return BUNDLED_DATA.get(name)
    try:
        return (Path(__file__).parent.parent / "data" / name).read_text(encoding="utf-8")
    except OSError:
        return None
