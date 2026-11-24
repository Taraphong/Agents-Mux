"""Tool execution and command helpers.

The agent's file and command tools live here: path resolution, one-time
approval tokens, redaction-aware output capture and the shell runner. It logs
and redacts through core.log and core.redaction directly.
"""

import json
import os
import secrets
import shlex
import shutil
import signal
import subprocess
import tempfile
import threading
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

import memory_engine

from core.config import (
    APPROVAL_REQUIRED_TOOLS,
    APPROVAL_TTL_SECONDS,
    AUTH_FILE,
    COMMAND_MAX_OUTPUT_BYTES,
    COMMAND_TIMEOUT_SECONDS,
    ENV_FILE,
    HISTORY_ROOT,
    MACHINE_TOOL_NAMES,
    MAX_PENDING_APPROVALS,
    PROJECT_ROOT,
    PROJECT_ROOT_TEXT,
    PROTECTED_NAMES,
    PROTECTED_PARTS,
    SENSITIVE_ENV_PARTS,
    SETTINGS_FILE,
    TOOL_ALIASES,
    TOOL_MAX_READ_BYTES,
    TOOL_MAX_WRITE_BYTES,
    WORKSPACE_ROOT,
)
from core.log import log_event
from core.paths import normalized_path_under
from core.redaction import (
    PEM_LOOKBACK_BYTES,
    mask_unterminated_pem,
    pem_state,
    redact_command_output,
    redact_secrets,
)
from core.schedule_store import SCHEDULE_LOCK, load_schedules, save_schedules, validate_cron
from core.settings import (
    SETTINGS_LOCK,
    load_settings,
    secret_values,
    stored_custom_api_keys,
)
from core.skills import save_skill, skill_path


PENDING_TOOL_REQUESTS: dict[str, dict[str, Any]] = {}
PENDING_APPROVAL_LOCK = threading.Lock()


def resolve_project_path(raw_path: str, must_exist: bool = False) -> Path:
    """Resolve a user path inside the project while blocking protected files."""
    if not isinstance(raw_path, str) or not raw_path.strip():
        raise ValueError("A path inside the project is required")
    project_root = PROJECT_ROOT.resolve()
    candidate = normalized_path_under(raw_path, project_root, "Only paths inside the project folder are allowed")
    # Repeat the normalized prefix check here: CodeQL only treats a startswith()
    # guard in this function as a barrier for the accesses below.
    candidate_text = os.path.normpath(str(candidate))
    if candidate_text == PROJECT_ROOT_TEXT:
        candidate_text = PROJECT_ROOT_TEXT + os.sep
    if not candidate_text.startswith(PROJECT_ROOT_TEXT + os.sep):
        raise ValueError("Only paths inside the project folder are allowed")
    candidate = Path(candidate_text)
    relative_text = os.path.relpath(str(candidate), str(project_root))
    relative_parts: list[str] = [] if relative_text == os.curdir else relative_text.split(os.sep)
    if any(part in PROTECTED_PARTS for part in relative_parts) or candidate.name in PROTECTED_NAMES:
        raise ValueError("Access to files or folders holding secrets is not allowed")
    resolved_candidate = candidate.resolve()
    for target in configured_secret_targets():
        if resolved_candidate == target or target in resolved_candidate.parents:
            raise ValueError("Access to files or folders holding secrets is not allowed")
    if must_exist and not candidate.exists():
        raise FileNotFoundError(f"Path not found: {raw_path}")
    return candidate


def machine_access_enabled(settings: dict[str, Any] | None = None) -> bool:
    """Return whether tools may reach the whole machine instead of the project only."""
    settings = settings if settings is not None else load_settings()
    return bool(settings.get("machine_access", True))


def approval_required_tools(settings: dict[str, Any] | None = None) -> set[str]:
    """Return the tools that need a fresh, single-use user approval."""
    if machine_access_enabled(settings):
        return set(MACHINE_TOOL_NAMES)
    return set(APPROVAL_REQUIRED_TOOLS)


