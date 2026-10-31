"""Policy answers: an FAQ cache, then hybrid search over the policy documents, then a
grounded one-sentence answer. Every number spoken must appear in the retrieved text.

    chunker.py     splits data/policies/*.md by heading; a table is never cut
    embeddings.py  nomic-embed-text through Ollama
    index.py       the saved vectors + keyword index, hybrid search, FAQ lookup
    answerer.py    FAQ hit → cached answer; else search → gate → model → grounding check
    build.py       `make policies`: chunk, scan for poisoned text, embed, save
"""
