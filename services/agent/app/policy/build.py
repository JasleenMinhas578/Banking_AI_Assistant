"""`make policies`: chunk the policy files, scan each chunk, embed, save the index.

    cd services/agent && uv run python -m app.policy.build

Only changed files are re-embedded (a hash per file is kept in the index). Every
chunk and FAQ is scanned with moderation tiers 1 and 2 first, so a poisoned
document with hidden instructions is caught before it can ever be retrieved.
"""

import asyncio
import hashlib
from pathlib import Path

import yaml

from app.config import Settings, settings
from app.policy.chunker import chunk_policy
from app.policy.embeddings import OllamaEmbedder
from app.policy.index import Faq, PolicyIndex
from app.safety.classifier import SklearnClassifier
from app.safety.rules import RulesModerator
from app.safety.types import Label


class PoisonedDocument(Exception):
    pass


CLASSIFIER_HARD_STOP = (
    0.97  # policy prose talks *about* PINs and agents; only a near-certain hit stops
)


def scan(texts: list[str], config: Settings) -> None:
    """Rules stop the build. The classifier stops it only when near-certain, warns otherwise."""
    rules = RulesModerator()
    classifier = SklearnClassifier.load(config.moderation_model_dir)
    for text in texts:
        if rules.check(text).label == Label.PROMPT_INJECTION:
            raise PoisonedDocument(f"rules flagged: {text[:80]!r}")
        if classifier:
            guess = classifier.predict(text)
            if guess.label == Label.PROMPT_INJECTION and guess.score >= CLASSIFIER_HARD_STOP:
                raise PoisonedDocument(f"classifier flagged ({guess.score:.2f}): {text[:80]!r}")
            if guess.label == Label.PROMPT_INJECTION and guess.score >= classifier.threshold:
                print(
                    f"  warning: looks like an instruction ({guess.score:.2f}), check it: "
                    f"{text[:70]!r}"
                )


async def build(config: Settings, folder: Path, out: Path) -> PolicyIndex:
    embedder = OllamaEmbedder(config.embed_model, config.ollama_base_url)
    index = PolicyIndex(embed_model=config.embed_model)
    old = PolicyIndex.load(out) if out.is_file() and out.stat().st_size else None
    if old and old.embed_model != config.embed_model:
        old = None

    for path in sorted(folder.glob("POL-*.md")):
        text = path.read_text()
        digest = hashlib.sha256(text.encode()).hexdigest()
        chunks = chunk_policy(text)
        reuse = old and old.file_hashes.get(path.name) == digest
        if reuse and old:
            kept = [
                (c, v)
                for c, v in zip(old.chunks, old.chunk_vectors, strict=True)
                if c.policy_id == chunks[0].policy_id
            ]
            vectors = [v for _, v in kept]
            chunks = [c for c, _ in kept]
            print(f"  {path.name}: unchanged, {len(chunks)} chunks kept")
        else:
            scan([c.text for c in chunks], config)
            vectors = await embedder.embed([f"{c.title}: {c.section}\n{c.text}" for c in chunks])
            print(f"  {path.name}: {len(chunks)} chunks embedded")
        index.chunks.extend(chunks)
        index.chunk_vectors.extend(vectors)
        index.file_hashes[path.name] = digest

    faq_file = folder / "faq.yaml"
    if faq_file.is_file():
        entries = yaml.safe_load(faq_file.read_text()) or []
        index.faqs = [Faq(e["question"], e["answer"], e["policy_id"]) for e in entries]
        scan([f"{f.question} {f.answer}" for f in index.faqs], config)
        index.faq_vectors = await embedder.embed([f.question for f in index.faqs])
        print(f"  faq.yaml: {len(index.faqs)} approved answers embedded")

    index.save(out)
    print(f"Saved {len(index.chunks)} chunks and {len(index.faqs)} FAQs to {out}")
    return index


def main() -> None:
    asyncio.run(build(settings, settings.policy_dir, settings.policy_index_path))


if __name__ == "__main__":
    main()