def resolve_tool_path(raw_path: str, must_exist: bool = False) -> Path:
    """Resolve a tool path safely for tool execution requests."""
    if not isinstance(raw_path, str) or not raw_path.strip():
        raise ValueError("A path is required")
    candidate = normalized_path_under(
        raw_path,
        PROJECT_ROOT,
        "The path is outside the project folder and is not allowed",
        PermissionError,
    )
    candidate_text = os.path.normpath(str(candidate))
    if candidate_text == PROJECT_ROOT_TEXT:
        candidate_text = PROJECT_ROOT_TEXT + os.sep
    if not candidate_text.startswith(PROJECT_ROOT_TEXT + os.sep):
        raise PermissionError("The path is outside the project folder and is not allowed")
    candidate = Path(candidate_text)
    if must_exist and not candidate.exists():
        raise FileNotFoundError(f"Path not found: {raw_path}")
    return candidate


def resolve_machine_path(raw_path: str, must_exist: bool = False) -> Path:
    """Resolve a path anywhere on the machine for machine-access tools.

    Machine access is the documented default; without this resolver the tools
    advertised as machine-scoped still refused every path outside the project.
    The parent is resolved through realpath before ".." is collapsed, so a
    symlinked folder cannot turn an approved write into a different file, and
    the final component may still be missing because write_file creates it.
    protected_write_target() resolves the finished path before it decides, so a
    symlinked final file is checked against the same secret rules.
    """
    if not isinstance(raw_path, str) or not raw_path.strip():
        raise ValueError("A path is required")
    raw_text = raw_path.strip()
    if "\x00" in raw_text:
        raise ValueError("Invalid path")
    expanded = os.path.expanduser(raw_text)
    parent_text, name = os.path.split(expanded)
    if not name or name in {".", ".."}:
        raise ValueError("Invalid path")
    if os.sep in name or (os.altsep and os.altsep in name):
        raise ValueError("Invalid path")
    resolved_parent = os.path.realpath(parent_text or os.curdir)
    candidate = Path(os.path.normpath(os.path.join(resolved_parent, name)))
    if must_exist and not candidate.exists():
        raise FileNotFoundError(f"Path not found: {raw_path}")
    return candidate


def workspace_directory() -> Path:
    """Return the AI workspace folder, creating it on first use."""
    root = Path(os.path.normpath(str(PROJECT_ROOT / WORKSPACE_ROOT)))
    root.mkdir(parents=True, exist_ok=True)
    return root


def workspace_tool_path(raw_path: Any) -> Path:
    """Resolve a tool path against the AI workspace instead of the app folder.

    A relative path (or no path at all) belongs to the workspace, while an
    absolute path or one starting with ~ still reaches the rest of the machine
    when machine access is on.
    """
    text = "" if raw_path is None else str(raw_path).strip()
    if not text or text in {".", "./"}:
        return workspace_directory()
    expanded = os.path.expanduser(text)
    if os.path.isabs(expanded):
        return Path(os.path.normpath(expanded))
    return Path(os.path.normpath(os.path.join(str(workspace_directory()), expanded)))


def configured_secret_targets() -> list[Path]:
    """Return the settings, auth, history, memory and certificate paths in use."""
    # ENV_FILE is included because .env itself can be a symlink: resolving the
    # write target would otherwise hide the protected name behind its target.
    targets = [SETTINGS_FILE, AUTH_FILE, HISTORY_ROOT, ENV_FILE]
    # The memory paths can be moved with AI_WEB_MEMORY_*; the static names above
    # would then miss them, so the configured locations are compared too.
    targets.extend(
        [
            memory_engine.MEMORY_FILE,
            memory_engine.DREAMS_FILE,
            memory_engine.DATABASE_FILE,
            Path(f"{memory_engine.DATABASE_FILE}-wal"),
            Path(f"{memory_engine.DATABASE_FILE}-shm"),
            memory_engine.MEMORY_DIR,
        ]
    )
    for name in ("AI_WEB_TLS_CERT", "AI_WEB_TLS_KEY"):
        value = os.getenv(name, "").strip()
        if value:
            targets.append(Path(value))
    resolved: list[Path] = []
    for target in targets:
        try:
            resolved.append(target.expanduser().resolve())
        except OSError:
            continue
    return resolved


