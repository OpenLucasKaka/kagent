from kagent.runtime.redaction import redact_runtime_payload, redact_runtime_text


def test_runtime_redaction_covers_environment_and_github_credentials():
    source = "\n".join(
        [
            "AWS_SECRET_ACCESS_KEY=very-secret-aws-value",
            '"GITHUB_TOKEN": "github-secret-value"',
            "client_secret: oauth-secret-value",
            "github_pat_abcdefghijklmnopqrstuvwxyz123456",
        ]
    )

    redacted = redact_runtime_text(source)

    for secret in (
        "very-secret-aws-value",
        "github-secret-value",
        "oauth-secret-value",
        "github_pat_abcdefghijklmnopqrstuvwxyz123456",
    ):
        assert secret not in redacted
    assert redacted.count("[REDACTED]") == 4


def test_runtime_redaction_removes_multiline_private_keys_from_nested_payloads():
    private_key = (
        "-----BEGIN PRIVATE KEY-----\n"
        "sensitive-key-material\n"
        "-----END PRIVATE KEY-----"
    )

    payload = redact_runtime_payload({"stdout": private_key, "items": [private_key]})

    assert payload == {"stdout": "[REDACTED]", "items": ["[REDACTED]"]}
