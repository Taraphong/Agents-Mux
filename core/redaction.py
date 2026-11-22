"""Secret and private-key redaction helpers.

Tool output is shown in the chat and written to the log, so anything that looks
like a key, token or PEM block is masked before it leaves the process.
"""

import re


PEM_REDACTED_MARKER = "•••••••• (private key hidden)"
PEM_MARKER_PATTERN = re.compile(
    r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----|-----END [A-Z0-9 ]*PRIVATE KEY-----"
)
# How far before a truncated capture tail to look for an opening BEGIN line.
PEM_LOOKBACK_BYTES = 8192
def pem_state(text: str, inside: bool = False) -> bool:
    """Report whether the text ends inside a private key block."""
    for match in PEM_MARKER_PATTERN.finditer(text):
        inside = match.group(0).startswith("-----BEGIN")
    return inside
def mask_unterminated_pem(text: str, starts_inside: bool = False) -> str:
    """Mask private key blocks, including one cut in half by the read boundary."""
    if not text:
        return text
    ranges: list[tuple[int, int]] = []
    inside = starts_inside
    opened_at = 0
    for match in PEM_MARKER_PATTERN.finditer(text):
        if match.group(0).startswith("-----BEGIN"):
            if not inside:
                inside = True
                opened_at = match.start()
        elif inside:
            inside = False
            ranges.append((opened_at, match.end()))
    if inside:
        ranges.append((opened_at, len(text)))
    for start, end in reversed(ranges):
        text = text[:start] + PEM_REDACTED_MARKER + text[end:]
    return text
def redact_command_output(text: str, secrets_found: list[str]) -> str:
    """Replace known secrets and any private key block in command output."""
    for secret in secrets_found:
        text = text.replace(secret, "••••••••")
    # mask_unterminated_pem walks the BEGIN/END markers instead of running a
    # DOTALL regex over the whole capture, so large output cannot go quadratic.
    return mask_unterminated_pem(text)
SECRET_QUERY_PATTERN = re.compile(r"([?&](?:key|api_key|api-key|token|access_token)=)[^&\s\"'<>]+", re.IGNORECASE)
