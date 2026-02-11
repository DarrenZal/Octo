"""
Tree-sitter based code entity extractor for Octo GitHub Sensor

Ported from RegenAI's tree_sitter_extractor.py, adapted for Octo:
- Supports Python and TypeScript/JavaScript (no Go/Proto — Octo has no Go code)
- Adds SQL file handling (regex-based CREATE TABLE/INDEX extraction)
- Deterministic entity IDs for idempotent extraction

Entity types: Function, Class, Module, File, Import, Interface
Edge types: CALLS, CONTAINS, BELONGS_TO, IMPORTS
"""

import hashlib
import os
import re
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, asdict

import logging

logger = logging.getLogger(__name__)

# Tree-sitter imports
import tree_sitter_python
import tree_sitter_typescript
from tree_sitter import Language, Parser, Node


@dataclass
class CodeEntity:
    """Represents an extracted code entity"""
    entity_id: str           # Deterministic hash ID
    name: str
    entity_type: str         # Function, Class, Interface, Module, File, Import
    file_path: str
    line_start: int
    line_end: int
    language: str
    repo: str
    signature: str = ""
    params: str = ""
    return_type: str = ""
    docstring: str = ""
    receiver_type: str = ""
    extraction_method: str = "tree_sitter"
    module_name: str = ""
    module_path: str = ""

    def to_dict(self) -> Dict:
        return asdict(self)


@dataclass
class CodeEdge:
    """Represents a relationship between entities

    Edge types:
    - CALLS: Function/method calls another function/method
    - IMPORTS: File/module imports another module
    - BELONGS_TO: File belongs to a module/package
    - CONTAINS: File/Module contains a Function, Class, or Method
    """
    edge_id: str             # Deterministic hash ID
    from_entity_id: str
    to_entity_id: str
    edge_type: str           # CALLS, IMPORTS, BELONGS_TO, CONTAINS
    file_path: str
    line_number: int

    def to_dict(self) -> Dict:
        return asdict(self)


def generate_entity_id(repo: str, file_path: str, name: str, signature: str = "") -> str:
    """Generate deterministic ID for idempotent extraction"""
    key = f"{repo}:{file_path}:{name}:{signature}"
    return hashlib.sha256(key.encode()).hexdigest()[:16]


def generate_edge_id(from_id: str, to_id: str, edge_type: str) -> str:
    """Generate deterministic ID for edges"""
    key = f"{from_id}-{edge_type}->{to_id}"
    return hashlib.sha256(key.encode()).hexdigest()[:16]


