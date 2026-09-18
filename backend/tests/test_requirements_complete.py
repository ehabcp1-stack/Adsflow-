"""Every third-party import must be declared in requirements.txt.

This is the check that a green test suite cannot make for you. Tests run in a
development environment where the missing package is already installed for some
other reason, so the suite passes, the image builds, the deploy reports success
— and the container dies on its first import. It cost two failed deploys to
find that Pillow, fontTools, arabic-reshaper and python-bidi were all used by
the caption engine and none of them were declared.
"""
from __future__ import annotations

import ast
import pathlib
import sys

APP = pathlib.Path(__file__).resolve().parent.parent / "app"
REQUIREMENTS = pathlib.Path(__file__).resolve().parent.parent / "requirements.txt"

#: Import name -> distribution name, where the two differ.
DISTRIBUTION = {
    "PIL": "pillow",
    "fontTools": "fonttools",
    "jose": "python-jose",
    "bidi": "python-bidi",
    "arabic_reshaper": "arabic-reshaper",
    "dotenv": "python-dotenv",
    "multipart": "python-multipart",
    "pydantic_settings": "pydantic-settings",
    "dateutil": "python-dateutil",
    "yaml": "pyyaml",
}

#: Packages that arrive as a dependency of something declared, and are imported
#: directly. Kept explicit so the list is a decision, not an accident.
TRANSITIVE_BUT_USED = {
    "starlette",
    "anyio",
    # boto3's own dependency, pinned by it. `storage.py` imports
    # `botocore.config.Config` directly to bound S3 timeouts and retries —
    # botocore's defaults are 60s/60s with five attempts, which is five
    # minutes per object and was the whole of "the analysis never finishes".
    "botocore",
}

LOCAL = {"app", "scripts", "tests", "alembic"}


def _top_level_imports(root: pathlib.Path) -> dict[str, set[str]]:
    found: dict[str, set[str]] = {}
    for path in root.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    found.setdefault(alias.name.split(".")[0], set()).add(path.name)
            elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
                found.setdefault(node.module.split(".")[0], set()).add(path.name)
    return found


def _declared() -> set[str]:
    names: set[str] = set()
    for line in REQUIREMENTS.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        # "package[extra]==1.2.3" -> "package"
        name = line.split("==")[0].split(">=")[0].split("[")[0].strip()
        names.add(name.lower().replace("_", "-"))
    return names


def test_every_third_party_import_is_declared():
    declared = _declared()
    missing = []
    for module, files in sorted(_top_level_imports(APP).items()):
        if module in sys.stdlib_module_names or module in LOCAL:
            continue
        if module in TRANSITIVE_BUT_USED:
            continue
        dist = DISTRIBUTION.get(module, module).lower().replace("_", "-")
        if dist not in declared:
            missing.append(f"{module} (pip install {dist}) used in {sorted(files)[:3]}")
    assert not missing, (
        "these are imported by app/ but not in requirements.txt, so the image "
        "will build and then die on boot:\n  " + "\n  ".join(missing)
    )


def test_the_arabic_rendering_stack_is_declared():
    """Named explicitly: these four are what make Arabic captions correct.

    They are easy to lose in a dependency cleanup because nothing else in the
    file hints at what they are for.
    """
    declared = _declared()
    for package in ("pillow", "fonttools", "arabic-reshaper", "python-bidi"):
        assert package in declared, f"{package} must stay in requirements.txt"


def test_a_postgres_driver_is_declared():
    """`DATABASE_URL` must name the driver that is actually installed.

    The image ships psycopg 3, so a URL written as `postgresql+psycopg2://`
    resolves to a driver that is not there — a deploy that looks successful and
    answers 502.
    """
    declared = _declared()
    assert "psycopg" in declared or "psycopg2-binary" in declared
