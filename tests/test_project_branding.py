from pathlib import Path

LEGACY_BRAND_PATTERNS = (
    "SelfCorrectingAgent",
    "Self-correcting",
    "self-correcting",
    "self_correcting",
    "SELF_CORRECTING",
)

TEXT_FILE_SUFFIXES = {
    ".cfg",
    ".css",
    ".dockerignore",
    ".env",
    ".example",
    ".html",
    ".ini",
    ".json",
    ".lock",
    ".md",
    ".py",
    ".sh",
    ".toml",
    ".txt",
    ".yaml",
    ".yml",
}

IGNORED_PARTS = {
    ".git",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    "__pycache__",
    "build",
    "dist",
}


def _iter_project_text_files(root: Path):
    for path in root.rglob("*"):
        if any(part in IGNORED_PARTS for part in path.parts):
            continue
        if not path.is_file():
            continue
        if path.name == "test_project_branding.py":
            continue
        if path.name in {"uv.lock", "Makefile", "Dockerfile"} or path.suffix in TEXT_FILE_SUFFIXES:
            yield path


def test_project_uses_kagent_branding_only():
    findings: list[str] = []
    root = Path(".")

    for path in _iter_project_text_files(root):
        text = path.read_text(errors="ignore")
        for pattern in LEGACY_BRAND_PATTERNS:
            if pattern in text:
                findings.append(f"{path}:{pattern}")

    assert findings == []
