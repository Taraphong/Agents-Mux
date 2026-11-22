"""Path safety helpers shared by the stores and the tools."""

from pathlib import Path


def normalized_path_under(raw_path: str, root: Path, message: str, error: type[Exception] = ValueError) -> Path:
    """Normalize a user path and keep it inside *root*.

    The shape matters: CodeQL's py/path-injection query only treats a path as
    checked when it passes through os.path.normpath()/realpath() and is then
    compared with str.startswith(). Path.relative_to() alone is not recognised
    as a check, so the guard is written the way the query understands.
    """
    if not isinstance(raw_path, str) or not raw_path.strip():
        raise error(message)
    root_text = os.path.normpath(os.path.realpath(str(root)))
    candidate_text = os.path.normpath(
        os.path.realpath(os.path.join(root_text, os.path.expanduser(raw_path.strip())))
    )
    if candidate_text != root_text and not candidate_text.startswith(root_text + os.sep):
        raise error(message)
    return Path(candidate_text)
