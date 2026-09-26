"""
The repository must not carry anybody's filesystem, user id, or a binary.

This is a regression gate, not a style check. The source tree was assembled
from a shared cluster directory that embedded one teammate's DTU user id
thousands of times, and licence-restricted software sat one directory away.
Both are the kind of thing that comes back the next time someone copies a
file in, so it is asserted rather than remembered.
"""
import re
import subprocess

from conftest import REPO_ROOT

# Cluster paths and DTU-style user ids.
FORBIDDEN_TEXT = re.compile(
    r"/work3/|/zhome/|/dtu/|\bs2\d{5}\b|\bc2\d{4}\b|/Users/[a-z]",
    re.IGNORECASE,
)

# Committed binaries and licence-restricted software. iGEM requires that the
# source produce the output, and FoldX may not be redistributed at all.
FORBIDDEN_NAMES = (
    "*.jar", "*.zip", "*.exe", "*.bin", "*.o", "*.a", "*.so",
    "*.pt", "*.ckpt", "foldx*",
)


def _tracked_files():
    out = subprocess.run(
        ["git", "-C", str(REPO_ROOT), "ls-files"],
        capture_output=True, text=True, check=True,
    )
    return [REPO_ROOT / line for line in out.stdout.splitlines() if line]


def test_no_machine_specific_paths():
    offenders = []
    for path in _tracked_files():
        if path.name == "test_no_machine_paths.py":
            continue  # this file names the patterns on purpose
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, FileNotFoundError):
            continue
        for lineno, line in enumerate(text.splitlines(), 1):
            if FORBIDDEN_TEXT.search(line):
                rel = path.relative_to(REPO_ROOT)
                offenders.append(f"{rel}:{lineno}: {line.strip()[:100]}")
    assert not offenders, (
        "machine-specific paths or user ids found:\n  " + "\n  ".join(offenders)
    )


def test_no_binaries_or_licence_restricted_files():
    import fnmatch

    offenders = [
        str(p.relative_to(REPO_ROOT))
        for p in _tracked_files()
        if any(fnmatch.fnmatch(p.name.lower(), pat) for pat in FORBIDDEN_NAMES)
    ]
    assert not offenders, (
        "binary or licence-restricted files are tracked:\n  " + "\n  ".join(offenders)
    )
