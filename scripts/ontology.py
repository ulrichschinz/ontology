#!/usr/bin/env python3
"""
Ontology graph operations: create, query, relate, validate, search.

Usage:
    python3 ontology.py setup               # check prerequisites
    python3 ontology.py setup --install     # install required packages + create dirs
    python3 ontology.py setup --install --with-search  # also install optional search deps
    python3 ontology.py create --type Person --props '{"name":"Alice"}'
    python3 ontology.py get --id p_001
    python3 ontology.py query --type Task --where '{"status":"open"}'
    python3 ontology.py relate --from proj_001 --rel has_task --to task_001
    python3 ontology.py related --id proj_001 --rel has_task
    python3 ontology.py list --type Person
    python3 ontology.py update --id p_001 --props '{"email":"new@example.com"}'
    python3 ontology.py delete --id p_001
    python3 ontology.py validate
    python3 ontology.py schema-append --data '{"types":{"Task":{"required":["title"]}}}'
    python3 ontology.py search --query "deployment issues last week" --limit 10 --type Task

Storage (all paths relative to the workspace root where this is invoked):
    Graph:   memory/ontology/graph/   (Kùzu database directory — auto-created)
    Vectors: memory/ontology/vectors/ (LanceDB directory — auto-created, optional)
    Schema:  memory/ontology/schema.yaml

All query results and entity data go to stdout as valid JSON.
All errors, warnings, and debug output go to stderr.
"""

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Optional

# Add the scripts directory to path so backend modules can be imported
# when this script is invoked as `python3 scripts/ontology.py ...`
_SCRIPTS_DIR = Path(__file__).resolve().parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

DEFAULT_GRAPH_PATH = "memory/ontology/graph"
DEFAULT_VECTORS_PATH = "memory/ontology/vectors"
DEFAULT_SCHEMA_PATH = "memory/ontology/schema.yaml"


# ---------------------------------------------------------------------------
# Path safety (retained verbatim from 1.0.4)
# ---------------------------------------------------------------------------

def resolve_safe_path(
    user_path: str,
    *,
    root: Optional[Path] = None,
    must_exist: bool = False,
    label: str = "path",
) -> Path:
    """Resolve user path within root and reject traversal outside it."""
    if not user_path or not user_path.strip():
        raise SystemExit(f"Invalid {label}: empty path")

    safe_root = (root or Path.cwd()).resolve()
    candidate = Path(user_path).expanduser()
    if not candidate.is_absolute():
        candidate = safe_root / candidate

    try:
        resolved = candidate.resolve(strict=False)
    except OSError as exc:
        raise SystemExit(f"Invalid {label}: {exc}") from exc

    try:
        resolved.relative_to(safe_root)
    except ValueError:
        raise SystemExit(
            f"Invalid {label}: must stay within workspace root '{safe_root}'"
        )

    if must_exist and not resolved.exists():
        raise SystemExit(f"Invalid {label}: file not found '{resolved}'")

    return resolved


# ---------------------------------------------------------------------------
# LanceDB sync helpers (fail-graceful wrappers)
# ---------------------------------------------------------------------------

def _sync_lance(entity: dict, vectors_path: str) -> None:
    """Mirror entity to LanceDB after a write. Silently skips if not installed."""
    try:
        import lance_backend
        if not lance_backend.LANCE_AVAILABLE or not lance_backend.ST_AVAILABLE:
            return
        table = lance_backend.init_lance(vectors_path)
        lance_backend.upsert_entity(table, entity)
    except ImportError:
        pass
    except Exception as exc:
        print(f"WARNING: LanceDB sync failed: {exc}", file=sys.stderr)


def _delete_lance(entity_id: str, vectors_path: str) -> None:
    """Remove entity from LanceDB after a delete. Silently skips if not installed."""
    try:
        import lance_backend
        if not lance_backend.LANCE_AVAILABLE:
            return
        table = lance_backend.init_lance(vectors_path)
        lance_backend.delete_entity(table, entity_id)
    except ImportError:
        pass
    except Exception as exc:
        print(f"WARNING: LanceDB delete failed: {exc}", file=sys.stderr)


# ---------------------------------------------------------------------------
# Setup / prerequisites check
# ---------------------------------------------------------------------------

_REQUIRED_PACKAGES = [
    ("kuzu", "kuzu>=0.9.0", "Graph database backend — required for all operations"),
    ("yaml", "pyyaml>=6.0", "YAML schema files — required for schema-append and validate"),
]

_OPTIONAL_PACKAGES = [
    ("lancedb", "lancedb>=0.20.0", "Vector database — enables `search` command"),
    (
        "sentence_transformers",
        "sentence-transformers>=3.0.0",
        "Embedding model — enables `search` command",
    ),
]

