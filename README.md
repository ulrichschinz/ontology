# Ontology Skill

A typed knowledge graph for structured agent memory and composable skills.

## Origin

This skill is based on [oswalpalash/ontology](https://clawhub.ai/oswalpalash/ontology) from ClaWHub. The original skill provided a typed vocabulary and constraint system for representing knowledge as a verifiable graph, using a JSONL flat file as its storage backend.

## What It Does

The ontology skill gives Claude agents a persistent, structured memory store. Everything is an **entity** with a type, properties, and typed relations to other entities. Every write is validated against schema constraints before committing.

**Core entity types:** Person, Organization, Project, Task, Goal, Event, Location, Document, Message, Thread, Note, Account, Device, Credential, Action, Policy

**Trigger phrases:** "remember that...", "what do I know about X?", "link X to Y", "show dependencies", "find anything about...", entity CRUD, cross-skill state sharing.

## Improvements over the Original

This version replaces the flat-file backend with two purpose-built databases:

### Kùzu (graph database)
- Replaces the JSONL flat file with an embedded graph database (no server required)
- Native Cypher query language for graph traversal and cycle detection
- O(1) entity lookups — no full-graph scan per operation
- Safe concurrent access by multiple agents
- Data persists in `memory/ontology/graph/`

### LanceDB (vector database, optional)
- Every entity written to Kùzu is automatically mirrored as a vector embedding
- Enables semantic/fuzzy search across all entities by natural language query
- Uses `sentence-transformers/all-MiniLM-L6-v2` (CPU-only, ~90 MB on first use)
- Override embedding model via `ONTOLOGY_EMBED_MODEL` environment variable
- Data persists in `memory/ontology/vectors/`
- All graph operations work normally without LanceDB; only the `search` command requires it

## Quick Start

```bash
# Install and initialize
python3 scripts/ontology.py setup --install

# Optional: add semantic search support
python3 scripts/ontology.py setup --install --with-search

# Create an entity
python3 scripts/ontology.py create --type Person --props '{"name":"Alice","email":"alice@example.com"}'

# Query
python3 scripts/ontology.py query --type Task --where '{"status":"open"}'

# Link entities
python3 scripts/ontology.py relate --from proj_001 --rel has_task --to task_001

# Semantic search (requires LanceDB)
python3 scripts/ontology.py search --query "deployment issues last week"
```

## Data Layout

```
memory/
  ontology/
    graph/      ← Kùzu database directory
    vectors/    ← LanceDB database directory (optional)
    schema.yaml ← Type definitions and constraints
```

All data lives in `memory/ontology/` relative to your workspace root. Add it to `.gitignore` if you don't want to commit graph data.

## References

- `SKILL.md` — Full skill documentation and workflow examples
- `references/schema.md` — Complete type definitions and constraint patterns
- `references/queries.md` — Query language and traversal examples
- `requirements.txt` — Python dependencies