def protected_write_target(path: Path) -> bool:
    """Return True when a write would touch a secret or machine-specific file.

    These files hold API keys, pairing state, certificates and conversation
    history, so no tool may overwrite them even when machine access is on.
    The settings, auth, history and certificate locations can be moved with
    environment variables, so the configured paths are compared as well: a
    write to a custom settings file must stay blocked like the default one.
    """
    parts = [part for part in path.parts if part not in {"/", "", "."}]
    if any(part in PROTECTED_NAMES for part in parts):
        return True
    if any(part in PROTECTED_PARTS for part in parts):
        return True
    # Canonicalize in a non-strict way for untrusted paths: resolve the parent
    # through realpath, then collapse traversal in the final path text.
    try:
        expanded = os.path.expanduser(str(path))
        parent_text, name = os.path.split(expanded)
        resolved_parent = os.path.realpath(parent_text or os.curdir)
        resolved = Path(os.path.normpath(os.path.join(resolved_parent, name)))
    except OSError:
        return False
    resolved_parts = [part for part in resolved.parts if part not in {"/", "", "."}]
    if any(part in PROTECTED_NAMES or part in PROTECTED_PARTS for part in resolved_parts):
        return True
    for target in configured_secret_targets():
        if resolved == target or target in resolved.parents:
            return True
    return False


def display_tool_path(path: Path) -> str:
    """Show a project-relative path when possible, otherwise the absolute path."""
    try:
        return str(path.relative_to(PROJECT_ROOT))
    except ValueError:
        return str(path)


def ensure_safe_command_token(token: str) -> None:
    """Reject command arguments that point outside the project or at protected files."""
    normalized = token.replace("\\", "/").strip()
    if not normalized or normalized.startswith("-"):
        return
    parts = [part for part in normalized.split("/") if part not in {"", "."}]
    if normalized.startswith(("/", "~")) or ".." in parts:
        raise ValueError("The command must reference paths inside the project only")
    if any(part in PROTECTED_PARTS or part in PROTECTED_NAMES for part in parts):
        raise ValueError("Access to files or folders holding secrets is not allowed")
SAFE_GIT_SUBCOMMANDS = {"status", "diff", "log"}
SAFE_GIT_OPTIONS = {
    "-p", "-n", "--oneline", "--stat", "--shortstat", "--name-only", "--name-status",
    "--no-color", "--no-pager", "--graph", "--decorate", "--all", "--cached",
}
SAFE_LS_OPTIONS = {"-a", "-l", "-la", "-al", "-lh", "-lah", "-R", "-t", "-r", "-1", "-h"}


def parse_command(command: str) -> list[str]:
    """Parse one whitelisted command into argv without ever invoking a shell."""
    if any(character in command for character in ("\n", "\r", ";", "|", "&", ">", "<", "`", "$(")):
        raise ValueError("The command uses syntax that is not allowed")
    try:
        argv = shlex.split(command)
    except ValueError as exc:
        raise ValueError("Invalid command format") from exc
    if not argv:
        raise ValueError("A command is required")
    binary, rest = argv[0], argv[1:]
    if binary == "pwd":
        if rest:
            raise ValueError("pwd takes no arguments")
    elif binary == "ls":
        for token in rest:
            if token.startswith("-"):
                if token not in SAFE_LS_OPTIONS:
                    raise ValueError(f"ls option {token} is not allowed")
            else:
                ensure_safe_command_token(token)
    elif binary == "git":
        if not rest or rest[0] not in SAFE_GIT_SUBCOMMANDS:
            raise ValueError("Only git status, git diff and git log are allowed")
        for token in rest[1:]:
            if token.startswith("-"):
                if token not in SAFE_GIT_OPTIONS and not token.lstrip("-").isdigit():
                    raise ValueError(f"git option {token} is not allowed")
            else:
                ensure_safe_command_token(token)
        # .git/config and .gitattributes can point at external programs or
        # textconv filters; neither may run while inspecting the repository.
        argv = ["git", "-c", "diff.external=", "--no-pager", *rest]
        if rest[0] in {"diff", "log"}:
            argv.extend(["--no-ext-diff", "--no-textconv"])
    elif binary in {"python", "python3"}:
        if rest != ["-m", "py_compile", "app.py"]:
            raise ValueError("Only the app.py syntax check is allowed")
    else:
        raise ValueError("Only the defined project check commands are allowed")
    return argv