_MIN_PYTHON = (3, 9)


def _check_import(module_name: str) -> bool:
    """Return True if the module can be imported."""
    import importlib.util
    return importlib.util.find_spec(module_name) is not None


def _pip_install(pip_spec: str) -> bool:
    """Run pip install for the given spec. Returns True on success."""
    result = subprocess.run(
        [sys.executable, "-m", "pip", "install", pip_spec],
        capture_output=True,
        text=True,
    )
    return result.returncode == 0


def _run_setup(args, workspace_root: Path) -> None:
    """Check (and optionally install) all prerequisites, create data directories."""
    ok = True

    # --- Python version ---
    ver = sys.version_info
    if ver < _MIN_PYTHON:
        print(
            f"  [FAIL] Python {'.'.join(str(v) for v in _MIN_PYTHON)}+ required, "
            f"found {ver.major}.{ver.minor}.{ver.micro}"
        )
        ok = False
    else:
        print(f"  [OK]   Python {ver.major}.{ver.minor}.{ver.micro}")

    # --- Required packages ---
    print("\nRequired packages:")
    for module, pip_spec, description in _REQUIRED_PACKAGES:
        installed = _check_import(module)
        if installed:
            print(f"  [OK]   {pip_spec}  —  {description}")
        elif args.install:
            print(f"  [...] Installing {pip_spec}  —  {description}")
            if _pip_install(pip_spec):
                print(f"  [OK]   {pip_spec} installed successfully")
            else:
                print(f"  [FAIL] Could not install {pip_spec}. Run manually: pip install {pip_spec}")
                ok = False
        else:
            print(f"  [MISS] {pip_spec}  —  {description}")
            print(f"         Install with: pip install {pip_spec}")
            ok = False

    # --- Optional packages ---
    print("\nOptional packages (semantic search):")
    for module, pip_spec, description in _OPTIONAL_PACKAGES:
        installed = _check_import(module)
        if installed:
            print(f"  [OK]   {pip_spec}  —  {description}")
        elif args.install and args.with_search:
            print(f"  [...] Installing {pip_spec}  —  {description}")
            if _pip_install(pip_spec):
                print(f"  [OK]   {pip_spec} installed successfully")
            else:
                print(f"  [WARN] Could not install {pip_spec}. Run manually: pip install {pip_spec}")
        else:
            status = "MISS" if args.install else "skip"
            print(f"  [{status}] {pip_spec}  —  {description}")
            if not installed and not args.with_search:
                print(f"         To install: python3 scripts/ontology.py setup --install --with-search")

    # --- Data directories ---
    print("\nData directories (relative to workspace root):")
    dirs = [
        (args.graph, "Kùzu graph database", True),
        (args.vectors, "LanceDB vector index (optional)", False),
    ]
    for dir_path, label, required in dirs:
        path = Path(dir_path)
        if path.exists():
            print(f"  [OK]   {path}  —  {label}")
        else:
            path.mkdir(parents=True, exist_ok=True)
            print(f"  [NEW]  {path}  —  {label} (created)")

    # Schema file — just note its expected location, don't create it
    schema_path = workspace_root / DEFAULT_SCHEMA_PATH
    if schema_path.exists():
        print(f"  [OK]   {DEFAULT_SCHEMA_PATH}  —  Schema definitions")
    else:
        print(f"  [--]   {DEFAULT_SCHEMA_PATH}  —  Schema definitions (not yet created; use schema-append)")

    # --- .gitignore advice ---
    gitignore = workspace_root / ".gitignore"
    gitignore_note = "memory/ontology/" not in (gitignore.read_text() if gitignore.exists() else "")
    if gitignore_note:
        print(
            "\n  TIP: Add memory/ontology/ to your .gitignore to avoid committing graph data:\n"
            "       echo 'memory/ontology/' >> .gitignore"
        )

    # --- Summary ---
    print()
    if ok:
        print("Setup complete. The ontology skill is ready to use.")
        print("Next step: python3 scripts/ontology.py create --type Person --props '{\"name\":\"Alice\"}'")
    else:
        print("Setup incomplete — install missing required packages above, then re-run `setup`.")
        sys.exit(1)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="Ontology graph operations")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # Setup / prerequisites check
    setup_p = subparsers.add_parser(
        "setup",
        help="Check prerequisites, create data directories, optionally install packages",
    )
    setup_p.add_argument(
        "--install",
        action="store_true",
        help="Install missing required packages with pip",
    )
    setup_p.add_argument(
        "--with-search",
        action="store_true",
        dest="with_search",
        help="Also install optional semantic search packages (lancedb, sentence-transformers)",
    )
    setup_p.add_argument("--graph", "-g", default=DEFAULT_GRAPH_PATH)
    setup_p.add_argument("--vectors", default=DEFAULT_VECTORS_PATH)

    # Create
    create_p = subparsers.add_parser("create", help="Create entity")
    create_p.add_argument("--type", "-t", required=True, help="Entity type")
    create_p.add_argument("--props", "-p", default="{}", help="Properties JSON")
    create_p.add_argument("--id", help="Entity ID (auto-generated if not provided)")
    create_p.add_argument("--graph", "-g", default=DEFAULT_GRAPH_PATH)
    create_p.add_argument("--vectors", default=DEFAULT_VECTORS_PATH)

    # Get
    get_p = subparsers.add_parser("get", help="Get entity by ID")
    get_p.add_argument("--id", required=True, help="Entity ID")
    get_p.add_argument("--graph", "-g", default=DEFAULT_GRAPH_PATH)

    # Query
    query_p = subparsers.add_parser("query", help="Query entities")
    query_p.add_argument("--type", "-t", help="Entity type")
    query_p.add_argument("--where", "-w", default="{}", help="Filter JSON")
    query_p.add_argument("--graph", "-g", default=DEFAULT_GRAPH_PATH)

    # List
    list_p = subparsers.add_parser("list", help="List entities")
    list_p.add_argument("--type", "-t", help="Entity type")
    list_p.add_argument("--graph", "-g", default=DEFAULT_GRAPH_PATH)

    # Update
    update_p = subparsers.add_parser("update", help="Update entity properties")
    update_p.add_argument("--id", required=True, help="Entity ID")
    update_p.add_argument("--props", "-p", required=True, help="Properties JSON")
    update_p.add_argument("--graph", "-g", default=DEFAULT_GRAPH_PATH)
    update_p.add_argument("--vectors", default=DEFAULT_VECTORS_PATH)

    # Delete
    delete_p = subparsers.add_parser("delete", help="Delete entity")
    delete_p.add_argument("--id", required=True, help="Entity ID")
    delete_p.add_argument("--graph", "-g", default=DEFAULT_GRAPH_PATH)
    delete_p.add_argument("--vectors", default=DEFAULT_VECTORS_PATH)

    # Relate
    relate_p = subparsers.add_parser("relate", help="Create relation")
    relate_p.add_argument("--from", dest="from_id", required=True, help="From entity ID")
    relate_p.add_argument("--rel", "-r", required=True, help="Relation type")
    relate_p.add_argument("--to", dest="to_id", required=True, help="To entity ID")
    relate_p.add_argument("--props", "-p", default="{}", help="Relation properties JSON")
    relate_p.add_argument("--graph", "-g", default=DEFAULT_GRAPH_PATH)

    # Related
    related_p = subparsers.add_parser("related", help="Get related entities")
    related_p.add_argument("--id", required=True, help="Entity ID")
    related_p.add_argument("--rel", "-r", help="Relation type filter")
    related_p.add_argument(
        "--dir", "-d",
        choices=["outgoing", "incoming", "both"],
        default="outgoing",
    )
    related_p.add_argument("--graph", "-g", default=DEFAULT_GRAPH_PATH)

    # Validate
    validate_p = subparsers.add_parser("validate", help="Validate graph against schema")
    validate_p.add_argument("--graph", "-g", default=DEFAULT_GRAPH_PATH)
    validate_p.add_argument("--schema", "-s", default=DEFAULT_SCHEMA_PATH)

    # Schema append
    schema_p = subparsers.add_parser("schema-append", help="Append/merge schema fragment")
    schema_p.add_argument("--schema", "-s", default=DEFAULT_SCHEMA_PATH)
    schema_p.add_argument("--data", "-d", help="Schema fragment as JSON")
    schema_p.add_argument("--file", "-f", help="Schema fragment file (YAML or JSON)")

    # Search (semantic, requires LanceDB)
    search_p = subparsers.add_parser(
        "search", help="Semantic search (requires lancedb + sentence-transformers)"
    )
    search_p.add_argument("--query", "-q", required=True, help="Natural language query")
    search_p.add_argument("--limit", "-l", type=int, default=10, help="Max results")
    search_p.add_argument("--type", "-t", help="Filter by entity type")
    search_p.add_argument("--vectors", default=DEFAULT_VECTORS_PATH)

    args = parser.parse_args()
    workspace_root = Path.cwd().resolve()

    # Resolve all user-supplied paths safely within the workspace root.
    if hasattr(args, "graph"):
        args.graph = str(
            resolve_safe_path(args.graph, root=workspace_root, label="graph path")
        )
    if hasattr(args, "vectors"):
        args.vectors = str(
            resolve_safe_path(args.vectors, root=workspace_root, label="vectors path")
        )
    if hasattr(args, "schema"):
        args.schema = str(
            resolve_safe_path(args.schema, root=workspace_root, label="schema path")
        )
    if hasattr(args, "file") and args.file:
        args.file = str(
            resolve_safe_path(
                args.file, root=workspace_root, must_exist=True, label="schema file"
            )
        )

    # Resolve default schema path for commands that don't expose --schema
    # (used internally for forbidden-property checks at write time).
    default_schema = str(
        resolve_safe_path(DEFAULT_SCHEMA_PATH, root=workspace_root, label="schema path")
    )

    # -----------------------------------------------------------------------
    # Command dispatch
    # -----------------------------------------------------------------------

    if args.command == "setup":
        _run_setup(args, workspace_root)
        return

    # kuzu_backend is only imported after setup has had the chance to install kuzu.
    import kuzu_backend  # noqa: E402

    if args.command == "create":
        props = json.loads(args.props)
        conn = kuzu_backend.init_db(args.graph)
        entity = kuzu_backend.create_entity(conn, args.type, props, default_schema, args.id)
        _sync_lance(entity, args.vectors)
        print(json.dumps(entity, indent=2))

    elif args.command == "get":
        conn = kuzu_backend.init_db(args.graph)
        entity = kuzu_backend.get_entity(conn, args.id)
        if entity:
            print(json.dumps(entity, indent=2))
        else:
            print(f"Entity not found: {args.id}")

    elif args.command == "query":
        where = json.loads(args.where)
        conn = kuzu_backend.init_db(args.graph)
        results = kuzu_backend.query_entities(conn, args.type, where)
        print(json.dumps(results, indent=2))

    elif args.command == "list":
        conn = kuzu_backend.init_db(args.graph)
        results = kuzu_backend.list_entities(conn, args.type)
        print(json.dumps(results, indent=2))

    elif args.command == "update":
        props = json.loads(args.props)
        conn = kuzu_backend.init_db(args.graph)
        entity = kuzu_backend.update_entity(conn, args.id, props, default_schema)
        if entity:
            _sync_lance(entity, args.vectors)
            print(json.dumps(entity, indent=2))
        else:
            print(f"Entity not found: {args.id}")

    elif args.command == "delete":
        conn = kuzu_backend.init_db(args.graph)
        if kuzu_backend.delete_entity(conn, args.id):
            _delete_lance(args.id, args.vectors)
            print(f"Deleted: {args.id}")
        else:
            print(f"Entity not found: {args.id}")

    elif args.command == "relate":
        props = json.loads(args.props)
        conn = kuzu_backend.init_db(args.graph)
        rel = kuzu_backend.create_relation(conn, args.from_id, args.rel, args.to_id, props)
        print(json.dumps(rel, indent=2))

    elif args.command == "related":
        conn = kuzu_backend.init_db(args.graph)
        results = kuzu_backend.get_related(conn, args.id, args.rel, args.dir)
        print(json.dumps(results, indent=2))

    elif args.command == "validate":
        conn = kuzu_backend.init_db(args.graph)
        errors = kuzu_backend.validate_graph(conn, args.schema)
        if errors:
            print("Validation errors:", file=sys.stderr)
            for err in errors:
                print(f"  - {err}", file=sys.stderr)
            sys.exit(1)
        else:
            print("Graph is valid.")

    elif args.command == "schema-append":
        if not args.data and not args.file:
            raise SystemExit("schema-append requires --data or --file")

        incoming: dict = {}
        if args.data:
            incoming = json.loads(args.data)
        else:
            path = Path(args.file)
            if path.suffix.lower() == ".json":
                with open(path) as f:
                    incoming = json.load(f)
            else:
                import yaml
                with open(path) as f:
                    incoming = yaml.safe_load(f) or {}

        merged = kuzu_backend.append_schema(args.schema, incoming)
        print(json.dumps(merged, indent=2))

    elif args.command == "search":
        try:
            import lance_backend
        except ImportError:
            print(
                "ERROR: Semantic search requires lancedb and sentence-transformers.\n"
                "Install with: pip install lancedb sentence-transformers",
                file=sys.stderr,
            )
            sys.exit(1)

        if not lance_backend.LANCE_AVAILABLE or not lance_backend.ST_AVAILABLE:
            print(
                "ERROR: Semantic search requires lancedb and sentence-transformers.\n"
                "Install with: pip install lancedb sentence-transformers",
                file=sys.stderr,
            )
            sys.exit(1)

        table = lance_backend.init_lance(args.vectors)
        results = lance_backend.semantic_search(table, args.query, args.limit, args.type)
        print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
