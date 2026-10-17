"""Static dependency and cross-file relationship graph resolver for Python projects.

Guarantees:
- Zero code execution: purely AST-based static relationship matching.
- Safe resolution of common relative imports and unambiguous project-local absolute imports.
- Explicit representation of unresolved and ambiguous relationships.
- Infinite traversal prevention for circular dependencies.
"""

import ast
import logging
import posixpath
from typing import Dict, List, Optional, Set, Tuple

from app.schemas.ast_analysis import (
    AnalyzePythonResponse,
    ImportInfo,
    SourceLocation,
)
from app.schemas.project_analysis import (
    ProjectFileAnalysisResult,
    ProjectRelationship,
    RelationshipType,
    ResolutionStatus,
)

logger = logging.getLogger("apicompass.project.graph_resolver")


def extract_top_level_definitions(source: str, ast_result: AnalyzePythonResponse) -> List[str]:
    """Extract top-level function names, class names, and assigned variable names safely."""
    symbols: Set[str] = set()

    # Add top-level functions
    for fn in ast_result.functions:
        if not fn.enclosing_scope:
            symbols.add(fn.name)

    # Add top-level classes
    for cls in ast_result.classes:
        if not cls.enclosing_scope:
            symbols.add(cls.name)

    # Extract top-level assigned identifiers from AST
    try:
        tree = ast.parse(source)
        for stmt in tree.body:
            if isinstance(stmt, ast.Assign):
                for target in stmt.targets:
                    if isinstance(target, ast.Name):
                        symbols.add(target.id)
            elif isinstance(stmt, ast.AnnAssign):
                if isinstance(stmt.target, ast.Name):
                    symbols.add(stmt.target.id)
    except Exception:
        # If AST parsing fails, fallback to what visitor collected
        pass

    return sorted(symbols)


