"""Shared no-link output policy for CLI and MCP recipe artifacts."""

from __future__ import annotations

import os
import stat
from pathlib import Path

from photonic_workflow.exceptions import InvalidInputError, SecurityViolationError
from photonic_workflow.security import ensure_within_allowed_roots


def checked_recipe_output(project_root: Path, output: Path) -> tuple[Path, str]:
    root = project_root.resolve()
    candidate = output if output.is_absolute() else root / output
    lexical = Path(os.path.abspath(candidate))
    checked = ensure_within_allowed_roots(lexical, [root])
    if checked == root:
        raise InvalidInputError("recipe output must be a file below project root")

    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    cursor = lexical
    while os.path.normcase(str(cursor)) != os.path.normcase(str(root)):
        if cursor.exists() or cursor.is_symlink():
            details = cursor.lstat()
            attributes = getattr(details, "st_file_attributes", 0)
            if cursor.is_symlink() or attributes & reparse_flag:
                raise SecurityViolationError(
                    f"recipe output path contains a symlink or junction: {cursor}"
                )
        parent = cursor.parent
        if parent == cursor:
            raise InvalidInputError("recipe output is not lexically below project root")
        cursor = parent
    return checked, checked.relative_to(root).as_posix()
