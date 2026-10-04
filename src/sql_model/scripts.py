"""SQL script handling: split files into GO-separated batches and resolve engine markers.

A batch whose leading comment lines contain "@tsql-only" runs only on SQL Server;
"@duckdb-only" runs only on the local verification engine. All other batches run on both.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

GO = re.compile(r"^\s*GO\s*;?\s*$", re.IGNORECASE | re.MULTILINE)


@dataclass(frozen=True)
class Batch:
    file: str
    index: int
    text: str
    target: str           # "both", "tsql" or "duckdb"

    def runs_on(self, engine: str) -> bool:
        return self.target == "both" or (self.target == "tsql" and engine == "mssql") or \
            (self.target == "duckdb" and engine == "duckdb")


def strip_comments(text: str) -> str:
    """Remove /* */ blocks and -- comments (the scripts never put these inside string literals)."""
    no_block = re.sub(r"/\*.*?\*/", "", text, flags=re.DOTALL)
    return "\n".join(re.sub(r"--.*$", "", ln) for ln in no_block.splitlines())


def _code_lines(text: str) -> list[str]:
    """Lines that are not blank, not -- comments and not inside /* */ blocks."""
    no_block = re.sub(r"/\*.*?\*/", "", text, flags=re.DOTALL)
    return [ln for ln in no_block.splitlines() if ln.strip() and not ln.strip().startswith("--")]


def split_batches(path: Path) -> list[Batch]:
    text = Path(path).read_text(encoding="utf-8")
    out = []
    for i, chunk in enumerate(GO.split(text)):
        if not _code_lines(chunk):
            continue
        lead = re.sub(r"/\*.*?\*/", "", chunk, flags=re.DOTALL).split("\n")
        header = []
        for ln in lead:
            s = ln.strip()
            if not s or s.startswith("--"):
                header.append(s)
            else:
                break
        head = " ".join(header)
        target = "tsql" if "@tsql-only" in head else "duckdb" if "@duckdb-only" in head else "both"
        out.append(Batch(file=Path(path).name, index=i, text=chunk.strip(), target=target))
    return out