class ProjectGraphResolver:
    """Statically resolves cross-file dependencies and relationships across a collection of Python files."""

    def __init__(
        self,
        files_data: Dict[str, str],
        ast_results: Dict[str, AnalyzePythonResponse],
    ) -> None:
        """Initialize resolver with normalized relative paths, raw contents, and parsed ASTs.
        
        Args:
            files_data: Mapping of normalized relative file paths to their source text.
            ast_results: Mapping of normalized relative file paths to their AnalyzePythonResponse.
        """
        self.files_data = files_data
        self.ast_results = ast_results

        # Precompute module name -> file path mappings
        # and directory -> package mappings
        self.module_to_files: Dict[str, List[str]] = {}
        self.file_to_primary_module: Dict[str, str] = {}
        self.defined_symbols: Dict[str, List[str]] = {}

        self._index_project_files()

    def _index_project_files(self) -> None:
        """Build bidirectional module-file indexes for fast, deterministic resolution."""
        for path, ast_res in self.ast_results.items():
            symbols = extract_top_level_definitions(self.files_data.get(path, ""), ast_res)
            self.defined_symbols[path] = symbols

            # Map file to module
            # e.g., "services/payment.py" -> "services.payment"
            # e.g., "services/__init__.py" -> "services" and "services.__init__"
            # e.g., "main.py" -> "main"
            without_ext = path[:-3] if path.lower().endswith(".py") else path
            parts = without_ext.split("/")
            
            if parts[-1] == "__init__":
                pkg_module = ".".join(parts[:-1]) if len(parts) > 1 else ""
                full_module = ".".join(parts)
                if pkg_module:
                    self.module_to_files.setdefault(pkg_module, []).append(path)
                self.module_to_files.setdefault(full_module, []).append(path)
                self.file_to_primary_module[path] = pkg_module or "__init__"
            else:
                mod_name = ".".join(parts)
                self.module_to_files.setdefault(mod_name, []).append(path)
                self.file_to_primary_module[path] = mod_name

    def resolve_all_relationships(self) -> Tuple[List[ProjectRelationship], List[str]]:
        """Resolve all imports and cross-file relationships across the project.
        
        Returns:
            relationships: List of structured ProjectRelationship items.
            circular_warnings: List of warnings about detected circular import cycles.
        """
        relationships: List[ProjectRelationship] = []
        import_graph: Dict[str, Set[str]] = {p: set() for p in self.ast_results}

        for source_path in sorted(self.ast_results.keys()):
            ast_res = self.ast_results[source_path]
            if ast_res.status == "syntax_error":
                continue

            for imp in ast_res.imports:
                rel = self._resolve_single_import(source_path, imp)
                relationships.append(rel)

                if rel.target_file and rel.status == "resolved":
                    import_graph[source_path].add(rel.target_file)

            # Check for dynamic import function calls (e.g. __import__ or importlib.import_module)
            for call in ast_res.calls:
                expr_lower = (call.call_expr or "").lower()
                method_lower = (call.method or "").lower()
                receiver_lower = (call.receiver or "").lower()

                is_dynamic_import = False
                func_name = ""
                if expr_lower.startswith("__import__"):
                    is_dynamic_import = True
                    func_name = "__import__"
                elif method_lower == "import_module" or (receiver_lower == "importlib" and method_lower == "import_module"):
                    is_dynamic_import = True
                    func_name = "importlib.import_module"

                if is_dynamic_import:
                    relationships.append(
                        ProjectRelationship(
                            source_file=source_path,
                            target=call.call_expr,
                            target_file=None,
                            relationship_type="file_imports_file",
                            imported_symbol=None,
                            alias=None,
                            status="ambiguous",
                            reason=f"Dynamic import construct ('{func_name}') prevents deterministic static resolution.",
                            location=call.location,
                        )
                    )

        # Detect circular dependencies without infinite loop
        circular_warnings = self._detect_circular_dependencies(import_graph)

        return relationships, circular_warnings

    def _resolve_single_import(self, source_file: str, imp: ImportInfo) -> ProjectRelationship:
        """Resolve a single ImportInfo statement from source_file."""
        # 1. Wildcard import check
        if imp.is_from and imp.name == "*":
            target_pkg = imp.module
            target_files = self.module_to_files.get(target_pkg, [])
            target_file = target_files[0] if len(target_files) == 1 else None
            return ProjectRelationship(
                source_file=source_file,
                target=f"from {target_pkg} import *",
                target_file=target_file,
                relationship_type="file_imports_file",
                imported_symbol="*",
                alias=None,
                status="ambiguous",
                reason=f"Wildcard import ('from {target_pkg} import *') prevents deterministic static symbol resolution.",
                location=imp.location,
            )

        # 2. Relative import resolution (level > 0)
        if imp.level > 0:
            return self._resolve_relative_import(source_file, imp)

        # 3. Absolute import resolution (level == 0)
        return self._resolve_absolute_import(source_file, imp)

    def _resolve_relative_import(self, source_file: str, imp: ImportInfo) -> ProjectRelationship:
        """Resolve relative import with one or more leading dots."""
        # Source file directory
        source_dir = posixpath.dirname(source_file)
        dir_parts = [p for p in source_dir.split("/") if p]

        # Calculate target package parts based on relative level
        # level=1 -> current directory
        # level=2 -> parent directory
        climb = imp.level - 1
        if climb > len(dir_parts):
            return ProjectRelationship(
                source_file=source_file,
                target=f"{'.' * imp.level}{imp.module}",
                target_file=None,
                relationship_type="file_imports_file",
                imported_symbol=imp.name,
                alias=imp.alias,
                status="unresolved",
                reason=f"Relative import level {imp.level} climbs beyond project root directory from '{source_file}'.",
                location=imp.location,
            )

        base_parts = dir_parts[: len(dir_parts) - climb] if climb > 0 else dir_parts
        base_pkg = ".".join(base_parts)

        # Determine target module path
        if imp.module:
            target_mod = f"{base_pkg}.{imp.module}" if base_pkg else imp.module
        else:
            target_mod = base_pkg

        # Case A: from . import submodule_or_symbol (module is empty)
        if not imp.module and imp.is_from and imp.name:
            # Check if name is a sibling submodule: base_pkg.name
            submod = f"{base_pkg}.{imp.name}" if base_pkg else imp.name
            if submod in self.module_to_files:
                candidate_files = self.module_to_files[submod]
                if len(candidate_files) == 1:
                    target_file = candidate_files[0]
                    return ProjectRelationship(
                        source_file=source_file,
                        target=target_file,
                        target_file=target_file,
                        relationship_type="file_imports_file",
                        imported_symbol=imp.name,
                        alias=imp.alias,
                        status="resolved",
                        reason=f"Relative import '.{imp.name}' resolved to project file '{target_file}'.",
                        location=imp.location,
                    )
                else:
                    return ProjectRelationship(
                        source_file=source_file,
                        target=submod,
                        target_file=None,
                        relationship_type="file_imports_file",
                        imported_symbol=imp.name,
                        alias=imp.alias,
                        status="ambiguous",
                        reason=f"Relative import '.{imp.name}' matches multiple project files: {candidate_files}.",
                        location=imp.location,
                    )

            # Check if base_pkg/__init__.py exists and defines symbol
            if base_pkg in self.module_to_files:
                pkg_files = [f for f in self.module_to_files[base_pkg] if f.endswith("__init__.py")]
                if pkg_files:
                    target_file = pkg_files[0]
                    defined = self.defined_symbols.get(target_file, [])
                    if imp.name in defined:
                        return ProjectRelationship(
                            source_file=source_file,
                            target=imp.name,
                            target_file=target_file,
                            relationship_type="symbol_reference",
                            imported_symbol=imp.name,
                            alias=imp.alias,
                            status="resolved",
                            reason=f"Statically resolved relative symbol '{imp.name}' defined in '{target_file}'.",
                            location=imp.location,
                        )
                    else:
                        return ProjectRelationship(
                            source_file=source_file,
                            target=imp.name,
                            target_file=target_file,
                            relationship_type="symbol_reference",
                            imported_symbol=imp.name,
                            alias=imp.alias,
                            status="unresolved",
                            reason=f"Symbol '{imp.name}' was not found among top-level definitions in package init '{target_file}'.",
                            location=imp.location,
                        )

            return ProjectRelationship(
                source_file=source_file,
                target=f"{'.' * imp.level}{imp.name}",
                target_file=None,
                relationship_type="file_imports_file",
                imported_symbol=imp.name,
                alias=imp.alias,
                status="unresolved",
                reason=f"Relative target '{imp.name}' was not found in package '{base_pkg or '.'}'.",
                location=imp.location,
            )

        # Case B: from .module import symbol OR from ..module import symbol
        if target_mod in self.module_to_files:
            candidate_files = self.module_to_files[target_mod]
            if len(candidate_files) > 1:
                return ProjectRelationship(
                    source_file=source_file,
                    target=target_mod,
                    target_file=None,
                    relationship_type="file_imports_file",
                    imported_symbol=imp.name,
                    alias=imp.alias,
                    status="ambiguous",
                    reason=f"Ambiguous module match: '{target_mod}' corresponds to multiple files: {candidate_files}.",
                    location=imp.location,
                )

            target_file = candidate_files[0]

            # If symbol is imported, check its definition in target_file
            if imp.is_from and imp.name:
                defined = self.defined_symbols.get(target_file, [])
                if imp.name in defined:
                    return ProjectRelationship(
                        source_file=source_file,
                        target=imp.name,
                        target_file=target_file,
                        relationship_type="symbol_reference",
                        imported_symbol=imp.name,
                        alias=imp.alias,
                        status="resolved",
                        reason=f"Statically resolved relative symbol '{imp.name}' defined in '{target_file}'.",
                        location=imp.location,
                    )
                else:
                    # Check if imp.name is a submodule in package target_file
                    submod_path = f"{target_mod}.{imp.name}"
                    if submod_path in self.module_to_files:
                        sub_file = self.module_to_files[submod_path][0]
                        return ProjectRelationship(
                            source_file=source_file,
                            target=sub_file,
                            target_file=sub_file,
                            relationship_type="file_imports_file",
                            imported_symbol=imp.name,
                            alias=imp.alias,
                            status="resolved",
                            reason=f"Relative import resolved to submodule '{sub_file}'.",
                            location=imp.location,
                        )

                    return ProjectRelationship(
                        source_file=source_file,
                        target=imp.name,
                        target_file=target_file,
                        relationship_type="symbol_reference",
                        imported_symbol=imp.name,
                        alias=imp.alias,
                        status="unresolved",
                        reason=f"Imported symbol '{imp.name}' was not found among statically identified top-level definitions in '{target_file}'.",
                        location=imp.location,
                    )

            # Direct file import
            return ProjectRelationship(
                source_file=source_file,
                target=target_file,
                target_file=target_file,
                relationship_type="file_imports_file",
                imported_symbol=None,
                alias=imp.alias,
                status="resolved",
                reason=f"Relative import level {imp.level} resolved to '{target_file}'.",
                location=imp.location,
            )

        # Target module not found in project
        return ProjectRelationship(
            source_file=source_file,
            target=f"{'.' * imp.level}{imp.module}",
            target_file=None,
            relationship_type="file_imports_file",
            imported_symbol=imp.name,
            alias=imp.alias,
            status="unresolved",
            reason=f"Relative module '{'.' * imp.level}{imp.module}' not found in project files.",
            location=imp.location,
        )

    def _resolve_absolute_import(self, source_file: str, imp: ImportInfo) -> ProjectRelationship:
        """Resolve project-local absolute or external library import."""
        mod = imp.module

        # 1. Check if module directly matches a project file
        if mod in self.module_to_files:
            candidate_files = self.module_to_files[mod]
            if len(candidate_files) > 1:
                return ProjectRelationship(
                    source_file=source_file,
                    target=mod,
                    target_file=None,
                    relationship_type="file_imports_file",
                    imported_symbol=imp.name,
                    alias=imp.alias,
                    status="ambiguous",
                    reason=f"Ambiguous module match: '{mod}' corresponds to multiple files: {candidate_files}.",
                    location=imp.location,
                )

            target_file = candidate_files[0]

            # If symbol is imported via 'from mod import name'
            if imp.is_from and imp.name:
                # Check if name is actually a submodule: mod.name
                submod = f"{mod}.{imp.name}"
                if submod in self.module_to_files:
                    sub_file = self.module_to_files[submod][0]
                    return ProjectRelationship(
                        source_file=source_file,
                        target=sub_file,
                        target_file=sub_file,
                        relationship_type="file_imports_file",
                        imported_symbol=imp.name,
                        alias=imp.alias,
                        status="resolved",
                        reason=f"Import of submodule '{imp.name}' from package '{mod}' resolved to '{sub_file}'.",
                        location=imp.location,
                    )

                defined = self.defined_symbols.get(target_file, [])
                if imp.name in defined:
                    return ProjectRelationship(
                        source_file=source_file,
                        target=imp.name,
                        target_file=target_file,
                        relationship_type="symbol_reference",
                        imported_symbol=imp.name,
                        alias=imp.alias,
                        status="resolved",
                        reason=f"Statically resolved imported symbol '{imp.name}' defined in '{target_file}'.",
                        location=imp.location,
                    )
                else:
                    return ProjectRelationship(
                        source_file=source_file,
                        target=imp.name,
                        target_file=target_file,
                        relationship_type="symbol_reference",
                        imported_symbol=imp.name,
                        alias=imp.alias,
                        status="unresolved",
                        reason=f"Imported symbol '{imp.name}' was not found among statically identified top-level definitions in '{target_file}'.",
                        location=imp.location,
                    )

            # Direct import of module (e.g. 'import services.payment')
            return ProjectRelationship(
                source_file=source_file,
                target=target_file,
                target_file=target_file,
                relationship_type="file_imports_file",
                imported_symbol=None,
                alias=imp.alias,
                status="resolved",
                reason=f"Unambiguous project-local absolute import resolved to '{target_file}'.",
                location=imp.location,
            )

        # 2. Check if mod.name is a submodule in project (e.g. from services import payment)
        if imp.is_from and imp.name:
            candidate_submod = f"{mod}.{imp.name}"
            if candidate_submod in self.module_to_files:
                target_file = self.module_to_files[candidate_submod][0]
                return ProjectRelationship(
                    source_file=source_file,
                    target=target_file,
                    target_file=target_file,
                    relationship_type="file_imports_file",
                    imported_symbol=imp.name,
                    alias=imp.alias,
                    status="resolved",
                    reason=f"Submodule import resolved to '{target_file}'.",
                    location=imp.location,
                )

        # 3. Not found in project files -> External or Standard Library import
        display_target = f"{mod}.{imp.name}" if (imp.is_from and imp.name) else mod
        return ProjectRelationship(
            source_file=source_file,
            target=display_target,
            target_file=None,
            relationship_type="file_imports_external",
            imported_symbol=imp.name if imp.is_from else None,
            alias=imp.alias,
            status="external",
            reason=f"External package or standard library import '{mod}'.",
            location=imp.location,
        )

    def _detect_circular_dependencies(self, graph: Dict[str, Set[str]]) -> List[str]:
        """Detect circular dependencies safely using cycle detection (DFS 3-color)."""
        visited: Dict[str, int] = {}  # 0: unvisited, 1: visiting, 2: visited
        cycles: List[str] = []

        def dfs(node: str, path: List[str]) -> None:
            visited[node] = 1
            path.append(node)

            for neighbor in sorted(graph.get(node, [])):
                if visited.get(neighbor, 0) == 1:
                    # Cycle detected
                    cycle_start = path.index(neighbor)
                    cycle_path = " -> ".join(path[cycle_start:] + [neighbor])
                    cycles.append(f"Circular dependency detected: {cycle_path}")
                elif visited.get(neighbor, 0) == 0:
                    dfs(neighbor, path)

            path.pop()
            visited[node] = 2

        for file_node in sorted(graph.keys()):
            if visited.get(file_node, 0) == 0:
                dfs(file_node, [])

        return cycles
