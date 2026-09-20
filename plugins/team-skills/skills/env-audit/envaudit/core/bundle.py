from pathlib import Path


def _module_name(package_dir: Path, source: Path) -> tuple[str, bool]:
    relative = source.relative_to(package_dir)
    is_package = relative.name == "__init__.py"
    parts = relative.parts[:-1] if is_package else (*relative.parts[:-1], source.stem)
    suffix = ".".join(parts)
    return ("envaudit" + (f".{suffix}" if suffix else ""), is_package)


def build_bundle() -> str:
    package_dir = Path(__file__).resolve().parent.parent
    sources = {
        name: (path.read_text(encoding="utf-8"), is_package)
        for path in sorted(package_dir.rglob("*.py"))
        for name, is_package in (_module_name(package_dir, path),)
    }
    data_dir = package_dir / "data"
    data = {
        path.relative_to(data_dir).as_posix(): path.read_text(encoding="utf-8")
        for path in sorted(data_dir.rglob("*"))
        if path.is_file() and path.name != ".keep"
    }
    return f'''import importlib.abc
import importlib.util
import sys

SOURCES = {sources!r}
DATA = {data!r}
PATH_PREFIX = "<env-audit-bundle:"


class BundleImporter(importlib.abc.MetaPathFinder, importlib.abc.Loader):
    def find_spec(self, fullname, path=None, target=None):
        item = SOURCES.get(fullname)
        if item is None:
            return None
        spec = importlib.util.spec_from_loader(fullname, self, is_package=item[1])
        if item[1]:
            spec.submodule_search_locations = [PATH_PREFIX + fullname + ">"]
        return spec

    def create_module(self, spec):
        return None

    def exec_module(self, module):
        source, _ = SOURCES[module.__name__]
        exec(compile(source, "<bundle>/" + module.__name__.replace(".", "/") + ".py", "exec"), module.__dict__)


class BundlePathFinder(importlib.abc.PathEntryFinder):
    def __init__(self, package):
        self.package = package

    def iter_modules(self, prefix=""):
        base = self.package + "."
        for name, (_, is_package) in sorted(SOURCES.items()):
            if name.startswith(base) and "." not in name[len(base):]:
                yield prefix + name[len(base):], is_package


def bundle_path_hook(path):
    if path.startswith(PATH_PREFIX) and path.endswith(">"):
        return BundlePathFinder(path[len(PATH_PREFIX):-1])
    raise ImportError


sys.dont_write_bytecode = True
sys.meta_path.insert(0, BundleImporter())
sys.path_hooks.insert(0, bundle_path_hook)
sys.path_importer_cache.clear()

from envaudit.core import resources
resources.BUNDLED_DATA = DATA
from envaudit.core.cli import main
sys.exit(main(sys.argv[1:]))
'''
