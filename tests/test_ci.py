from pathlib import Path


def test_github_actions_ci_runs_standard_check_script():
    workflow_path = Path(".github/workflows/ci.yml")
    workflow = workflow_path.read_text()

    assert workflow_path.exists()
    assert "scripts/run_checks.sh" in workflow
    assert "pip install -e '.[dev]'" in workflow


def test_github_actions_ci_uses_minimal_permissions():
    workflow = Path(".github/workflows/ci.yml").read_text()

    assert "permissions:" in workflow
    assert "contents: read" in workflow


def test_github_actions_ci_runs_python_version_matrix():
    workflow = Path(".github/workflows/ci.yml").read_text()

    assert "matrix:" in workflow
    assert "python-version: [\"3.9\", \"3.12\"]" in workflow
    assert "python-version: ${{ matrix.python-version }}" in workflow


def test_github_actions_ci_has_job_timeout():
    workflow = Path(".github/workflows/ci.yml").read_text()

    assert "timeout-minutes:" in workflow


def test_github_actions_ci_uploads_wheel_artifact():
    workflow = Path(".github/workflows/ci.yml").read_text()

    assert "actions/upload-artifact" in workflow
    assert "self-correcting-agent-wheel-${{ matrix.python-version }}" in workflow
    assert "/tmp/self-correcting-agent-wheelhouse" in workflow
    assert "retention-days: 14" in workflow


def test_github_actions_ci_uploads_release_manifest_artifact():
    workflow = Path(".github/workflows/ci.yml").read_text()

    assert "self-correcting-agent-release-manifest-${{ matrix.python-version }}" in workflow
    assert "/tmp/self-correcting-agent-release-manifest.json" in workflow
    assert "if-no-files-found: error" in workflow
    assert workflow.count("retention-days: 14") == 2


def test_dependabot_tracks_python_and_github_actions_dependencies():
    dependabot_path = Path(".github/dependabot.yml")
    dependabot = dependabot_path.read_text()

    assert dependabot_path.exists()
    assert 'package-ecosystem: "pip"' in dependabot
    assert 'package-ecosystem: "github-actions"' in dependabot
    assert "interval: weekly" in dependabot