class TreeSitterExtractor:
    """
    Tree-sitter based code entity extractor

    Usage:
        extractor = TreeSitterExtractor()
        entities, edges = extractor.extract("python", code, "api/server.py", "Octo")
    """

    def __init__(self):
        self.python_parser = Parser(Language(tree_sitter_python.language()))
        self.ts_parser = Parser(Language(tree_sitter_typescript.language_typescript()))
        self.tsx_parser = Parser(Language(tree_sitter_typescript.language_tsx()))
        logger.info("TreeSitterExtractor initialized with Python, TypeScript support")

    def extract(
        self,
        language: str,
        content: str,
        file_path: str,
        repo: str
    ) -> Tuple[List[CodeEntity], List[CodeEdge]]:
        """Extract entities and edges from source code"""
        if language == "python":
            return self._extract_python(content, file_path, repo)
        elif language in ("typescript", "javascript", "tsx"):
            return self._extract_typescript(content, file_path, repo, language)
        elif language == "sql":
            return self._extract_sql(content, file_path, repo)
        else:
            logger.warning(f"Unsupported language: {language}")
            return [], []

    # ============= SHARED HELPERS =============

    def _find_nodes_by_type(self, node: Node, type_name: str) -> List[Node]:
        """Recursively find all nodes of a given type"""
        results = []
        if node.type == type_name:
            results.append(node)
        for child in node.children:
            results.extend(self._find_nodes_by_type(child, type_name))
        return results

    def _create_file_entity(
        self,
        file_path: str,
        repo: str,
        language: str,
        content: str,
        module_name: str = "",
        module_path: str = ""
    ) -> CodeEntity:
        """Create a File entity"""
        file_name = os.path.basename(file_path)
        line_count = content.count('\n') + 1
        file_hash = hashlib.sha256(content.encode()).hexdigest()[:16]

        return CodeEntity(
            entity_id=generate_entity_id(repo, file_path, file_name, "file"),
            name=file_name,
            entity_type="File",
            file_path=file_path,
            line_start=1,
            line_end=line_count,
            language=language,
            repo=repo,
            signature=f"{file_path} ({line_count} lines)",
            docstring=f"hash:{file_hash}",
            module_name=module_name,
            module_path=module_path,
        )

    # ============= PYTHON EXTRACTION =============

    def _extract_python(
        self,
        content: str,
        file_path: str,
        repo: str
    ) -> Tuple[List[CodeEntity], List[CodeEdge]]:
        """Extract entities and edges from Python code"""
        entities = []
        edges = []

        tree = self.python_parser.parse(content.encode())
        root = tree.root_node
        source = content.encode()

        dir_path = os.path.dirname(file_path)
        file_name = os.path.basename(file_path)

        if file_name == "__init__.py":
            module_name = os.path.basename(dir_path) if dir_path else repo
        else:
            module_name = os.path.splitext(file_name)[0]

        if dir_path:
            module_path = dir_path.replace(os.sep, ".").replace("/", ".")
            full_module_path = f"{module_path}.{module_name}" if module_name != os.path.basename(dir_path) else module_path
        else:
            full_module_path = module_name

        # Create Module entity
        module_entity = self._create_python_module_entity(
            module_name, dir_path, file_path, repo, content, full_module_path
        )
        entities.append(module_entity)

        # Create File entity
        file_entity = self._create_file_entity(file_path, repo, "python", content, module_name, full_module_path)
        entities.append(file_entity)

        # BELONGS_TO edge: File -> Module
        edges.append(CodeEdge(
            edge_id=generate_edge_id(file_entity.entity_id, module_entity.entity_id, "BELONGS_TO"),
            from_entity_id=file_entity.entity_id,
            to_entity_id=module_entity.entity_id,
            edge_type="BELONGS_TO",
            file_path=file_path,
            line_number=1,
        ))

        # Extract imports
        for node in self._find_nodes_by_type(root, "import_statement"):
            imports = self._extract_python_import(node, source, file_path, repo)
            for imp in imports:
                imp.module_name = module_name
                imp.module_path = full_module_path
            entities.extend(imports)
        for node in self._find_nodes_by_type(root, "import_from_statement"):
            imports = self._extract_python_import(node, source, file_path, repo)
            for imp in imports:
                imp.module_name = module_name
                imp.module_path = full_module_path
            entities.extend(imports)

        # Extract classes
        for node in self._find_nodes_by_type(root, "class_definition"):
            entity = self._extract_python_class(node, source, file_path, repo)
            if entity:
                entity.module_name = module_name
                entity.module_path = full_module_path
                entities.append(entity)
                edges.append(CodeEdge(
                    edge_id=generate_edge_id(file_entity.entity_id, entity.entity_id, "CONTAINS"),
                    from_entity_id=file_entity.entity_id,
                    to_entity_id=entity.entity_id,
                    edge_type="CONTAINS",
                    file_path=file_path,
                    line_number=entity.line_start,
                ))

        # Extract functions
        for node in self._find_nodes_by_type(root, "function_definition"):
            entity = self._extract_python_function(node, source, file_path, repo)
            if entity:
                entity.module_name = module_name
                entity.module_path = full_module_path
                entities.append(entity)
                edges.append(CodeEdge(
                    edge_id=generate_edge_id(file_entity.entity_id, entity.entity_id, "CONTAINS"),
                    from_entity_id=file_entity.entity_id,
                    to_entity_id=entity.entity_id,
                    edge_type="CONTAINS",
                    file_path=file_path,
                    line_number=entity.line_start,
                ))
                calls = self._extract_python_calls(node, source, file_path, repo, entity)
                edges.extend(calls)

        return entities, edges

    def _create_python_module_entity(
        self,
        module_name: str,
        dir_path: str,
        file_path: str,
        repo: str,
        content: str,
        full_module_path: str
    ) -> CodeEntity:
        """Create a Module entity for a Python module"""
        file_name = os.path.basename(file_path)
        is_package = file_name == "__init__.py"

        docstring = ""
        lines = content.split('\n')
        for i, line in enumerate(lines):
            stripped = line.strip()
            if stripped.startswith('"""') or stripped.startswith("'''"):
                quote = '"""' if stripped.startswith('"""') else "'''"
                if stripped.count(quote) >= 2:
                    docstring = stripped.strip(quote).strip()
                else:
                    docstring_lines = [stripped.lstrip(quote)]
                    for j in range(i + 1, min(i + 20, len(lines))):
                        if quote in lines[j]:
                            docstring_lines.append(lines[j].split(quote)[0])
                            break
                        docstring_lines.append(lines[j])
                    docstring = " ".join(docstring_lines).strip()
                break
            elif stripped and not stripped.startswith('#'):
                break

        if len(docstring) > 200:
            docstring = docstring[:200] + "..."

        return CodeEntity(
            entity_id=generate_entity_id(repo, file_path, module_name, "module"),
            name=module_name,
            entity_type="Module",
            file_path=file_path,
            line_start=1,
            line_end=1,
            language="python",
            repo=repo,
            signature=f"module {full_module_path}" + (" (package)" if is_package else ""),
            docstring=docstring,
            module_name=module_name,
            module_path=full_module_path,
        )

    def _extract_python_import(
        self,
        node: Node,
        source: bytes,
        file_path: str,
        repo: str
    ) -> List[CodeEntity]:
        """Extract Python import statement"""
        entities = []

        if node.type == "import_statement":
            for child in node.children:
                if child.type == "dotted_name":
                    name = source[child.start_byte:child.end_byte].decode()
                    entities.append(CodeEntity(
                        entity_id=generate_entity_id(repo, file_path, f"import:{name}"),
                        name=name,
                        entity_type="Import",
                        file_path=file_path,
                        line_start=node.start_point[0] + 1,
                        line_end=node.end_point[0] + 1,
                        language="python",
                        repo=repo,
                        signature=source[node.start_byte:node.end_byte].decode(),
                    ))

        elif node.type == "import_from_statement":
            module = ""
            for child in node.children:
                if child.type == "dotted_name":
                    module = source[child.start_byte:child.end_byte].decode()
                    break
            if module:
                entities.append(CodeEntity(
                    entity_id=generate_entity_id(repo, file_path, f"import:{module}"),
                    name=module,
                    entity_type="Import",
                    file_path=file_path,
                    line_start=node.start_point[0] + 1,
                    line_end=node.end_point[0] + 1,
                    language="python",
                    repo=repo,
                    signature=source[node.start_byte:node.end_byte].decode(),
                ))

        return entities

    def _extract_python_class(
        self,
        node: Node,
        source: bytes,
        file_path: str,
        repo: str
    ) -> Optional[CodeEntity]:
        """Extract Python class definition"""
        name = ""
        for child in node.children:
            if child.type == "identifier":
                name = source[child.start_byte:child.end_byte].decode()
                break

        if not name:
            return None

        docstring = self._get_python_docstring(node, source)
        full_code = source[node.start_byte:node.end_byte].decode()
        sig_lines = full_code.split('\n')
        signature = sig_lines[0] if sig_lines else full_code

        return CodeEntity(
            entity_id=generate_entity_id(repo, file_path, name, "class"),
            name=name,
            entity_type="Class",
            file_path=file_path,
            line_start=node.start_point[0] + 1,
            line_end=node.end_point[0] + 1,
            language="python",
            repo=repo,
            signature=signature,
            docstring=docstring,
        )

    def _extract_python_function(
        self,
        node: Node,
        source: bytes,
        file_path: str,
        repo: str
    ) -> Optional[CodeEntity]:
        """Extract Python function definition"""
        name = ""
        params = ""
        return_type = ""

        for child in node.children:
            if child.type == "identifier":
                name = source[child.start_byte:child.end_byte].decode()
            elif child.type == "parameters":
                params = source[child.start_byte:child.end_byte].decode()
            elif child.type == "type":
                return_type = source[child.start_byte:child.end_byte].decode()

        if not name:
            return None

        docstring = self._get_python_docstring(node, source)
        full_code = source[node.start_byte:node.end_byte].decode()
        sig_lines = full_code.split('\n')
        signature = sig_lines[0] if sig_lines else full_code

        return CodeEntity(
            entity_id=generate_entity_id(repo, file_path, name, params),
            name=name,
            entity_type="Function",
            file_path=file_path,
            line_start=node.start_point[0] + 1,
            line_end=node.end_point[0] + 1,
            language="python",
            repo=repo,
            signature=signature,
            params=params,
            return_type=return_type,
            docstring=docstring,
        )

    def _extract_python_calls(
        self,
        node: Node,
        source: bytes,
        file_path: str,
        repo: str,
        caller: CodeEntity
    ) -> List[CodeEdge]:
        """Extract function calls from Python function body"""
        edges = []

        for call in self._find_nodes_by_type(node, "call"):
            callee_name = ""
            for child in call.children:
                if child.type == "identifier":
                    callee_name = source[child.start_byte:child.end_byte].decode()
                elif child.type == "attribute":
                    callee_name = source[child.start_byte:child.end_byte].decode()

            if callee_name:
                edge = CodeEdge(
                    edge_id=generate_edge_id(caller.entity_id, callee_name, "CALLS"),
                    from_entity_id=caller.entity_id,
                    to_entity_id=callee_name,
                    edge_type="CALLS",
                    file_path=file_path,
                    line_number=call.start_point[0] + 1,
                )
                edges.append(edge)

        return edges

    def _get_python_docstring(self, node: Node, source: bytes) -> str:
        """Get Python docstring from function/class body"""
        body = None
        for child in node.children:
            if child.type == "block":
                body = child
                break

        if not body or not body.children:
            return ""

        first = body.children[0]
        if first.type == "expression_statement":
            for child in first.children:
                if child.type == "string":
                    docstring = source[child.start_byte:child.end_byte].decode()
                    return docstring.strip('"""').strip("'''").strip()

        return ""

    # ============= TYPESCRIPT EXTRACTION =============

    def _extract_typescript(
        self,
        content: str,
        file_path: str,
        repo: str,
        language: str
    ) -> Tuple[List[CodeEntity], List[CodeEdge]]:
        """Extract entities and edges from TypeScript/JavaScript code"""
        entities = []
        edges = []

        parser = self.tsx_parser if language == "tsx" else self.ts_parser
        tree = parser.parse(content.encode())
        root = tree.root_node
        source = content.encode()

        dir_path = os.path.dirname(file_path)
        file_name = os.path.basename(file_path)

        module_name = os.path.splitext(file_name)[0]
        if module_name == "index":
            module_name = os.path.basename(dir_path) if dir_path else repo

        if dir_path:
            full_module_path = f"{dir_path}/{module_name}"
        else:
            full_module_path = module_name

        # Create Module entity
        module_entity = self._create_ts_module_entity(
            module_name, dir_path, file_path, repo, content, full_module_path, language
        )
        entities.append(module_entity)

        # Create File entity
        file_entity = self._create_file_entity(file_path, repo, language, content, module_name, full_module_path)
        entities.append(file_entity)

        # BELONGS_TO edge: File -> Module
        edges.append(CodeEdge(
            edge_id=generate_edge_id(file_entity.entity_id, module_entity.entity_id, "BELONGS_TO"),
            from_entity_id=file_entity.entity_id,
            to_entity_id=module_entity.entity_id,
            edge_type="BELONGS_TO",
            file_path=file_path,
            line_number=1,
        ))

        # Extract imports
        for node in self._find_nodes_by_type(root, "import_statement"):
            entity = self._extract_ts_import(node, source, file_path, repo, language)
            if entity:
                entity.module_name = module_name
                entity.module_path = full_module_path
                entities.append(entity)

        # Extract classes
        for node in self._find_nodes_by_type(root, "class_declaration"):
            entity = self._extract_ts_class(node, source, file_path, repo, language)
            if entity:
                entity.module_name = module_name
                entity.module_path = full_module_path
                entities.append(entity)
                edges.append(CodeEdge(
                    edge_id=generate_edge_id(file_entity.entity_id, entity.entity_id, "CONTAINS"),
                    from_entity_id=file_entity.entity_id,
                    to_entity_id=entity.entity_id,
                    edge_type="CONTAINS",
                    file_path=file_path,
                    line_number=entity.line_start,
                ))

        # Extract interfaces
        for node in self._find_nodes_by_type(root, "interface_declaration"):
            entity = self._extract_ts_interface(node, source, file_path, repo, language)
            if entity:
                entity.module_name = module_name
                entity.module_path = full_module_path
                entities.append(entity)
                edges.append(CodeEdge(
                    edge_id=generate_edge_id(file_entity.entity_id, entity.entity_id, "CONTAINS"),
                    from_entity_id=file_entity.entity_id,
                    to_entity_id=entity.entity_id,
                    edge_type="CONTAINS",
                    file_path=file_path,
                    line_number=entity.line_start,
                ))

        # Extract functions
        for node in self._find_nodes_by_type(root, "function_declaration"):
            entity = self._extract_ts_function(node, source, file_path, repo, language)
            if entity:
                entity.module_name = module_name
                entity.module_path = full_module_path
                entities.append(entity)
                edges.append(CodeEdge(
                    edge_id=generate_edge_id(file_entity.entity_id, entity.entity_id, "CONTAINS"),
                    from_entity_id=file_entity.entity_id,
                    to_entity_id=entity.entity_id,
                    edge_type="CONTAINS",
                    file_path=file_path,
                    line_number=entity.line_start,
                ))

        # Extract arrow functions (const foo = () => {})
        for node in self._find_nodes_by_type(root, "lexical_declaration"):
            entity = self._extract_ts_arrow_function(node, source, file_path, repo, language)
            if entity:
                entity.module_name = module_name
                entity.module_path = full_module_path
                entities.append(entity)
                edges.append(CodeEdge(
                    edge_id=generate_edge_id(file_entity.entity_id, entity.entity_id, "CONTAINS"),
                    from_entity_id=file_entity.entity_id,
                    to_entity_id=entity.entity_id,
                    edge_type="CONTAINS",
                    file_path=file_path,
                    line_number=entity.line_start,
                ))

        return entities, edges

    def _create_ts_module_entity(
        self,
        module_name: str,
        dir_path: str,
        file_path: str,
        repo: str,
        content: str,
        full_module_path: str,
        language: str
    ) -> CodeEntity:
        """Create a Module entity for a TypeScript/JavaScript module"""
        file_name = os.path.basename(file_path)
        is_index = module_name == "index" or file_name.startswith("index.")

        docstring = ""
        lines = content.split('\n')
        if lines and lines[0].strip().startswith('/**'):
            docstring_lines = []
            for line in lines:
                stripped = line.strip()
                if stripped.startswith('/**'):
                    docstring_lines.append(stripped.lstrip('/**').strip())
                elif stripped.startswith('*/'):
                    break
                elif stripped.startswith('*'):
                    docstring_lines.append(stripped.lstrip('* ').strip())
                else:
                    docstring_lines.append(stripped)
            docstring = " ".join(docstring_lines).strip()

        if len(docstring) > 200:
            docstring = docstring[:200] + "..."

        return CodeEntity(
            entity_id=generate_entity_id(repo, file_path, module_name, "module"),
            name=module_name,
            entity_type="Module",
            file_path=file_path,
            line_start=1,
            line_end=1,
            language=language,
            repo=repo,
            signature=f"module {full_module_path}" + (" (index)" if is_index else ""),
            docstring=docstring,
            module_name=module_name,
            module_path=full_module_path,
        )

    def _extract_ts_import(
        self,
        node: Node,
        source: bytes,
        file_path: str,
        repo: str,
        language: str
    ) -> Optional[CodeEntity]:
        """Extract TypeScript import statement"""
        module_path = ""
        for child in self._find_nodes_by_type(node, "string"):
            module_path = source[child.start_byte:child.end_byte].decode().strip('"\'')
            break

        if not module_path:
            return None

        return CodeEntity(
            entity_id=generate_entity_id(repo, file_path, f"import:{module_path}"),
            name=module_path,
            entity_type="Import",
            file_path=file_path,
            line_start=node.start_point[0] + 1,
            line_end=node.end_point[0] + 1,
            language=language,
            repo=repo,
            signature=source[node.start_byte:node.end_byte].decode(),
        )

    def _extract_ts_class(
        self,
        node: Node,
        source: bytes,
        file_path: str,
        repo: str,
        language: str
    ) -> Optional[CodeEntity]:
        """Extract TypeScript class declaration"""
        name = ""
        for child in node.children:
            if child.type == "type_identifier":
                name = source[child.start_byte:child.end_byte].decode()
                break

        if not name:
            return None

        docstring = self._get_ts_docstring(node, source)
        full_code = source[node.start_byte:node.end_byte].decode()
        sig_lines = full_code.split('\n')
        signature = sig_lines[0] if sig_lines else full_code

        return CodeEntity(
            entity_id=generate_entity_id(repo, file_path, name, "class"),
            name=name,
            entity_type="Class",
            file_path=file_path,
            line_start=node.start_point[0] + 1,
            line_end=node.end_point[0] + 1,
            language=language,
            repo=repo,
            signature=signature,
            docstring=docstring,
        )

    def _extract_ts_interface(
        self,
        node: Node,
        source: bytes,
        file_path: str,
        repo: str,
        language: str
    ) -> Optional[CodeEntity]:
        """Extract TypeScript interface declaration"""
        name = ""
        for child in node.children:
            if child.type == "type_identifier":
                name = source[child.start_byte:child.end_byte].decode()
                break

        if not name:
            return None

        docstring = self._get_ts_docstring(node, source)
        full_code = source[node.start_byte:node.end_byte].decode()
        sig_lines = full_code.split('\n')
        signature = sig_lines[0] if sig_lines else full_code

        return CodeEntity(
            entity_id=generate_entity_id(repo, file_path, name, "interface"),
            name=name,
            entity_type="Interface",
            file_path=file_path,
            line_start=node.start_point[0] + 1,
            line_end=node.end_point[0] + 1,
            language=language,
            repo=repo,
            signature=signature,
            docstring=docstring,
        )

    def _extract_ts_function(
        self,
        node: Node,
        source: bytes,
        file_path: str,
        repo: str,
        language: str
    ) -> Optional[CodeEntity]:
        """Extract TypeScript function declaration"""
        name = ""
        params = ""

        for child in node.children:
            if child.type == "identifier":
                name = source[child.start_byte:child.end_byte].decode()
            elif child.type == "formal_parameters":
                params = source[child.start_byte:child.end_byte].decode()

        if not name:
            return None

        docstring = self._get_ts_docstring(node, source)
        full_code = source[node.start_byte:node.end_byte].decode()
        sig_lines = full_code.split('\n')
        signature = sig_lines[0] if sig_lines else full_code

        return CodeEntity(
            entity_id=generate_entity_id(repo, file_path, name, params),
            name=name,
            entity_type="Function",
            file_path=file_path,
            line_start=node.start_point[0] + 1,
            line_end=node.end_point[0] + 1,
            language=language,
            repo=repo,
            signature=signature,
            params=params,
            docstring=docstring,
        )

    def _extract_ts_arrow_function(
        self,
        node: Node,
        source: bytes,
        file_path: str,
        repo: str,
        language: str
    ) -> Optional[CodeEntity]:
        """Extract TypeScript arrow function (const foo = () => {})"""
        for declarator in self._find_nodes_by_type(node, "variable_declarator"):
            name = ""
            is_arrow = False
            params = ""

            for child in declarator.children:
                if child.type == "identifier":
                    name = source[child.start_byte:child.end_byte].decode()
                elif child.type == "arrow_function":
                    is_arrow = True
                    for arrow_child in child.children:
                        if arrow_child.type == "formal_parameters":
                            params = source[arrow_child.start_byte:arrow_child.end_byte].decode()

            if name and is_arrow:
                docstring = self._get_ts_docstring(node, source)
                full_code = source[node.start_byte:node.end_byte].decode()
                sig_lines = full_code.split('\n')
                signature = sig_lines[0] if sig_lines else full_code

                return CodeEntity(
                    entity_id=generate_entity_id(repo, file_path, name, params),
                    name=name,
                    entity_type="Function",
                    file_path=file_path,
                    line_start=node.start_point[0] + 1,
                    line_end=node.end_point[0] + 1,
                    language=language,
                    repo=repo,
                    signature=signature,
                    params=params,
                    docstring=docstring,
                )

        return None

    def _get_ts_docstring(self, node: Node, source: bytes) -> str:
        """Get JSDoc comment above TypeScript declaration"""
        prev = node.prev_sibling
        while prev:
            if prev.type == "comment":
                text = source[prev.start_byte:prev.end_byte].decode()
                if text.startswith("/**"):
                    return text.strip("/* \n")
                elif text.startswith("//"):
                    return text.lstrip("/ ").strip()
            else:
                break
            prev = prev.prev_sibling
        return ""

    # ============= SQL EXTRACTION (regex-based) =============

    def _extract_sql(
        self,
        content: str,
        file_path: str,
        repo: str
    ) -> Tuple[List[CodeEntity], List[CodeEdge]]:
        """Extract entities from SQL files using regex (CREATE TABLE, INDEX, VIEW, etc.)"""
        entities = []
        edges = []

        # File entity
        file_entity = self._create_file_entity(file_path, repo, "sql", content)
        entities.append(file_entity)

        lines = content.split('\n')

        # CREATE TABLE
        for match in re.finditer(
            r'CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?(\w+)',
            content, re.IGNORECASE
        ):
            name = match.group(1)
            line_num = content[:match.start()].count('\n') + 1
            entity = CodeEntity(
                entity_id=generate_entity_id(repo, file_path, name, "table"),
                name=name,
                entity_type="Class",  # Tables map to Class in the graph
                file_path=file_path,
                line_start=line_num,
                line_end=line_num,
                language="sql",
                repo=repo,
                signature=f"CREATE TABLE {name}",
                extraction_method="regex",
            )
            entities.append(entity)
            edges.append(CodeEdge(
                edge_id=generate_edge_id(file_entity.entity_id, entity.entity_id, "CONTAINS"),
                from_entity_id=file_entity.entity_id,
                to_entity_id=entity.entity_id,
                edge_type="CONTAINS",
                file_path=file_path,
                line_number=line_num,
            ))

        # CREATE INDEX
        for match in re.finditer(
            r'CREATE\s+(?:UNIQUE\s+)?INDEX\s+(?:IF\s+NOT\s+EXISTS\s+)?(\w+)',
            content, re.IGNORECASE
        ):
            name = match.group(1)
            line_num = content[:match.start()].count('\n') + 1
            entity = CodeEntity(
                entity_id=generate_entity_id(repo, file_path, name, "index"),
                name=name,
                entity_type="Function",  # Indexes map to Function in the graph
                file_path=file_path,
                line_start=line_num,
                line_end=line_num,
                language="sql",
                repo=repo,
                signature=f"CREATE INDEX {name}",
                extraction_method="regex",
            )
            entities.append(entity)

        # CREATE VIEW
        for match in re.finditer(
            r'CREATE\s+(?:OR\s+REPLACE\s+)?VIEW\s+(\w+)',
            content, re.IGNORECASE
        ):
            name = match.group(1)
            line_num = content[:match.start()].count('\n') + 1
            entity = CodeEntity(
                entity_id=generate_entity_id(repo, file_path, name, "view"),
                name=name,
                entity_type="Class",
                file_path=file_path,
                line_start=line_num,
                line_end=line_num,
                language="sql",
                repo=repo,
                signature=f"CREATE VIEW {name}",
                extraction_method="regex",
            )
            entities.append(entity)

        # CREATE FUNCTION
        for match in re.finditer(
            r'CREATE\s+(?:OR\s+REPLACE\s+)?FUNCTION\s+(\w+)',
            content, re.IGNORECASE
        ):
            name = match.group(1)
            line_num = content[:match.start()].count('\n') + 1
            entity = CodeEntity(
                entity_id=generate_entity_id(repo, file_path, name, "sql_function"),
                name=name,
                entity_type="Function",
                file_path=file_path,
                line_start=line_num,
                line_end=line_num,
                language="sql",
                repo=repo,
                signature=f"CREATE FUNCTION {name}",
                extraction_method="regex",
            )
            entities.append(entity)

        return entities, edges