def request_tool_approval(name: str, arguments: dict[str, Any]) -> tuple[str, int]:
    """Create a short-lived approval token for a sensitive tool call.

    Returns the token and the unix timestamp it expires at. The expiry is
    derived from the same clock reading that is stored as ``created_at``, so
    the deadline the client shows matches what ``consume_tool_approval``
    accepts even when this call waits on the lock.
    """
    approval_id = secrets.token_urlsafe(24)
    now = time.time()
    with PENDING_APPROVAL_LOCK:
        for key, item in list(PENDING_TOOL_REQUESTS.items()):
            if now - item.get("created_at", 0) > APPROVAL_TTL_SECONDS:
                PENDING_TOOL_REQUESTS.pop(key, None)
        while len(PENDING_TOOL_REQUESTS) >= MAX_PENDING_APPROVALS:
            PENDING_TOOL_REQUESTS.pop(next(iter(PENDING_TOOL_REQUESTS)))
        PENDING_TOOL_REQUESTS[approval_id] = {"name": name, "arguments": arguments, "created_at": now}
    return approval_id, int(now) + APPROVAL_TTL_SECONDS


def consume_tool_approval(approval_id: Any, name: str, arguments: dict[str, Any]) -> bool:
    """Validate and consume a pending tool approval exactly once."""
    if not isinstance(approval_id, str) or not approval_id:
        return False
    now = time.time()
    with PENDING_APPROVAL_LOCK:
        pending = PENDING_TOOL_REQUESTS.pop(approval_id, None)
    if not pending:
        return False
    if now - pending.get("created_at", 0) > APPROVAL_TTL_SECONDS:
        return False
    return pending.get("name") == name and pending.get("arguments") == arguments


