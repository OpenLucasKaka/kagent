from pathlib import Path


def test_makefile_exposes_standard_developer_targets():
    makefile = Path("Makefile").read_text()

    assert "check:" in makefile
    assert "test:" in makefile
    assert "lint:" in makefile
    assert "eval:" in makefile
    assert "clean:" in makefile
    assert "smoke-service:" in makefile
    assert "readiness-audit:" in makefile
    assert "wheel:" in makefile
    assert "docker-build:" in makefile
    assert "scripts/run_checks.sh" in makefile
    assert "scripts/smoke_service.sh" in makefile
    assert "scripts/production_readiness_audit.py" in makefile
    assert "scripts/production_approval_bundle.sh --strict" in makefile
    assert "PYTHONWARNINGS=ignore" in makefile
    assert "rm -rf build dist" in makefile
    assert "rm -rf build dist .pytest_cache .ruff_cache *.egg-info src/*.egg-info" in makefile


def test_makefile_wheel_target_matches_release_gate():
    makefile = Path("Makefile").read_text()

    assert "--no-build-isolation" in makefile
    assert "self_correcting_langgraph_agent-0.1.0-*.whl" in makefile
