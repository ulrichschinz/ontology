# Query Reference

Query patterns and graph traversal examples for ontology v2 (Kùzu + LanceDB).

## Basic Queries

### Get by ID

```bash
python3 scripts/ontology.py get --id task_001
```

### List by Type

```bash
# All tasks
python3 scripts/ontology.py list --type Task

# All people
python3 scripts/ontology.py list --type Person

# All entities (no type filter)
python3 scripts/ontology.py list
```

### Filter by Properties

```bash
# Open tasks
python3 scripts/ontology.py query --type Task --where '{"status":"open"}'

# High priority tasks
python3 scripts/ontology.py query --type Task --where '{"priority":"high"}'

# Tasks assigned to specific person (by property)
python3 scripts/ontology.py query --type Task --where '{"assignee":"p_001"}'
```

## Relation Queries

### Get Related Entities

```bash
# Tasks belonging to a project (outgoing)
python3 scripts/ontology.py related --id proj_001 --rel has_task

# What projects does this task belong to (incoming)
python3 scripts/ontology.py related --id task_001 --rel part_of --dir incoming

# All relations for an entity (both directions)
python3 scripts/ontology.py related --id p_001 --dir both
```

### Common Patterns

```bash
# Who owns this project?
python3 scripts/ontology.py related --id proj_001 --rel has_owner

# What events is this person attending?
python3 scripts/ontology.py related --id p_001 --rel attendee_of --dir outgoing

# What's blocking this task?
python3 scripts/ontology.py related --id task_001 --rel blocked_by --dir incoming
```

## Semantic Search

Semantic search uses LanceDB vector embeddings to find entities by meaning,
not just exact property matches. Requires `pip install lancedb sentence-transformers`.

```bash
# Find anything related to deployment issues
python3 scripts/ontology.py search --query "deployment issues last week"

# Find people involved with a project
python3 scripts/ontology.py search --query "website project owner" --type Person

# Find tasks about authentication
python3 scripts/ontology.py search --query "authentication bugs" --type Task --limit 5
```

Search results include a `score` field (lower = more similar) and the full entity
`properties` for display.

Semantic search complements structured queries — use `query`/`related` when you know
exact property values, use `search` when you want fuzzy recall by topic.

## Query Patterns by Use Case

### Task Management

```bash
# All my open tasks
python3 scripts/ontology.py query --type Task --where '{"status":"open","assignee":"p_me"}'

# High priority open tasks
python3 scripts/ontology.py query --type Task --where '{"status":"open","priority":"high"}'

# Tasks with no blockers (get all open, filter in calling code)
python3 scripts/ontology.py query --type Task --where '{"status":"open"}'
```

### Project Overview

```bash
# All tasks in project
python3 scripts/ontology.py related --id proj_001 --rel has_task

# Project team members
python3 scripts/ontology.py related --id proj_001 --rel has_member

# Project goals
python3 scripts/ontology.py related --id proj_001 --rel has_goal
```

### People & Contacts

```bash
# All people
python3 scripts/ontology.py list --type Person

# People in an organization
python3 scripts/ontology.py related --id org_001 --rel has_member

# What's assigned to this person
python3 scripts/ontology.py related --id p_001 --rel assigned_to --dir incoming
```

### Events & Calendar

```bash
# All events
python3 scripts/ontology.py list --type Event

# Events at a location
python3 scripts/ontology.py related --id loc_001 --rel located_at --dir incoming

# Event attendees
python3 scripts/ontology.py related --id event_001 --rel attendee_of --dir incoming
```

## Programmatic Use via kuzu_backend

For scripts that need direct backend access, use `kuzu_backend` functions:

```python
import sys
sys.path.insert(0, "scripts/")
import kuzu_backend

conn = kuzu_backend.init_db("memory/ontology/graph")

# Query entities
open_tasks = kuzu_backend.query_entities(conn, "Task", {"status": "open"})

# Get related
project_tasks = kuzu_backend.get_related(conn, "proj_001", "has_task", "outgoing")

# Validate
errors = kuzu_backend.validate_graph(conn, "memory/ontology/schema.yaml")
```

For aggregations, iterate over the returned lists in Python:

```python
from collections import Counter

def task_status_summary(project_id: str) -> dict:
    """Count tasks by status for a project."""
    tasks = kuzu_backend.get_related(conn, project_id, "has_task", "outgoing")
    statuses = Counter(t["entity"]["properties"].get("status", "unknown") for t in tasks)
    return dict(statuses)

def workload_by_person() -> dict:
    """Count open tasks per assignee."""
    open_tasks = kuzu_backend.query_entities(conn, "Task", {"status": "open"})
    workload = Counter(t["properties"].get("assignee") for t in open_tasks)
    return dict(workload)
```

For semantic aggregations, combine structured and vector queries:

```python
import lance_backend

table = lance_backend.init_lance("memory/ontology/vectors")

# Find tasks related to a theme
relevant = lance_backend.semantic_search(table, "database performance", limit=20, type_filter="Task")

# Cross-reference with structured status
open_relevant = [r for r in relevant if r["properties"].get("status") == "open"]
```