def run_local_tool(name: str, arguments: dict[str, Any], approved: bool = False) -> dict[str, Any]:
    """Execute one local tool call after checking approvals and arguments."""
    requested_name = name
    name = TOOL_ALIASES.get(name, name)
    if requested_name != name:
        log_event("tool.alias", f"Mapped tool name {requested_name} to {name}", requested=requested_name, tool=name)
    log_event("tool.start", f"Starting {name}", tool=name, approved=approved)
    if name == "create_skill":
        if not approved:
            raise PermissionError("Creating a skill needs approval first")
        # The tool owns the layout: SKILL.md always gets a name/description
        # frontmatter, and extra files may only go in scripts/, references/
        # or assets/ so the folder stays the documented skill structure.
        created = save_skill(
            str(arguments.get("name", "")),
            description=arguments.get("description", ""),
            content=arguments.get("content", ""),
            files=arguments.get("files"),
        )
        path = skill_path(created["name"])
        try:
            display_path = str(path.relative_to(PROJECT_ROOT))
        except ValueError:
            # AI_WEB_SKILLS_DIR may point outside the project; report it as is.
            display_path = str(path)
        result = {
            "tool": name,
            "name": created["name"],
            "path": display_path,
            "description": created["description"],
            "files": created["files"],
        }
        log_event("tool.success", f"Created skill {created['name']}", tool=name, path=result["path"])
        return result
    if name == "create_schedule":
        if not approved:
            raise PermissionError("Creating a scheduled job needs approval first")
        job_name = str(arguments.get("name", "")).strip()
        prompt = str(arguments.get("prompt", "")).strip()
        if not job_name or not prompt:
            raise ValueError("A job name and prompt are required")
        schedule = validate_cron(arguments.get("schedule", ""))
        discord_channel_id = str(arguments.get("discord_channel_id", "")).strip()[:30]
        if discord_channel_id and not discord_channel_id.isdigit():
            raise ValueError("The Discord Channel ID must be a number")
        job = {
            "id": str(uuid.uuid4()),
            "conversation_id": str(uuid.uuid4()),
            "name": job_name[:100],
            "schedule": schedule,
            "prompt": prompt[:10_000],
            "model": str(arguments.get("model", "")).strip()[:200],
            "discord_channel_id": discord_channel_id,
            "enabled": bool(arguments.get("enabled", True)),
            "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            "last_run_at": None,
            "last_status": None,
            "last_error": "",
        }
        with SCHEDULE_LOCK:
            jobs = load_schedules()
            jobs.append(job)
            save_schedules(jobs)
        log_event("schedule.created", f"Created scheduled job {job['name']}", job=job["id"], schedule=schedule)
        return {"tool": name, "job": job, "timezone": datetime.now().astimezone().tzname()}
    if name == "update_schedule":
        if not approved:
            raise PermissionError("Editing a scheduled job needs approval first")
        job_id = str(arguments.get("job_id", "")).strip()
        if not job_id:
            raise ValueError("job_id is required")
        with SCHEDULE_LOCK:
            jobs = load_schedules()
            job = next((item for item in jobs if item.get("id") == job_id), None)
            if not job:
                raise ValueError("Scheduled job not found")
            if "schedule" in arguments:
                job["schedule"] = validate_cron(arguments["schedule"])
            if "name" in arguments:
                job["name"] = str(arguments["name"]).strip()[:100] or job["name"]
            if "prompt" in arguments:
                job["prompt"] = str(arguments["prompt"]).strip()[:10_000]
            if "model" in arguments:
                job["model"] = str(arguments["model"]).strip()[:200]
            if "discord_channel_id" in arguments:
                channel_id = str(arguments["discord_channel_id"]).strip()[:30]
                if channel_id and not channel_id.isdigit():
                    raise ValueError("The Discord Channel ID must be a number")
                job["discord_channel_id"] = channel_id
            if "enabled" in arguments:
                job["enabled"] = bool(arguments["enabled"])
            save_schedules(jobs)
        log_event("schedule.updated", f"Updated scheduled job {job['name']}", job=job_id)
        return {"tool": name, "job": job, "timezone": datetime.now().astimezone().tzname()}
    if name == "list_files":
        machine_access = machine_access_enabled()
        requested_path = str(workspace_tool_path(arguments.get("path", ".")))
        if machine_access:
            root = resolve_machine_path(requested_path, must_exist=True)
        else:
            root = resolve_tool_path(requested_path, must_exist=True)
            root_text = os.path.normpath(str(root))
            if root_text == PROJECT_ROOT_TEXT:
                root_text = PROJECT_ROOT_TEXT + os.sep
            if not root_text.startswith(PROJECT_ROOT_TEXT + os.sep):
                raise PermissionError("The path is outside the project folder and is not allowed")
            root = Path(root_text)
        if not root.is_dir():
            raise ValueError("This path is not a folder")
        files: list[str] = []
        truncated = False
        for dirpath, dirnames, filenames in os.walk(root):
            if not machine_access:
                dirnames[:] = sorted(directory for directory in dirnames if directory not in PROTECTED_PARTS)
            for filename in sorted(filenames):
                if not machine_access and filename in PROTECTED_NAMES:
                    continue
                if len(files) >= 500:
                    truncated = True
                    break
                files.append(display_tool_path(Path(dirpath, filename)))
            if truncated:
                break
        result = {"tool": name, "files": files, "truncated": truncated, "scope": "machine" if machine_access else "project"}
        log_event("tool.success", f"Used {name}", tool=name, count=len(files))
        return result

    if name == "read_file":
        machine_access = machine_access_enabled()
        if not str(arguments.get("path") or "").strip():
            raise ValueError("A file path is required (relative paths resolve inside the workspace folder)")
        requested_path = str(workspace_tool_path(arguments.get("path", "")))
        if machine_access:
            # Same scope as list_files and write_file: any path on the machine,
            # including a workspace folder configured outside the project.
            path = resolve_machine_path(requested_path, must_exist=True)
        else:
            path = resolve_project_path(requested_path, must_exist=True)
            file_text = os.path.normpath(str(path))
            if not file_text.startswith(PROJECT_ROOT_TEXT + os.sep):
                raise PermissionError("The path is outside the project folder and is not allowed")
            path = Path(file_text)
        if not path.is_file():
            raise ValueError("This path is not a file")
        if path.stat().st_size > TOOL_MAX_READ_BYTES:
            raise ValueError("The file is larger than the allowed read size")
        if machine_access:
            # Whole-machine reads must not copy stored credentials into the chat
            # transcript or the saved conversation history. The snapshot, the
            # read and the redaction share SETTINGS_LOCK with the settings
            # writers: a save that lands mid-read would otherwise add a key
            # that neither the snapshot nor the redaction knows.
            with SETTINGS_LOCK:
                try:
                    secrets_before_read = secret_values()
                except (OSError, ValueError):
                    secrets_before_read = []
                content = path.read_text(encoding="utf-8", errors="replace")
                content = redact_secrets(content)
                content = redact_command_output(content, secrets_before_read)
        else:
            content = path.read_text(encoding="utf-8", errors="replace")
        result = {"tool": name, "path": display_tool_path(path), "content": content, "scope": "machine" if machine_access else "project"}
        log_event("tool.success", f"Used {name}", tool=name, path=result["path"])
        return result

    if name == "write_file":
        if not approved:
            raise PermissionError("Writing a file needs approval first")
        machine_access = machine_access_enabled()
        if not str(arguments.get("path") or "").strip():
            raise ValueError("A file path is required (relative paths resolve inside the workspace folder)")
        requested_path = str(workspace_tool_path(arguments.get("path", "")))
        if machine_access:
            path = resolve_machine_path(requested_path)
        else:
            path = resolve_tool_path(requested_path)
            write_text = os.path.normpath(str(path))
            if not write_text.startswith(PROJECT_ROOT_TEXT + os.sep):
                raise PermissionError("The path is outside the project folder and is not allowed")
            path = Path(write_text)
        content = arguments.get("content", "")
        if not isinstance(content, str) or len(content.encode("utf-8")) > TOOL_MAX_WRITE_BYTES:
            raise ValueError("The file content is larger than allowed")
        if protected_write_target(path):
            raise PermissionError("Writing files that hold secrets, certificates or history is not allowed")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        result = {"tool": name, "path": display_tool_path(path), "bytes": len(content.encode("utf-8"))}
        log_event("tool.success", f"Used {name}", tool=name, path=result["path"], bytes=result["bytes"])
        return result

    if name == "run_command":
        if not approved:
            raise PermissionError("Running a command needs approval first")
        command = arguments.get("command", "")
        if not isinstance(command, str) or not command.strip():
            raise ValueError("A command is required")
        command = command.strip()
        if len(command) > 4000:
            raise ValueError("The command is too long (4000 characters max)")
        if machine_access_enabled():
            # A real shell with the app user's privileges: any binary, pipes,
            # sudo (when the user may run it without a password prompt), and
            # any path on the machine. The approval click is the boundary.
            returncode, stdout, stderr, timed_out, truncated, duration_ms, launch_secrets = run_shell_process(command, workspace_directory())
            if timed_out:
                returncode = 124
            secrets_found = secret_values(launch_secrets)
            result = {
                "tool": name,
                "command": redact_command_output(command, secrets_found),
                "returncode": returncode,
                "stdout": redact_command_output(stdout, secrets_found),
                "stderr": redact_command_output(stderr, secrets_found),
                "timed_out": timed_out,
                "truncated": truncated,
                "duration_ms": duration_ms,
                "scope": "machine",
            }
            log_event(
                "tool.success" if returncode == 0 else "tool.failed",
                f"Command finished ({returncode})",
                tool=name,
                command=redact_command_output(command, secrets_found)[:300],
                duration_ms=duration_ms,
            )
            return result
        argv = parse_command(command)
        completed = subprocess.run(argv, cwd=PROJECT_ROOT, shell=False, capture_output=True, text=True, timeout=30)
        result = {"tool": name, "command": command, "returncode": completed.returncode, "stdout": completed.stdout[-20_000:], "stderr": completed.stderr[-20_000:], "scope": "project"}
        log_event("tool.success" if completed.returncode == 0 else "tool.failed", f"Command finished ({completed.returncode})", tool=name, command=command)
        return result

    raise ValueError("Unknown tool")


