# LLM planner loop: chooses screening tools without changing deterministic scores.
from __future__ import annotations

import argparse
import asyncio
import json
import re
from pathlib import Path
from typing import Any, Callable

ALLOWED_TOOLS = ("run_screening", "resume_run", "ask_user", "get_run_status", "finish")
ALLOWED_MISSING = ("jd", "candidates", "position")
TERMINAL_STATUSES = {"success", "need_input", "error"}
_EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
_PATH_RE = re.compile(r"(?:[A-Za-z]:)?(?:/|\\)[^\s]{8,}")
_planner_llm_client: Any = None

SYSTEM_PROMPT = """You are the screening-job planner for a CV screening system.
Choose exactly one tool per turn. Scoring and ranking are NEVER yours to change.

Tools:
- run_screening: run the full L1 screening pipeline with the CLI-provided JD/CVs. Prefer this when inputs look complete. Never resumes artifacts.
- resume_run: retry the same run, reusing artifacts in output_dir. Use after partial_success with retryable failures.
- get_run_status: read agent-state.json for the current output_dir.
- ask_user: stop and ask for missing JD, CVs, position, or other required input. Use when files/refs are missing.
- finish: stop and return the latest screening result, including a prior agent-state.json in output_dir.

Rules:
- Return one JSON object: {"tool": "<name>", "arguments": {}, "reason": "<short>"}.
- Do not invent file paths, API keys, or scores. Tool arguments are optional; run_screening/resume_run ignore extra keys.
- ask_user arguments: {"missing": ["jd"|"candidates"|"position"], "questions": ["..."]}.
- After success or need_input, call finish (the runtime may stop earlier).
- Never request weight/score edits.
"""


# Redacts emails/paths and truncates text before it is sent to the planner LLM.
def _sanitize_text(value: Any, limit: int = 80) -> str:
    text = _EMAIL_RE.sub("[redacted]", str(value or ""))
    text = _PATH_RE.sub("[path]", text)
    return text[:limit]


# Builds a compact snapshot of CLI inputs for the planner (no secrets or full paths).
def _input_snapshot(args: argparse.Namespace) -> dict[str, Any]:
    return {
        "has_jd_file": bool(args.jd_file),
        "has_jd_json": bool(args.jd_json),
        "has_polyu_ref": bool(args.polyu_ref),
        "cv_count": len(args.cv or []),
        "extracted_count": len(args.extracted or []),
        "has_position": bool(args.position),
        "engine": args.engine,
        "skip_reports": bool(args.skip_reports),
        "cli_resume": bool(args.resume),
        "goal": _sanitize_text(args.goal, 200) if args.goal else None,
    }


# Shrinks a screening-agent envelope so the planner context stays small and de-identified.
def _compact_payload(payload: dict[str, Any] | None) -> dict[str, Any]:
    if not payload:
        return {}
    result = payload.get("result") if isinstance(payload.get("result"), dict) else payload
    failures = result.get("failures") or payload.get("failures") or []
    compact_failures = []
    for item in failures[:8]:
        if not isinstance(item, dict):
            continue
        compact_failures.append(
            {
                "source": item.get("source"),
                "stage": item.get("stage"),
                "error_message": _sanitize_text(item.get("error_message")),
            }
        )
    ask = payload.get("ask") if payload.get("ask") is not None else result.get("ask")
    if isinstance(ask, dict):
        ask = {
            "missing": ask.get("missing"),
            "questions": [_sanitize_text(q, 120) for q in (ask.get("questions") or [])[:6]],
        }
    return {
        "status": payload.get("status") or result.get("status"),
        "ask": ask,
        "candidates_count": len(result.get("candidates") or payload.get("candidates") or []),
        "failures": compact_failures,
        "runs": len(payload.get("runs") or []),
        "error_message": _sanitize_text(payload.get("error_message") or result.get("error_message")),
    }


# Reads persisted L1 agent state if present.
def _read_agent_state(output_dir: Path) -> dict[str, Any]:
    path = output_dir / "agent-state.json"
    if not path.is_file():
        return {"status": "empty", "message": "no agent-state.json yet"}
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError:
        return {"status": "error", "error_message": "agent-state.json is not valid JSON"}
    return {
        "status": data.get("status"),
        "round": data.get("round"),
        "retry_decision": data.get("retry_decision"),
        "runs": len(data.get("runs") or []),
    }


