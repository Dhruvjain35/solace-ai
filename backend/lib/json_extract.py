"""Tolerant JSON extraction for LLM output.

LLMs wrap JSON in markdown fences, add prose, and — when they hit the
``max_tokens`` ceiling — stop mid-structure, leaving unbalanced brackets and an
unterminated string. The naive ``json.loads(re.search(r"\\{.*\\}", text))``
pattern that was copy-pasted across ~23 services throws on all of these, and
every caller silently degrades to an empty result. This is exactly how the
differential "stopped working" when we moved to a chattier model.

``extract_obj`` recovers a usable dict from any of those cases:
  1. strip fences / surrounding prose,
  2. parse the first balanced object as-is,
  3. on failure, repair a truncated tail (close the open string + brackets) and
     retry — dropping a partial trailing array element if needed.

It never raises; it returns ``None`` only when there is no recoverable object.
"""
from __future__ import annotations

import json
from typing import Any


def extract_obj(text: str) -> dict[str, Any] | None:
    """Best-effort parse of the first JSON object in ``text``. Returns the dict
    or ``None``. Tolerant of markdown fences, leading/trailing prose, and
    output truncated by a token limit."""
    return _extract(text, "{", dict)


def extract_array(text: str) -> list[Any] | None:
    """Best-effort parse of the first JSON array in ``text``. Same tolerance as
    ``extract_obj`` (fences, prose, truncated tail). Returns the list or ``None``."""
    return _extract(text, "[", list)


def _extract(text: str, open_char: str, want: type) -> Any | None:
    if not text:
        return None
    s = _strip_fences(text)
    start = s.find(open_char)
    if start == -1:
        return None
    s = s[start:]

    # 1. Fast path — already valid (possibly with trailing prose).
    end = _balanced_end(s)
    if end is not None:
        val = _try_loads(s[: end + 1], want)
        if val is not None:
            return val

    # 2. Truncated tail — repair by closing open string/brackets, retrying with
    #    progressively more of the partial trailing element trimmed off.
    return _loads_repaired(s, want)


def _strip_fences(text: str) -> str:
    t = text.strip()
    if "```" in t:
        # take the content of the first fenced block if present
        parts = t.split("```")
        if len(parts) >= 3:
            block = parts[1]
            block = block.removeprefix("json").removeprefix("JSON").lstrip("\n")
            if "{" in block:
                return block.strip()
    return t


def _try_loads(candidate: str, want: type = dict) -> Any | None:
    try:
        obj = json.loads(candidate)
        return obj if isinstance(obj, want) else None
    except (json.JSONDecodeError, ValueError):
        return None


def _balanced_end(s: str) -> int | None:
    """Index of the '}' that closes the object opened at s[0], or None if the
    string ends before the object closes. String/escape aware."""
    depth = 0
    in_str = False
    esc = False
    for i, ch in enumerate(s):
        if esc:
            esc = False
            continue
        if ch == "\\" and in_str:
            esc = True
            continue
        if ch == '"':
            in_str = not in_str
            continue
        if in_str:
            continue
        if ch in "{[":
            depth += 1
        elif ch in "}]":
            depth -= 1
            if depth == 0:
                return i
    return None


def _loads_repaired(s: str, want: type = dict) -> Any | None:
    """Close an unterminated string and any open brackets, then parse. If the
    truncation landed inside a partial element, trim back to the last clean
    boundary (comma or closing bracket at the right depth) and try again."""
    # Track structure to know what to close.
    stack: list[str] = []
    in_str = False
    esc = False
    # Boundaries (index just AFTER) where the structure was 'clean' — i.e. an
    # element had just ended. Trimming here drops only a partial trailing item.
    boundaries: list[int] = []
    for i, ch in enumerate(s):
        if esc:
            esc = False
            continue
        if ch == "\\" and in_str:
            esc = True
            continue
        if ch == '"':
            in_str = not in_str
            continue
        if in_str:
            continue
        if ch in "{[":
            stack.append(ch)
        elif ch in "}]":
            if stack:
                stack.pop()
            boundaries.append(i + 1)
        elif ch == ",":
            boundaries.append(i)  # cut BEFORE the comma

    # Attempt 1: close what's open at the very end.
    candidate = _close(s, in_str, stack)
    obj = _try_loads(candidate, want)
    if obj is not None:
        return obj

    # Attempt 2..N: trim to each earlier clean boundary, newest first, and close
    # the brackets that were open at that point.
    for cut in reversed(boundaries):
        head = s[:cut]
        # recompute open stack for the trimmed head
        h_stack, h_in_str = _scan_stack(head)
        candidate = _close(head, h_in_str, h_stack)
        obj = _try_loads(candidate, want)
        if obj is not None:
            return obj
    return None


def _scan_stack(s: str) -> tuple[list[str], bool]:
    stack: list[str] = []
    in_str = False
    esc = False
    for ch in s:
        if esc:
            esc = False
            continue
        if ch == "\\" and in_str:
            esc = True
            continue
        if ch == '"':
            in_str = not in_str
            continue
        if in_str:
            continue
        if ch in "{[":
            stack.append(ch)
        elif ch in "}]":
            if stack:
                stack.pop()
    return stack, in_str


def _close(s: str, in_str: bool, stack: list[str]) -> str:
    out = s.rstrip()
    if in_str:
        out += '"'
    # drop a dangling comma or ':' left by a partial element
    out = out.rstrip()
    while out and out[-1] in ",:":
        out = out[:-1].rstrip()
    for opener in reversed(stack):
        out += "}" if opener == "{" else "]"
    return out