def command_shell() -> str:
    """Pick an available POSIX shell, including Termux where /bin/sh may not exist."""
    for candidate in (os.getenv("SHELL"), shutil.which("bash"), shutil.which("sh"), "/system/bin/sh", "/bin/sh"):
        if candidate and Path(candidate).exists():
            return candidate
    return "sh"


def command_environment() -> tuple[dict[str, str], list[str]]:
    """Inherit the server environment without exposing credentials to commands.

    Returns the child environment plus the custom key values injected into it,
    so a command's output can still be redacted when a key is deleted or
    replaced while that command is still running.
    """
    env = {
        name: value
        for name, value in os.environ.items()
        if not any(part in name.upper() for part in SENSITIVE_ENV_PARTS)
    }
    # Extra keys saved in Settings are exposed by name so a skill or command
    # can use e.g. "$WEATHER_API_KEY" without the value ever reaching the chat.
    injected: list[str] = []
    try:
        for name, value in stored_custom_api_keys(load_settings()).items():
            if name in env:
                continue
            env[name] = value
            injected.append(value)
    except (OSError, ValueError):
        pass
    env.setdefault("TERM", "xterm-256color")
    env.setdefault("LANG", "C.UTF-8")
    env["PYTHONUNBUFFERED"] = "1"
    return env, injected


