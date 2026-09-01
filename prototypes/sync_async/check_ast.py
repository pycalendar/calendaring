"""CI enforcement for the Sans-I/O pattern (roadmap 1.3 asks for exactly this).

Inside an I/O body (a method named ``_io_*``), there are two ways to reach
another I/O body and only one of them is correct:

    yield from self._io_save()     # correct
    self.save()                    # WRONG - the caldav bug: in async mode this
                                   # builds a coroutine and drops it
    self._io_save()                # WRONG - builds a generator and drops it

This reports both wrong shapes.  It looks *only* inside ``_io_*`` bodies, which
is what keeps it quiet about the typed facades in ``p2_typed.py``: a facade
legitimately hands ``self._io_x()`` to a driver, and a facade is not an I/O
body.

    python check_ast.py p2_sansio.py p2_typed.py     # exit 0
    python check_ast.py p2_sansio_bug.py             # exit 1

Exit code 1 if any violation is found.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path


def _io_bodies(tree: ast.AST) -> list[ast.FunctionDef]:
    return [
        n
        for n in ast.walk(tree)
        if isinstance(n, ast.FunctionDef) and n.name.startswith("_io_")
    ]


def check(path: Path) -> list[tuple[int, str]]:
    tree = ast.parse(path.read_text())
    # Public names that have an I/O body behind them: `_io_save` -> `save`.
    public_names = {
        n.name.removeprefix("_io_") for n in ast.walk(tree)
        if isinstance(n, ast.FunctionDef) and n.name.startswith("_io_")
    }

    violations: list[tuple[int, str]] = []
    for fn in _io_bodies(tree):
        # calls entered correctly, and names that are later `yield from`-ed
        ok_calls: set[int] = set()
        delegated: set[str] = set()
        for node in ast.walk(fn):
            if isinstance(node, ast.YieldFrom):
                if isinstance(node.value, ast.Call):
                    ok_calls.add(id(node.value))
                elif isinstance(node.value, ast.Name):
                    delegated.add(node.value.id)
        # a generator assigned to a name that is later `yield from`-ed is fine
        for node in ast.walk(fn):
            if isinstance(node, ast.Assign) and isinstance(node.value, ast.Call):
                for tgt in node.targets:
                    if isinstance(tgt, ast.Name) and tgt.id in delegated:
                        ok_calls.add(id(node.value))

        for node in ast.walk(fn):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            if not isinstance(func, ast.Attribute):
                continue
            if id(node) in ok_calls:
                continue
            if func.attr.startswith("_io_"):
                violations.append(
                    (node.lineno, f"{func.attr}() in {fn.name}() without 'yield from'")
                )
            elif func.attr in public_names:
                violations.append(
                    (
                        node.lineno,
                        f"{func.attr}() is the public wrapper - in {fn.name}() "
                        f"use 'yield from self._io_{func.attr}()'",
                    )
                )
    return sorted(violations)


def main(argv: list[str]) -> int:
    here = Path(__file__).parent
    args = argv[1:] or ["p2_sansio.py", "p2_typed.py"]
    paths = [Path(a) if Path(a).exists() else here / a for a in args]
    bad = 0
    for p in paths:
        for lineno, msg in check(p):
            print(f"{p.name}:{lineno}: {msg}")
            bad += 1
    if bad:
        print(f"\n{bad} violation(s)")
        return 1
    print(f"OK - no Sans-I/O composition violations in {', '.join(p.name for p in paths)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
