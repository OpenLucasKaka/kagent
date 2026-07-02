from pathlib import Path


def test_package_declares_inline_type_information():
    pyproject = Path("pyproject.toml").read_text()

    assert Path("src/self_correcting_langgraph_agent/py.typed").exists()
    assert "self_correcting_langgraph_agent = [\"py.typed\"]" in pyproject


def test_pytest_filters_known_local_ssl_warning_noise():
    pyproject = Path("pyproject.toml").read_text()

    assert "NotOpenSSLWarning" in pyproject


def test_dev_dependencies_include_wheel_builder():
    pyproject = Path("pyproject.toml").read_text()

    assert '"setuptools>=61"' in pyproject
    assert '"wheel>=0.45,<1"' in pyproject


def test_build_system_declares_wheel_builder():
    pyproject = Path("pyproject.toml").read_text()

    assert 'requires = ["setuptools>=61", "wheel>=0.45,<1"]' in pyproject


def test_package_declares_batch_console_script():
    pyproject = Path("pyproject.toml").read_text()

    assert (
        'self-correcting-agent-batch = "self_correcting_langgraph_agent.ops.batch:main"'
        in pyproject
    )


def test_package_declares_service_console_script():
    pyproject = Path("pyproject.toml").read_text()

    assert (
        'self-correcting-agent-serve = "self_correcting_langgraph_agent.service:main"'
        in pyproject
    )


def test_package_declares_trace_prune_console_script():
    pyproject = Path("pyproject.toml").read_text()

    assert (
        'self-correcting-agent-trace-prune = '
        '"self_correcting_langgraph_agent.service.trace_store:main"'
    ) in pyproject


def test_package_declares_trace_replay_console_script():
    pyproject = Path("pyproject.toml").read_text()

    assert (
        'self-correcting-agent-trace-replay = '
        '"self_correcting_langgraph_agent.ops.trace_replay:main"'
    ) in pyproject


def test_package_declares_doctor_console_script():
    pyproject = Path("pyproject.toml").read_text()

    assert (
        'self-correcting-agent-doctor = "self_correcting_langgraph_agent.ops.doctor:main"'
        in pyproject
    )


def test_package_declares_release_manifest_console_script():
    pyproject = Path("pyproject.toml").read_text()

    assert (
        'self-correcting-agent-release-manifest = '
        '"self_correcting_langgraph_agent.ops.release_manifest:main"'
    ) in pyproject


def test_package_declares_release_evidence_console_script():
    pyproject = Path("pyproject.toml").read_text()

    assert (
        'self-correcting-agent-release-evidence = '
        '"self_correcting_langgraph_agent.ops.release_evidence:main"'
    ) in pyproject
