import importlib
import shutil
import subprocess
import sys
from contextlib import contextmanager
from pathlib import Path

from setuptools import find_packages


REPO_ROOT = Path(__file__).resolve().parents[1]
SMOKE_MODULES = (
    "clm.analysis.summary",
    "clm.monitoring",
    "clm.runtimes",
    "clm.migration.traffic",
)


def _packages_from_init_files() -> set[str]:
    packages = set()
    for init_file in (REPO_ROOT / "clm").rglob("__init__.py"):
        relative_package = init_file.parent.relative_to(REPO_ROOT).parts
        packages.add(".".join(relative_package))
    return packages


def test_setuptools_discovery_matches_clm_package_init_files():
    discovered = set(find_packages(where=str(REPO_ROOT), include=["clm*"]))

    assert discovered == _packages_from_init_files()


def test_build_output_contains_and_imports_packaged_smoke_modules(tmp_path):
    project_root = tmp_path / "project"
    _copy_build_inputs(project_root)

    build_lib = project_root / "build_lib"
    subprocess.run(
        [
            sys.executable,
            "-c",
            "from setuptools import setup; setup()",
            "build_py",
            "--build-lib",
            str(build_lib),
        ],
        cwd=project_root,
        check=True,
        capture_output=True,
        text=True,
    )

    for module_name in SMOKE_MODULES:
        assert (build_lib / Path(*module_name.split(".")).with_suffix(".py")).exists() or (
            build_lib / Path(*module_name.split(".")) / "__init__.py"
        ).exists()

    with _imports_from_build_output(build_lib):
        for module_name in SMOKE_MODULES:
            module = importlib.import_module(module_name)
            assert str(module.__file__).startswith(str(build_lib))


def _copy_build_inputs(project_root: Path) -> None:
    project_root.mkdir()
    shutil.copy2(REPO_ROOT / "pyproject.toml", project_root / "pyproject.toml")
    shutil.copy2(REPO_ROOT / "README.md", project_root / "README.md")
    shutil.copytree(
        REPO_ROOT / "clm",
        project_root / "clm",
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
    )


@contextmanager
def _imports_from_build_output(build_lib: Path):
    saved_modules = {
        name: module
        for name, module in sys.modules.items()
        if name == "clm" or name.startswith("clm.")
    }
    original_path = list(sys.path)
    _purge_clm_modules()
    sys.path.insert(0, str(build_lib))
    try:
        yield
    finally:
        _purge_clm_modules()
        sys.modules.update(saved_modules)
        sys.path[:] = original_path


def _purge_clm_modules() -> None:
    for name in [name for name in sys.modules if name == "clm" or name.startswith("clm.")]:
        del sys.modules[name]