# Rebuilds a screening envelope from disk so finish can reuse a prior L1 run.
def _payload_from_agent_state(output_dir: Path) -> dict[str, Any] | None:
    path = output_dir / "agent-state.json"
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError:
        return None
    status = str(data.get("status") or "")
    if status in {"", "empty"}:
        return None
    runs = data.get("runs") if isinstance(data.get("runs"), list) else []
    last_run = runs[-1] if runs and isinstance(runs[-1], dict) else {}
    last = last_run.get("payload") if isinstance(last_run.get("payload"), dict) else {}
    result = last or {"status": status, "retry_decision": data.get("retry_decision")}
    return {
        "status": status,
        "output_dir": str(output_dir),
        "runs": runs,
        "result": result,
        "ask": result.get("ask") if isinstance(result, dict) else None,
        "from_agent_state": True,
    }


# Restricts ask_user missing keys to the host contract.
def _normalize_ask(arguments: dict[str, Any]) -> tuple[list[str], list[str]]:
    raw = arguments.get("missing") or []
    if isinstance(raw, str):
        raw = [raw]
    if not isinstance(raw, list):
        raw = []
    missing = [str(item) for item in raw if str(item) in ALLOWED_MISSING]
    if not missing:
        missing = ["input"]
    questions = arguments.get("questions") or ["Provide the missing screening inputs."]
    if isinstance(questions, str):
        questions = [questions]
    if not isinstance(questions, list) or not questions:
        questions = ["Provide the missing screening inputs."]
    clipped = [_sanitize_text(item, 240) for item in questions[:6] if str(item).strip()]
    return missing, clipped or ["Provide the missing screening inputs."]


# Parses and validates one planner JSON action.
def _parse_action(parsed: dict[str, Any]) -> dict[str, Any]:
    tool = str(parsed.get("tool") or "").strip()
    if tool not in ALLOWED_TOOLS:
        raise ValueError(f"unsupported tool: {tool or parsed}")
    arguments = parsed.get("arguments") or {}
    if not isinstance(arguments, dict):
        arguments = {}
    return {"tool": tool, "arguments": arguments, "reason": str(parsed.get("reason") or "")}


# Flattens nested HTTP/SSL exceptions into a single planner error string.
def _format_planner_error(exc: BaseException) -> str:
    parts: list[str] = []
    current: BaseException | None = exc
    seen: set[int] = set()
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        text = str(current).strip() or type(current).__name__
        if text not in parts:
            parts.append(text)
        current = current.__cause__ or current.__context__
    message = " | ".join(parts)
    lowered = message.lower()
    if "certificate" in lowered or "ssl" in lowered:
        message += (
            " Hint: --planner llm must reach Zhipu; the SDK uses httpx. "
            "Use --planner rules to stay offline with --extracted samples."
        )
    elif "connection error" in lowered:
        message += " Hint: planner LLM call failed before screening. Check LLM_BASE_URL / network, or use --planner rules."
    return message


# Returns a process-wide LLM client so planner turns reuse one HTTP session.
def _planner_client() -> Any:
    global _planner_llm_client
    if _planner_llm_client is None:
        from screening_core.llm_client import LLMClient

        _planner_llm_client = LLMClient()
    return _planner_llm_client


# Calls Zhipu via the shared LLMClient and returns parsed JSON.
def _default_complete_json(system_prompt: str, user_prompt: str) -> dict[str, Any]:
    client = _planner_client()
    try:
        result = asyncio.run(
            client.chat_completion(
                system_prompt,
                user_prompt,
                response_format={"type": "json_object"},
                temperature=0,
                seed=42,
            )
        )
    except Exception as exc:
        raise RuntimeError(_format_planner_error(exc)) from exc
    parsed = result.get("parsed")
    if not isinstance(parsed, dict):
        raise ValueError("planner LLM did not return a JSON object")
    return parsed


# Builds the user prompt for one planner turn.
def _turn_prompt(args: argparse.Namespace, steps: list[dict[str, Any]]) -> str:
    body = {
        "inputs": _input_snapshot(args),
        "history": steps,
        "instruction": "Pick the next tool as JSON.",
    }
    return json.dumps(body, ensure_ascii=False)


# Maps a stored screening status to the screening-agent exit code.
def _code_for_status(status: str, exit_ok: int, exit_error: int, exit_need_input: int) -> int:
    if status == "need_input":
        return exit_need_input
    if status in {"success", "partial_success"}:
        return exit_ok
    return exit_error