def read_command_capture(handle: Any) -> tuple[str, bool]:
    """Read at most the tail of a captured stream so runaway output cannot exhaust memory."""
    handle.flush()
    handle.seek(0, os.SEEK_END)
    size = handle.tell()
    start = max(0, size - COMMAND_MAX_OUTPUT_BYTES)
    cut = start > 0
    # A private key block may open before the tail starts, so derive the
    # redaction state from a bounded window in front of it instead of relying on
    # the BEGIN line being inside the returned text.
    starts_inside = False
    if cut:
        lookback_start = max(0, start - PEM_LOOKBACK_BYTES)
        handle.seek(lookback_start)
        starts_inside = pem_state(
            handle.read(start - lookback_start).decode("utf-8", errors="replace")
        )
    handle.seek(start)
    text = mask_unterminated_pem(
        handle.read().decode("utf-8", errors="replace"), starts_inside
    )
    if cut:
        text = "… (start of the output trimmed because there is a lot of it)\n" + text
    return text, cut


def process_group_alive(pgid: int) -> bool:
    """Report whether any process of a command's group still runs."""
    try:
        os.killpg(pgid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def kill_process_group(pgid: int) -> None:
    """Kill every process left in a command's group."""
    try:
        os.killpg(pgid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        pass


def run_shell_process(command: str, cwd: Path) -> tuple[int, str, str, bool, bool, int, list[str]]:
    """Run a command with capped output and a hard timeout for the whole process group."""
    started_at = time.perf_counter()
    timed_out = False
    env, injected_secrets = command_environment()
    if not command.strip():
        raise ValueError("Type a command")
    # Agent commands run through the real shell so pipes, redirections, globs
    # and variables behave as typed; approval is the boundary.
    argv = [command_shell(), "-c", command]
    with tempfile.TemporaryFile() as out_file, tempfile.TemporaryFile() as err_file:
        process = subprocess.Popen(
            argv,
            cwd=str(cwd),
            stdin=subprocess.DEVNULL,
            stdout=out_file,
            stderr=err_file,
            env=env,
            start_new_session=True,
        )
        # The group is its own session, so its id is the leader's pid.
        pgid = process.pid
        deadline = time.monotonic() + COMMAND_TIMEOUT_SECONDS
        try:
            process.wait(timeout=COMMAND_TIMEOUT_SECONDS)
        except subprocess.TimeoutExpired:
            timed_out = True
            kill_process_group(pgid)
            process.wait()
        # A shell that exits still leaves `cmd &` jobs running in the group, and
        # they keep the capture files open. They get the same deadline, then the
        # group is killed so nothing outlives the timeout.
        while process_group_alive(pgid):
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                # The shell already exited, so the job outlived the deadline:
                # report it as a timeout instead of the shell's status 0.
                kill_process_group(pgid)
                timed_out = True
                break
            time.sleep(min(0.05, remaining))
        stdout, stdout_cut = read_command_capture(out_file)
        stderr, stderr_cut = read_command_capture(err_file)
    duration_ms = round((time.perf_counter() - started_at) * 1000)
    return process.returncode, stdout, stderr, timed_out, stdout_cut or stderr_cut, duration_ms, injected_secrets


def parse_tool_request(answer: str) -> dict[str, Any] | None:
    """Return the first tool call found in an AI answer, if any."""
    requests = parse_tool_requests(answer)
    return requests[0] if requests else None
ASCII_LOWERCASE_TABLE = str.maketrans(
    "ABCDEFGHIJKLMNOPQRSTUVWXYZ", "abcdefghijklmnopqrstuvwxyz"
)


def tool_call_bodies(answer: str) -> list[str]:
    """Return the body of every <tool_call> block in *answer*.

    Plain marker scanning keeps the work linear, so a reply that repeats
    "<tool_call>" many times cannot make the parser backtrack. Only ASCII
    letters are lowercased: str.lower() can lengthen a character (for example
    U+0130 becomes two characters), which would shift the marker offsets that
    slice *answer*.
    """
    bodies: list[str] = []
    lowered = answer.translate(ASCII_LOWERCASE_TABLE)
    start = 0
    while True:
        open_at = lowered.find("<tool_call>", start)
        if open_at < 0:
            return bodies
        body_start = open_at + len("<tool_call>")
        close_at = lowered.find("</tool_call>", body_start)
        if close_at < 0:
            # A reply that was cut off, or a model that forgot the closing
            # marker, can still carry a complete payload. Keep the remainder so
            # a whole JSON object runs and a broken one reaches the repair step
            # instead of being printed to the user as raw text.
            bodies.append(answer[body_start:])
            return bodies
        bodies.append(answer[body_start:close_at])
        start = close_at + len("</tool_call>")


def parse_tool_requests(answer: str) -> list[dict[str, Any]]:
    """Parse every tool call so multiple Skill files can be inspected in one turn."""
    if not isinstance(answer, str):
        return []
    # A marker scan instead of a DOTALL regular expression: the answer is shared
    # with the model, so a pathological reply must not be able to backtrack.
    matches = tool_call_bodies(answer)
    if not matches:
        return []
    requests = []
    for raw_request in matches:
        try:
            request = json.loads(raw_request.strip())
        except json.JSONDecodeError as exc:
            log_event("tool.parse_failed", "Could not parse the tool_call", error=str(exc))
            raise ValueError("Invalid tool_call format") from exc
        tool_request = normalize_tool_payload(request)
        log_event("tool.request", f"The AI requested {tool_request['name']}", tool=tool_request["name"])
        requests.append(tool_request)
    return requests


def normalize_tool_payload(request: Any) -> dict[str, Any]:
    """Coerce the payload shapes small models emit into name + arguments.

    A weaker model sometimes answers with ``{"command": "curl ..."}`` (no tool
    name) or puts the arguments next to the name instead of inside
    ``arguments``. Refusing those used to cost the user the whole turn, so an
    unnamed command becomes ``run_command`` and loose keys become the argument
    object. Every tool still passes the approval step before it runs.
    """
    if not isinstance(request, dict):
        raise ValueError("Invalid tool_call payload")
    name = request.get("name")
    arguments = request.get("arguments")
    if not isinstance(name, str) or not name.strip():
        command = request.get("command")
        if isinstance(command, str) and command.strip():
            return {"name": "run_command", "arguments": {"command": command}}
        raise ValueError("Invalid tool_call payload")
    if not isinstance(arguments, dict):
        arguments = {
            key: value
            for key, value in request.items()
            if key not in {"name", "arguments"}
        }
    return {"name": name.strip(), "arguments": arguments}


def has_tool_marker(answer: str) -> bool:
    """Report whether an answer still contains a tool-call marker."""
    return isinstance(answer, str) and "<tool_call>" in answer.translate(ASCII_LOWERCASE_TABLE)


def strip_tool_markers(answer: str) -> str:
    """Remove tool-call protocol text from an answer meant for the user.

    A marker scan instead of a DOTALL regular expression, for the same reason as
    tool_call_bodies(): the model's reply must not be able to make the parser
    backtrack. A dangling marker drops everything after it, because that tail is
    the unreadable call itself.
    """
    if not isinstance(answer, str):
        return ""
    if not has_tool_marker(answer):
        return answer
    lowered = answer.translate(ASCII_LOWERCASE_TABLE)
    pieces: list[str] = []
    start = 0
    while True:
        open_at = lowered.find("<tool_call>", start)
        if open_at < 0:
            pieces.append(answer[start:])
            break
        pieces.append(answer[start:open_at])
        close_at = lowered.find("</tool_call>", open_at)
        if close_at < 0:
            break
        start = close_at + len("</tool_call>")
    return "".join(pieces).strip()
