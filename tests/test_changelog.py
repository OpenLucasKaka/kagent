from pathlib import Path


def test_changelog_documents_current_release_capabilities():
    readme = Path("README.md").read_text()
    changelog = Path("CHANGELOG.md").read_text()

    assert "CHANGELOG.md" in readme
    assert "0.1.0" in changelog
    assert "LangGraph" in changelog
    assert "continuous iteration" in changelog
