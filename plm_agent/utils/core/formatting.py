import re

_MD_ESCAPE_CHARS = str.maketrans({  # e.g. gene_stats.csv -> gene\_stats.csv
    '_': r'\_', '*': r'\*', '[': r'\[', ']': r'\]', '`': r'\`', '~': r'\~',
})
_MD_UNESCAPE_RE = re.compile(r'\\([_*\[\]`~])')


def escape_md_filename(name: str) -> str:
    """Escape markdown special characters in a filename."""
    return name.translate(_MD_ESCAPE_CHARS)


def unescape_md_filename(name: str) -> str:
    """Remove backslash escapes to recover the original filename."""
    return _MD_UNESCAPE_RE.sub(r'\1', name)


def if_camel_to_snake(name: str) -> str:
    if not re.match(r'^[a-zA-Z]+$', name):
        return name
    s1 = re.sub('(.)([A-Z][a-z]+)', r'\1_\2', name)
    return re.sub('([a-z0-9])([A-Z])', r'\1_\2', s1).lower()


def truncate_output(output: str, max_chars: int = 30000) -> str:
    """Truncate long output keeping head (30%) and tail (70%).

    The tail-heavy split preserves the most recent output which is
    typically more relevant for debugging and LLM context.

    Args:
        output: The text to truncate.
        max_chars: Maximum allowed characters.

    Returns:
        Original string if within limit, otherwise head + marker + tail.
    """
    if not output or len(output) <= max_chars:
        return output or ""

    head_size = int(max_chars * 0.3)
    tail_size = max_chars - head_size
    truncated_chars = len(output) - max_chars

    return (
        output[:head_size]
        + f"\n\n... [truncated {truncated_chars} characters] ...\n\n"
        + output[-tail_size:]
    )