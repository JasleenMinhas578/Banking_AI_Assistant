"""Turns a policy Markdown file into chunks: one per `##` section, front matter kept."""

import re
from dataclasses import dataclass
from pathlib import Path

_FRONT = re.compile(r"\A---\n(.*?)\n---\n", re.DOTALL)


@dataclass(frozen=True)
class Chunk:
    policy_id: str
    title: str  # the policy's title, e.g. "Fee schedule"
    section: str  # the heading, e.g. "Account fees"
    effective: str
    text: str  # the section's own text, tables included

    @property
    def ref(self) -> str:
        return f"{self.policy_id} · {self.section}"


def parse_front_matter(markdown: str) -> tuple[dict[str, str], str]:
    match = _FRONT.match(markdown)
    if not match:
        return {}, markdown
    fields = {}
    for line in match.group(1).splitlines():
        key, _, value = line.partition(":")
        fields[key.strip()] = value.strip()
    return fields, markdown[match.end() :]


def chunk_policy(markdown: str) -> list[Chunk]:
    """One chunk per `##` section. The intro under the `#` title becomes the first chunk."""
    meta, body = parse_front_matter(markdown)
    policy_id, title = meta.get("policy_id", "?"), meta.get("title", "")
    effective = meta.get("effective", "")
    chunks: list[Chunk] = []
    section = "Overview"
    lines: list[str] = []

    def flush() -> None:
        text = "\n".join(lines).strip()
        if text:
            chunks.append(Chunk(policy_id, title, section, effective, text))

    for line in body.splitlines():
        if line.startswith("# "):
            continue  # the document title: already in `title`
        if line.startswith("## "):
            flush()
            section, lines = line[3:].strip(), []
        else:
            lines.append(line)
    flush()
    return chunks


def load_policies(folder: Path) -> list[Chunk]:
    chunks = []
    for path in sorted(folder.glob("POL-*.md")):
        chunks.extend(chunk_policy(path.read_text()))
    return chunks
