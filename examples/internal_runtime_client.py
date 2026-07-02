#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Dict, Optional

DEFAULT_TIMEOUT_SECONDS = 30.0


class RuntimeClient:
    def __init__(
        self,
        *,
        base_url: str,
        token: str,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.timeout_seconds = timeout_seconds

    def run(
        self,
        *,
        goal: str,
        max_iterations: int,
        idempotency_key: str = "",
        plan: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "goal": goal,
            "max_iterations": max_iterations,
        }
        if plan is not None:
            payload["plan"] = plan
        return self._post_json(
            "/runtime/run",
            payload,
            idempotency_key=idempotency_key,
        )

    def resume(
        self,
        *,
        run_id: str,
        approved_action_ids: list[str],
        max_iterations: int = 1,
    ) -> Dict[str, Any]:
        return self._post_json(
            "/runtime/resume",
            {
                "run_id": run_id,
                "approved_action_ids": approved_action_ids,
                "max_iterations": max_iterations,
            },
        )

    def list_runs(
        self,
        *,
        auth_subject: str = "",
        status: str = "",
        limit: int = 20,
    ) -> Dict[str, Any]:
        query = [f"limit={limit}"]
        if auth_subject:
            query.append("auth_subject=" + urllib.parse.quote(auth_subject))
        if status:
            query.append("status=" + urllib.parse.quote(status))
        return self._get_json("/runtime/runs?" + "&".join(query))

    def approvals(
        self,
        *,
        auth_subject: str = "",
        tool: str = "",
        limit: int = 20,
    ) -> Dict[str, Any]:
        query = [f"limit={limit}"]
        if auth_subject:
            query.append("auth_subject=" + urllib.parse.quote(auth_subject))
        if tool:
            query.append("tool=" + urllib.parse.quote(tool))
        return self._get_json("/runtime/approvals?" + "&".join(query))

    def approval_summary(
        self,
        *,
        auth_subject: str = "",
        tool: str = "",
    ) -> Dict[str, Any]:
        query = []
        if auth_subject:
            query.append("auth_subject=" + urllib.parse.quote(auth_subject))
        if tool:
            query.append("tool=" + urllib.parse.quote(tool))
        suffix = "?" + "&".join(query) if query else ""
        return self._get_json("/runtime/approvals/summary" + suffix)

    def policy(
        self,
        *,
        tool: str = "",
        approval_required: str = "",
    ) -> Dict[str, Any]:
        payload = self._get_json("/runtime/policy")
        if tool or approval_required:
            payload = _filter_policy_payload(
                payload,
                tool=tool,
                approval_required=approval_required,
            )
        return payload

    def summary(
        self,
        *,
        auth_subject: str = "",
        status: str = "",
        tool: str = "",
        has_pending_approval: str = "",
    ) -> Dict[str, Any]:
        query = []
        if auth_subject:
            query.append("auth_subject=" + urllib.parse.quote(auth_subject))
        if status:
            query.append("status=" + urllib.parse.quote(status))
        if tool:
            query.append("tool=" + urllib.parse.quote(tool))
        if has_pending_approval:
            query.append(
                "has_pending_approval="
                + urllib.parse.quote(has_pending_approval)
            )
        suffix = "?" + "&".join(query) if query else ""
        return self._get_json("/runtime/runs/summary" + suffix)

    def _get_json(self, path: str) -> Dict[str, Any]:
        request = urllib.request.Request(
            self.base_url + path,
            headers=self._headers(),
            method="GET",
        )
        return self._open_json(request)

    def _post_json(
        self,
        path: str,
        payload: Dict[str, Any],
        *,
        idempotency_key: str = "",
    ) -> Dict[str, Any]:
        headers = self._headers()
        headers["Content-Type"] = "application/json"
        if idempotency_key:
            headers["Idempotency-Key"] = idempotency_key
        request = urllib.request.Request(
            self.base_url + path,
            data=json.dumps(payload).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        return self._open_json(request)

    def _headers(self) -> Dict[str, str]:
        return {"Authorization": f"Bearer {self.token}"}

    def _open_json(self, request: urllib.request.Request) -> Dict[str, Any]:
        try:
            with urllib.request.urlopen(
                request,
                timeout=self.timeout_seconds,
            ) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            payload = json.loads(exc.read().decode("utf-8"))
            payload["_http_status"] = exc.code
            return payload


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Internal client example for the self-correcting LangGraph runtime. "
            "Set SELF_CORRECTING_CLIENT_BASE_URL and SELF_CORRECTING_CLIENT_TOKEN "
            "or pass --base-url and --token."
        )
    )
    parser.add_argument(
        "--base-url",
        default=os.environ.get("SELF_CORRECTING_CLIENT_BASE_URL", "http://127.0.0.1:8000"),
    )
    parser.add_argument(
        "--token",
        default=os.environ.get("SELF_CORRECTING_CLIENT_TOKEN", ""),
        help="Bearer token for the default or named internal auth_subject.",
    )
    parser.add_argument(
        "--timeout-seconds",
        type=float,
        default=DEFAULT_TIMEOUT_SECONDS,
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    run_parser = subparsers.add_parser("run", help="POST /runtime/run")
    run_parser.add_argument("--goal", required=True)
    run_parser.add_argument("--max-iterations", type=int, default=2)
    run_parser.add_argument("--idempotency-key", default="")
    run_parser.add_argument(
        "--plan-json",
        default="",
        help="Optional deterministic plan JSON for smoke tests or replay.",
    )

    resume_parser = subparsers.add_parser(
        "resume",
        help=(
            "POST /runtime/resume and print audit fields such as "
            "resumed_by_auth_subject when present"
        ),
    )
    resume_parser.add_argument("--run-id", required=True)
    resume_parser.add_argument("--approved-action-id", action="append", required=True)
    resume_parser.add_argument("--max-iterations", type=int, default=1)

    approvals_parser = subparsers.add_parser(
        "approvals",
        help="GET /runtime/approvals",
    )
    approvals_parser.add_argument("--auth-subject", default="")
    approvals_parser.add_argument("--tool", default="")
    approvals_parser.add_argument("--limit", type=int, default=20)

    approval_summary_parser = subparsers.add_parser(
        "approval-summary",
        help="GET /runtime/approvals/summary",
    )
    approval_summary_parser.add_argument("--auth-subject", default="")
    approval_summary_parser.add_argument("--tool", default="")

    policy_parser = subparsers.add_parser(
        "policy",
        help="GET /runtime/policy",
    )
    policy_parser.add_argument(
        "--tool",
        default="",
        help="Filter effective_tool_policy to one runtime tool name.",
    )
    policy_parser.add_argument(
        "--approval-required",
        choices=["true", "false", ""],
        default="",
        help="Filter effective_tool_policy by current approval requirement.",
    )

    list_parser = subparsers.add_parser("list-runs", help="GET /runtime/runs")
    list_parser.add_argument("--auth-subject", default="")
    list_parser.add_argument("--status", default="")
    list_parser.add_argument("--limit", type=int, default=20)

    summary_parser = subparsers.add_parser(
        "summary",
        help="GET /runtime/runs/summary",
    )
    summary_parser.add_argument("--auth-subject", default="")
    summary_parser.add_argument("--status", default="")
    summary_parser.add_argument("--tool", default="")
    summary_parser.add_argument(
        "--has-pending-approval",
        choices=["true", "false", ""],
        default="",
    )

    args = parser.parse_args(argv)
    if not args.token:
        parser.error("--token or SELF_CORRECTING_CLIENT_TOKEN is required")

    client = RuntimeClient(
        base_url=args.base_url,
        token=args.token,
        timeout_seconds=args.timeout_seconds,
    )

    if args.command == "run":
        plan = json.loads(args.plan_json) if args.plan_json else None
        payload = client.run(
            goal=args.goal,
            max_iterations=args.max_iterations,
            idempotency_key=args.idempotency_key,
            plan=plan,
        )
    elif args.command == "resume":
        payload = client.resume(
            run_id=args.run_id,
            approved_action_ids=args.approved_action_id,
            max_iterations=args.max_iterations,
        )
    elif args.command == "approvals":
        payload = client.approvals(
            auth_subject=args.auth_subject,
            tool=args.tool,
            limit=args.limit,
        )
    elif args.command == "approval-summary":
        payload = client.approval_summary(
            auth_subject=args.auth_subject,
            tool=args.tool,
        )
    elif args.command == "policy":
        payload = client.policy(
            tool=args.tool,
            approval_required=args.approval_required,
        )
    elif args.command == "list-runs":
        payload = client.list_runs(
            auth_subject=args.auth_subject,
            status=args.status,
            limit=args.limit,
        )
    else:
        payload = client.summary(
            auth_subject=args.auth_subject,
            status=args.status,
            tool=args.tool,
            has_pending_approval=args.has_pending_approval,
        )

    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


def _filter_policy_payload(
    payload: Dict[str, Any],
    *,
    tool: str,
    approval_required: str,
) -> Dict[str, Any]:
    filtered = dict(payload)
    tool_policy = payload.get("effective_tool_policy", [])
    if isinstance(tool_policy, list):
        filtered["effective_tool_policy"] = [
            item
            for item in tool_policy
            if isinstance(item, dict)
            and (not tool or item.get("name") == tool)
            and (
                not approval_required
                or item.get("approval_required") == approval_required
            )
        ]
    filtered["effective_tool_policy_filter"] = {
        "tool": tool,
        "approval_required": approval_required,
    }
    return filtered


if __name__ == "__main__":
    sys.exit(main())