# Executes one allowlisted planner tool against the L1 loop.
def _execute_tool(
    tool: str,
    arguments: dict[str, Any],
    args: argparse.Namespace,
    *,
    run_loop: Callable[[argparse.Namespace], tuple[int, dict[str, Any]]],
    resolve_output_dir: Callable[[str], Path],
    last_payload: dict[str, Any] | None,
    exit_ok: int,
    exit_error: int,
    exit_need_input: int,
) -> tuple[int, dict[str, Any]]:
    if tool == "ask_user":
        missing, questions = _normalize_ask(arguments)
        ask = {"missing": missing, "questions": questions}
        payload = {
            "status": "need_input",
            "output_dir": str(resolve_output_dir(args.output_dir)),
            "runs": [],
            "result": {"status": "need_input", "missing": missing, "questions": questions, "ask": ask},
            "ask": ask,
        }
        return exit_need_input, payload
    if tool == "get_run_status":
        out_dir = resolve_output_dir(args.output_dir)
        observation = _read_agent_state(out_dir)
        payload = {
            "status": "status_read",
            "output_dir": str(out_dir),
            "runs": [],
            "result": observation,
            "ask": None,
        }
        return exit_ok, payload
    if tool == "finish":
        payload = last_payload or _payload_from_agent_state(resolve_output_dir(args.output_dir))
        if payload:
            status = str(payload.get("status") or "error")
            return _code_for_status(status, exit_ok, exit_error, exit_need_input), payload
        return exit_error, {
            "status": "error",
            "error_message": "finish called with no prior screening result",
            "runs": [],
            "result": {},
            "ask": None,
        }
    if tool in {"run_screening", "resume_run"}:
        cloned = argparse.Namespace(**vars(args))
        cloned.resume = tool == "resume_run"
        return run_loop(cloned)
    raise ValueError(f"unsupported tool: {tool}")


# Runs the LLM planner until a terminal screening status or step budget is hit.
def run_llm_planner(
    args: argparse.Namespace,
    *,
    run_loop: Callable[[argparse.Namespace], tuple[int, dict[str, Any]]],
    resolve_output_dir: Callable[[str], Path],
    exit_ok: int = 0,
    exit_error: int = 1,
    exit_need_input: int = 2,
    complete_json: Callable[[str, str], dict[str, Any]] | None = None,
) -> tuple[int, dict[str, Any]]:
    complete = complete_json or _default_complete_json
    out_dir = resolve_output_dir(args.output_dir)
    steps: list[dict[str, Any]] = []
    last_screening: dict[str, Any] | None = None
    last_code = exit_error
    tool_kwargs = {
        "run_loop": run_loop,
        "resolve_output_dir": resolve_output_dir,
        "exit_ok": exit_ok,
        "exit_error": exit_error,
        "exit_need_input": exit_need_input,
    }

    for _step in range(1, args.planner_max_steps + 1):
        raw = complete(SYSTEM_PROMPT, _turn_prompt(args, steps))
        try:
            action = _parse_action(raw)
        except ValueError as exc:
            observation = {"status": "error", "error_message": str(exc)}
            steps.append({"tool": "invalid", "arguments": {}, "reason": "", "observation": observation})
            continue

        if action["tool"] == "finish":
            code, payload = _execute_tool("finish", {}, args, last_payload=last_screening, **tool_kwargs)
            return _planner_envelope(code, payload, steps, out_dir)

        code, payload = _execute_tool(
            action["tool"],
            action["arguments"],
            args,
            last_payload=last_screening,
            **tool_kwargs,
        )
        observation = _compact_payload(payload)
        steps.append({**action, "observation": observation})
        if action["tool"] in {"run_screening", "resume_run", "ask_user"}:
            last_code, last_screening = code, payload

        status = str(payload.get("status") or "")
        if action["tool"] in {"run_screening", "resume_run", "ask_user"} and status in TERMINAL_STATUSES:
            return _planner_envelope(code, payload, steps, out_dir)

    if last_screening:
        return _planner_envelope(last_code, last_screening, steps, out_dir)
    empty = {"status": "error", "error_message": "planner produced no screening result", "runs": [], "result": {}, "ask": None}
    return _planner_envelope(exit_error, empty, steps, out_dir)


# Wraps the L1 payload with planner step history for auditability.
def _planner_envelope(
    code: int,
    payload: dict[str, Any],
    steps: list[dict[str, Any]],
    out_dir: Path,
) -> tuple[int, dict[str, Any]]:
    wrapped = dict(payload)
    wrapped["planner"] = "llm"
    wrapped["planner_steps"] = steps
    wrapped.setdefault("output_dir", str(out_dir))
    state_path = out_dir / "planner-state.json"
    state_path.write_text(
        json.dumps({"planner": "llm", "steps": steps, "status": wrapped.get("status")}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return code, wrapped
