#!/usr/bin/env python3
"""
LanceDB semantic vector layer for the ontology skill.

Optional — the skill functions fully without this module.
If lancedb or sentence-transformers are not installed the import fails
gracefully and all write operations continue using Kùzu alone.

Storage: memory/ontology/vectors/ (a LanceDB directory)
Table:   "entities" with schema {id, type, text, vector, properties}

Embedding model: sentence-transformers/all-MiniLM-L6-v2 (default, ~90 MB,
CPU-only, no API key). Override with the ONTOLOGY_EMBED_MODEL env var.
"""

import json
import os
import sys
from pathlib import Path
from typing import Optional

# ---------------------------------------------------------------------------
# Optional dependency detection
# ---------------------------------------------------------------------------

try:
    import lancedb as _lancedb
    LANCE_AVAILABLE = True
except ImportError:
    LANCE_AVAILABLE = False

try:
    from sentence_transformers import SentenceTransformer as _SentenceTransformer
    ST_AVAILABLE = True
except ImportError:
    ST_AVAILABLE = False

TABLE_NAME = "entities"

# Module-level model singleton — loaded lazily on first use.
_MODEL = None


# ---------------------------------------------------------------------------
# Text conversion
# ---------------------------------------------------------------------------

def entity_to_text(entity: dict) -> str:
    """Convert an entity dict to an embeddable natural-language string.

    Example output:
        "Type: Task. Title: Fix deployment. Status: open. Priority: high."
    """
    parts = [f"Type: {entity.get('type', 'Unknown')}."]
    for key, value in entity.get("properties", {}).items():
        if value is None or value == "":
            continue
        label = key.replace("_", " ").title()
        if isinstance(value, list):
            parts.append(f"{label}: {', '.join(str(v) for v in value)}.")
        elif isinstance(value, (str, int, float, bool)):
            parts.append(f"{label}: {value}.")
    return " ".join(parts)


# ---------------------------------------------------------------------------
# Model access
# ---------------------------------------------------------------------------

def _get_model() -> "_SentenceTransformer":
    global _MODEL
    if _MODEL is None:
        if not ST_AVAILABLE:
            raise ImportError(
                "sentence-transformers is not installed. "
                "Install with: pip install sentence-transformers"
            )
        model_name = os.environ.get(
            "ONTOLOGY_EMBED_MODEL",
            "sentence-transformers/all-MiniLM-L6-v2",
        )
        print(
            f"INFO: Loading embedding model '{model_name}' "
            "(first use — ~90 MB download if not cached).",
            file=sys.stderr,
        )
        _MODEL = _SentenceTransformer(model_name)
    return _MODEL


def _embed(text: str) -> list[float]:
    return _get_model().encode(text).tolist()


# ---------------------------------------------------------------------------
# LanceDB table management
# ---------------------------------------------------------------------------

def init_lance(vectors_dir: str):
    """Open (or create) the LanceDB vector store and return the table object.

    Raises ImportError if lancedb or sentence-transformers are not installed.
    """
    if not LANCE_AVAILABLE:
        raise ImportError(
            "lancedb is not installed. Install with: pip install lancedb"
        )
    if not ST_AVAILABLE:
        raise ImportError(
            "sentence-transformers is not installed. "
            "Install with: pip install sentence-transformers"
        )

    vector_path = Path(vectors_dir)
    vector_path.mkdir(parents=True, exist_ok=True)

    db = _lancedb.connect(str(vector_path))

    if TABLE_NAME not in db.table_names():
        import pyarrow as pa
        dim = _get_model().get_sentence_embedding_dimension()
        schema = pa.schema([
            pa.field("id", pa.string()),
            pa.field("type", pa.string()),
            pa.field("text", pa.string()),
            pa.field("vector", pa.list_(pa.float32(), dim)),
            pa.field("properties", pa.string()),
        ])
        db.create_table(TABLE_NAME, schema=schema)

    return db.open_table(TABLE_NAME)


# ---------------------------------------------------------------------------
# Write operations (called automatically after every Kùzu write)
# ---------------------------------------------------------------------------

def upsert_entity(table, entity: dict) -> None:
    """Insert or replace the entity's vector representation."""
    text = entity_to_text(entity)
    vector = _embed(text)
    record = {
        "id": entity["id"],
        "type": entity["type"],
        "text": text,
        "vector": vector,
        "properties": json.dumps(entity.get("properties", {})),
    }
    # LanceDB: delete existing row then insert (cross-version safe upsert).
    try:
        table.delete(f"id = '{entity['id']}'")
    except Exception:
        pass
    table.add([record])


def delete_entity(table, entity_id: str) -> None:
    """Remove the entity from the vector index."""
    try:
        table.delete(f"id = '{entity_id}'")
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Semantic search
# ---------------------------------------------------------------------------

def semantic_search(
    table,
    query_text: str,
    limit: int = 10,
    type_filter: Optional[str] = None,
) -> list[dict]:
    """Return entities most semantically similar to query_text.

    Results are ordered by ascending distance (most similar first).
    Each result includes: id, type, text, score, properties.
    """
    vector = _embed(query_text)

    fetch_limit = limit * 3 if type_filter else limit
    search = table.search(vector).limit(fetch_limit)

    results = search.to_list()

    output: list[dict] = []
    for row in results:
        if type_filter and row.get("type") != type_filter:
            continue
        output.append({
            "id": row["id"],
            "type": row["type"],
            "text": row["text"],
            "score": float(row.get("_distance", 0.0)),
            "properties": json.loads(row["properties"]),
        })
        if len(output) >= limit:
            break

    return output
