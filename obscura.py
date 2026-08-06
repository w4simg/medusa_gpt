import ast
import os
import sys
import time
import random
import shutil
import argparse
import builtins

# =====================================================================
# SCOPE ANALYSIS & UTILITIES
# =====================================================================

class Scope:
    def __init__(self, parent=None, is_class=False):
        self.parent = parent
        self.is_class = is_class
        self.defined = set()           # local variables, functions, classes
        self.globals = set()           # global declarations
        self.nonlocals = set()         # nonlocal declarations
        self.defined_imports = {}      # local_name -> full_module_path (for project modules)
        self.children = []

def resolve_scope(scope, name):
    curr = scope
    while curr is not None:
        if name in curr.globals:
            # Resolve to module scope (root scope)
            root = curr
            while root.parent is not None:
                root = root.parent
            return root
        if name in curr.nonlocals:
            # Skip class scopes when finding nonlocal
            curr = curr.parent
            while curr is not None and curr.is_class:
                curr = curr.parent
            while curr is not None:
                if name in curr.defined:
                    return curr
                curr = curr.parent
            return None
        if name in curr.defined:
            return curr
        
        # When searching up, skip class scope for bare names
        parent = curr.parent
        if parent and parent.is_class:
            parent = parent.parent
        curr = parent
    return None

def get_module_name(file_path, project_root):
    rel_path = os.path.relpath(file_path, project_root)
    base, _ = os.path.splitext(rel_path)
    parts = base.replace(os.path.sep, '/').split('/')
    if parts and parts[-1] == '__init__':
        parts.pop()
    return ".".join(parts)

def resolve_relative_import(current_module, is_package, level, target_module):
    if not current_module:
        return target_module or ""
        
    parts = current_module.split('.')
    if not is_package:
        # Normal modules drop their own name on the first level of relative import
        parts = parts[:-1]
        
    # Drop additional parts for higher levels (e.g. level=2 drops one more)
    if level > 1:
        parts = parts[:-(level - 1)]
        
    if target_module:
        parts.append(target_module)
        
    return ".".join(parts)

def resolve_name_to_module(scope, name_id):
    curr = scope
    while curr is not None:
        if name_id in curr.defined_imports:
            return curr.defined_imports[name_id]
        curr = curr.parent
    return None

def resolve_attribute_chain(node, scope):
    if isinstance(node, ast.Name):
        mod = resolve_name_to_module(scope, node.id)
        if mod:
            return (mod, [])
        return None
    elif isinstance(node, ast.Attribute):
        res = resolve_attribute_chain(node.value, scope)
        if res:
            mod_path, attrs = res
            return (mod_path, attrs + [node.attr])
    return None

# =====================================================================
# AST SCOPE BUILDER & COLLECTORS
# =====================================================================

class ScopeBuilder(ast.NodeVisitor):
    def __init__(self, project_modules, current_module=None, is_package=False):
        self.current_scope = Scope()
        self.node_scopes = {}
        self.project_modules = project_modules  # set of module names in the project
        self.current_module = current_module
        self.is_package = is_package

    def visit_Module(self, node):
        self.node_scopes[node] = self.current_scope
        self.generic_visit(node)

    def visit_ClassDef(self, node):
        self.current_scope.defined.add(node.name)
        parent = self.current_scope
        self.current_scope = Scope(parent=parent, is_class=True)
        parent.children.append(self.current_scope)
        self.node_scopes[node] = self.current_scope
        self.generic_visit(node)
        self.current_scope = parent

    def visit_FunctionDef(self, node):
        self.current_scope.defined.add(node.name)
        parent = self.current_scope
        self.current_scope = Scope(parent=parent)
        parent.children.append(self.current_scope)
        self.node_scopes[node] = self.current_scope
        
        # Add arguments to function scope
        for arg in node.args.posonlyargs + node.args.args + node.args.kwonlyargs:
            self.current_scope.defined.add(arg.arg)
        if node.args.vararg:
            self.current_scope.defined.add(node.args.vararg.arg)
        if node.args.kwarg:
            self.current_scope.defined.add(node.args.kwarg.arg)
            
        self.generic_visit(node)
        self.current_scope = parent

    def visit_AsyncFunctionDef(self, node):
        self.visit_FunctionDef(node)

    def visit_Global(self, node):
        for name in node.names:
            self.current_scope.globals.add(name)

    def visit_Nonlocal(self, node):
        for name in node.names:
            self.current_scope.nonlocals.add(name)

    def visit_Name(self, node):
        if isinstance(node.ctx, ast.Store):
            if node.id not in self.current_scope.globals and node.id not in self.current_scope.nonlocals:
                self.current_scope.defined.add(node.id)

    def visit_MatchAs(self, node):
        if node.name:
            self.current_scope.defined.add(node.name)
        self.generic_visit(node)

    def visit_Import(self, node):
        for alias in node.names:
            local_name = alias.asname or alias.name.split('.')[0]
            self.current_scope.defined.add(local_name)
            if alias.asname:
                if alias.name in self.project_modules:
                    self.current_scope.defined_imports[alias.asname] = alias.name
            else:
                top_pkg = alias.name.split('.')[0]
                self.current_scope.defined_imports[top_pkg] = top_pkg

    def visit_ImportFrom(self, node):
        if not node.module and node.level == 0:
            return
            
        # Determine source module path
        if node.level > 0:
            resolved_module = resolve_relative_import(self.current_module, self.is_package, node.level, node.module)
        else:
            resolved_module = node.module or ""
        
        for alias in node.names:
            local_name = alias.asname or alias.name
            self.current_scope.defined.add(local_name)
            
            full_path = f"{resolved_module}.{alias.name}" if resolved_module else alias.name
            if full_path in self.project_modules:
                self.current_scope.defined_imports[local_name] = full_path

class NameCollector(ast.NodeVisitor):
    def __init__(self):
        self.names = set()

    def visit_Name(self, node):
        self.names.add(node.id)
        self.generic_visit(node)

    def visit_FunctionDef(self, node):
        self.names.add(node.name)
        self.generic_visit(node)

    def visit_AsyncFunctionDef(self, node):
        self.names.add(node.name)
        self.generic_visit(node)

    def visit_ClassDef(self, node):
        self.names.add(node.name)
        self.generic_visit(node)

    def visit_Import(self, node):
        for alias in node.names:
            self.names.add(alias.asname or alias.name.split('.')[0])
        self.generic_visit(node)

    def visit_ImportFrom(self, node):
        for alias in node.names:
            self.names.add(alias.asname or alias.name)
        self.generic_visit(node)

class KeywordArgCollector(ast.NodeVisitor):
    def __init__(self):
        self.keywords = set()

    def visit_Call(self, node):
        for kw in node.keywords:
            if kw.arg:
                self.keywords.add(kw.arg)
        self.generic_visit(node)

class PrivateAttrCollector(ast.NodeVisitor):
    def __init__(self):
        self.private_attrs = set()

    def visit_Attribute(self, node):
        if self._is_private(node.attr):
            self.private_attrs.add(node.attr)
        self.generic_visit(node)

    def visit_FunctionDef(self, node):
        if self._is_private(node.name):
            self.private_attrs.add(node.name)
        self.generic_visit(node)

    def visit_Name(self, node):
        if isinstance(node.ctx, ast.Store) and self._is_private(node.id):
            self.private_attrs.add(node.id)
        self.generic_visit(node)

    def _is_private(self, name):
        return name.startswith('_') and not name.endswith('__') and name != '_'

# =====================================================================
# NAME GENERATOR
# =====================================================================

class NameGenerator:
    def __init__(self, style="hex"):
        self.style = style
        self.counter = 0
        self.existing = set()

    def get_next(self):
        while True:
            self.counter += 1
            if self.style == "confusing":
                chars = ['l', 'O', 'I']
                temp = self.counter
                result = []
                while temp > 0:
                    result.append(chars[temp % 3])
                    temp //= 3
                candidate = "l" + "".join(result)
            else:
                candidate = f"_0x{self.counter:x}"
            if candidate not in self.existing:
                return candidate

# =====================================================================
# AST TRANSFORMERS
# =====================================================================

class DocstringRemover(ast.NodeTransformer):
    def visit_Module(self, node):
        self.generic_visit(node)
        self._remove_docstring(node.body)
        return node

    def visit_ClassDef(self, node):
        self.generic_visit(node)
        self._remove_docstring(node.body)
        return node

    def visit_FunctionDef(self, node):
        self.generic_visit(node)
        self._remove_docstring(node.body)
        return node

    def visit_AsyncFunctionDef(self, node):
        self.generic_visit(node)
        self._remove_docstring(node.body)
        return node

    def _remove_docstring(self, body):
        if not body:
            return
        first = body[0]
        if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant) and isinstance(first.value.value, str):
            body.pop(0)
            if not body:
                body.append(ast.Pass())

class FStringRewriter(ast.NodeTransformer):
    def visit_JoinedStr(self, node):
        if not node.values:
            return ast.Constant(value="")
        
        exprs = []
        for val in node.values:
            if isinstance(val, ast.Constant):
                exprs.append(val)
            elif isinstance(val, ast.FormattedValue):
                transformed_value = self.visit(val.value)
                if val.format_spec:
                    transformed_spec = self.visit(val.format_spec)
                    exprs.append(
                        ast.Call(
                            func=ast.Name(id='format', ctx=ast.Load()),
                            args=[transformed_value, transformed_spec],
                            keywords=[]
                        )
                    )
                else:
                    exprs.append(
                        ast.Call(
                            func=ast.Name(id='str', ctx=ast.Load()),
                            args=[transformed_value],
                            keywords=[]
                        )
                    )
            else:
                exprs.append(self.visit(val))
        
        result = exprs[0]
        for expr in exprs[1:]:
            result = ast.BinOp(left=result, op=ast.Add(), right=expr)
            
        return result



class StringObfuscator(ast.NodeTransformer):
    def __init__(self, level, decoder_name="_0x_dec"):
        self.level = level
        self.decoder_name = decoder_name
        self.string_count = 0

    def visit_Constant(self, node):
        if isinstance(node.value, str):
            if self.level == "basic":
                return node
                
            self.string_count += 1
            
            if self.level == "medium":
                # Medium level: hex encoding
                val_bytes = node.value.encode('utf-8')
                return ast.Call(
                    func=ast.Attribute(
                        value=ast.Call(
                            func=ast.Name(id='bytes', ctx=ast.Load()),
                            args=[ast.List(elts=[ast.Constant(value=b) for b in val_bytes], ctx=ast.Load())],
                            keywords=[]
                        ),
                        attr='decode',
                        ctx=ast.Load()
                    ),
                    args=[ast.Constant(value='utf-8')],
                    keywords=[]
                )
            else: # strong or extreme
                # Strong/Extreme level: XOR encryption
                key = random.randint(1, 255)
                val_bytes = node.value.encode('utf-8')
                xor_bytes = bytes([b ^ key for b in val_bytes])
                return ast.Call(
                    func=ast.Name(id=self.decoder_name, ctx=ast.Load()),
                    args=[
                        ast.Constant(value=xor_bytes),
                        ast.Constant(value=key)
                    ],
                    keywords=[]
                )
        return node

class NumberObfuscator(ast.NodeTransformer):
    def visit_Constant(self, node):
        # Obfuscate integer constants
        if isinstance(node.value, int) and not isinstance(node.value, bool):
            if abs(node.value) < 1000000:
                r = random.randint(100, 100000)
                xor_val = node.value ^ r
                return ast.BinOp(
                    left=ast.Constant(value=xor_val),
                    op=ast.BitXor(),
                    right=ast.Constant(value=r)
                )
        # Obfuscate boolean constants
        elif isinstance(node.value, bool):
            r = random.randint(10, 100)
            if node.value:
                return ast.Compare(
                    left=ast.Constant(value=r),
                    ops=[ast.Eq()],
                    comparators=[ast.Constant(value=r)]
                )
            else:
                return ast.Compare(
                    left=ast.Constant(value=r),
                    ops=[ast.NotEq()],
                    comparators=[ast.Constant(value=r)]
                )
        return node

class BuiltinObfuscator(ast.NodeTransformer):
    def __init__(self, scope_tree, node_scopes, builtins_module_name, getattr_name):
        self.scope_tree = scope_tree
        self.node_scopes = node_scopes
        self.builtins_module_name = builtins_module_name
        self.getattr_name = getattr_name
        self.builtin_names = set(dir(builtins))

    def visit_Name(self, node):
        if isinstance(node.ctx, ast.Load) and node.id in self.builtin_names:
            scope = self.node_scopes.get(node)
            if scope:
                resolved = resolve_scope(scope, node.id)
                if resolved is not None:
                    # Locally/globally defined symbol shadows the builtin
                    return node
            
            # Replace builtin call with getattr dynamic lookup
            return ast.Call(
                func=ast.Name(id=self.getattr_name, ctx=ast.Load()),
                args=[
                    ast.Name(id=self.builtins_module_name, ctx=ast.Load()),
                    ast.Constant(value=node.id)
                ],
                keywords=[]
            )
        return node

class ControlFlowFlattener(ast.NodeTransformer):
    def __init__(self, state_var_prefix="_state_"):
        self.state_var_prefix = state_var_prefix
        self.counter = 0

    def visit_FunctionDef(self, node):
        self.generic_visit(node)
        # Exclude dunder methods from flow flattening
        if not (node.name.startswith('__') and node.name.endswith('__')):
            node.body = self._flatten_body(node.body)
        return node

    def visit_AsyncFunctionDef(self, node):
        self.generic_visit(node)
        if not (node.name.startswith('__') and node.name.endswith('__')):
            node.body = self._flatten_body(node.body)
        return node

    def _flatten_body(self, body):
        declarations = []
        real_stmts = []
        for stmt in body:
            if isinstance(stmt, (ast.Global, ast.Nonlocal)):
                declarations.append(stmt)
            else:
                real_stmts.append(stmt)
                
        # Only flatten if there are multiple statements and no generator/yield statements
        if len(real_stmts) < 2 or self._has_yield(ast.Module(body=real_stmts, type_ignores=[])):
            return body
            
        self.counter += 1
        state_var = f"{self.state_var_prefix}{self.counter}"
        
        N = len(real_stmts)
        state_vals = random.sample(range(1000, 99999), N + 1)
        start_state = state_vals[0]
        end_state = state_vals[-1]
        
        blocks = []
        for i in range(N):
            blocks.append((state_vals[i], real_stmts[i], state_vals[i+1]))
            
        random.shuffle(blocks)
        
        assign_init = ast.Assign(
            targets=[ast.Name(id=state_var, ctx=ast.Store())],
            value=ast.Constant(value=start_state)
        )
        
        loop_test = ast.Compare(
            left=ast.Name(id=state_var, ctx=ast.Load()),
            ops=[ast.NotEq()],
            comparators=[ast.Constant(value=end_state)]
        )
        
        if_chain = self._build_if_chain(blocks, state_var)
        loop = ast.While(test=loop_test, body=if_chain, orelse=[])
        
        return declarations + [assign_init, loop]

    def _has_yield(self, node):
        for n in ast.walk(node):
            if isinstance(n, (ast.Yield, ast.YieldFrom)):
                return True
        return False

    def _build_if_chain(self, blocks, state_var):
        current_orelse = []
        for state_val, stmt_node, next_state_val in reversed(blocks):
            block_body = []
            if isinstance(stmt_node, list):
                block_body.extend(stmt_node)
            else:
                block_body.append(stmt_node)
                
            transition = ast.Assign(
                targets=[ast.Name(id=state_var, ctx=ast.Store())],
                value=ast.Constant(value=next_state_val)
            )
            block_body.append(transition)
            
            test = ast.Compare(
                left=ast.Name(id=state_var, ctx=ast.Load()),
                ops=[ast.Eq()],
                comparators=[ast.Constant(value=state_val)]
            )
            current_orelse = [ast.If(test=test, body=block_body, orelse=current_orelse)]
            
        return current_orelse

class IdentifierRenamer(ast.NodeTransformer):
    def __init__(self, node_scopes, name_mappings, private_attr_map, project_modules, project_globals, current_module, is_package=False):
        self.node_scopes = node_scopes
        self.mappings = name_mappings
        self.private_attr_map = private_attr_map
        self.project_modules = project_modules
        self.project_globals = project_globals
        self.current_module = current_module
        self.is_package = is_package
        self.current_scope = None

    def visit_Module(self, node):
        self.current_scope = self.node_scopes[node]
        self.generic_visit(node)
        return node

    def visit_ClassDef(self, node):
        parent_scope = self.current_scope
        key = (parent_scope, node.name)
        if key in self.mappings:
            node.name = self.mappings[key]
        elif self.project_globals is not None and self.current_module is not None:
            proj_key = (self.current_module, node.name)
            if proj_key in self.project_globals:
                node.name = self.project_globals[proj_key]
                
        self.current_scope = self.node_scopes[node]
        self.generic_visit(node)
        self.current_scope = parent_scope
        return node

    def visit_FunctionDef(self, node):
        parent_scope = self.current_scope
        
        if parent_scope and parent_scope.is_class and node.name in self.private_attr_map:
            node.name = self.private_attr_map[node.name]
        else:
            key = (parent_scope, node.name)
            if key in self.mappings:
                node.name = self.mappings[key]
            elif self.project_globals is not None and self.current_module is not None:
                proj_key = (self.current_module, node.name)
                if proj_key in self.project_globals:
                    node.name = self.project_globals[proj_key]
                    
        self.current_scope = self.node_scopes[node]
        
        # Rename function parameter/argument variables
        for arg in node.args.posonlyargs + node.args.args + node.args.kwonlyargs:
            key = (self.current_scope, arg.arg)
            if key in self.mappings:
                arg.arg = self.mappings[key]
        if node.args.vararg:
            key = (self.current_scope, node.args.vararg.arg)
            if key in self.mappings:
                node.args.vararg.arg = self.mappings[key]
        if node.args.kwarg:
            key = (self.current_scope, node.args.kwarg.arg)
            if key in self.mappings:
                node.args.kwarg.arg = self.mappings[key]
                
        self.generic_visit(node)
        self.current_scope = parent_scope
        return node

    def visit_AsyncFunctionDef(self, node):
        return self.visit_FunctionDef(node)

    def visit_Name(self, node):
        if self.current_scope and self.current_scope.is_class and node.id in self.private_attr_map:
            node.id = self.private_attr_map[node.id]
            return node
            
        scope = resolve_scope(self.current_scope, node.id)
        if scope:
            key = (scope, node.id)
            if key in self.mappings:
                node.id = self.mappings[key]
            elif scope.parent is None and self.project_globals is not None and self.current_module is not None:
                proj_key = (self.current_module, node.id)
                if proj_key in self.project_globals:
                    node.id = self.project_globals[proj_key]
        return node

    def visit_Attribute(self, node):
        self.generic_visit(node)
        
        if node.attr in self.private_attr_map:
            node.attr = self.private_attr_map[node.attr]
            return node
            
        res = resolve_attribute_chain(node.value, self.current_scope)
        if res:
            mod_path, attrs = res
            full_mod = f"{mod_path}.{'.'.join(attrs)}" if attrs else mod_path
            if full_mod in self.project_modules and self.project_globals is not None:
                proj_key = (full_mod, node.attr)
                if proj_key in self.project_globals:
                    node.attr = self.project_globals[proj_key]
        return node

    def visit_Import(self, node):
        for alias in node.names:
            local_name = alias.asname or alias.name.split('.')[0]
            scope = resolve_scope(self.current_scope, local_name)
            if scope:
                key = (scope, local_name)
                if key in self.mappings:
                    alias.asname = self.mappings[key]
                elif scope.parent is None and self.project_globals is not None and self.current_module is not None:
                    proj_key = (self.current_module, local_name)
                    if proj_key in self.project_globals:
                        alias.asname = self.project_globals[proj_key]
        return node

    def visit_ImportFrom(self, node):
        if node.level > 0:
            resolved_module = resolve_relative_import(self.current_module, self.is_package, node.level, node.module)
        else:
            resolved_module = node.module or ""
                
        for alias in node.names:
            local_name = alias.asname or alias.name
            is_proj = False
            
            if resolved_module in self.project_modules and self.project_globals is not None:
                proj_key = (resolved_module, alias.name)
                if proj_key in self.project_globals:
                    alias.name = self.project_globals[proj_key]
                    is_proj = True
                    
            scope = resolve_scope(self.current_scope, local_name)
            if scope:
                key = (scope, local_name)
                if key in self.mappings:
                    alias.asname = self.mappings[key]
                elif is_proj and self.project_globals is not None:
                    alias.asname = alias.name
        return node

    def visit_Global(self, node):
        new_names = []
        for name in node.names:
            scope = resolve_scope(self.current_scope, name)
            if scope:
                key = (scope, name)
                if key in self.mappings:
                    new_names.append(self.mappings[key])
                elif scope.parent is None and self.project_globals is not None and self.current_module is not None:
                    proj_key = (self.current_module, name)
                    if proj_key in self.project_globals:
                        new_names.append(self.project_globals[proj_key])
                    else:
                        new_names.append(name)
                else:
                    new_names.append(name)
            else:
                new_names.append(name)
        node.names = new_names
        return node

    def visit_Nonlocal(self, node):
        new_names = []
        for name in node.names:
            scope = resolve_scope(self.current_scope, name)
            if scope:
                key = (scope, name)
                if key in self.mappings:
                    new_names.append(self.mappings[key])
                else:
                    new_names.append(name)
            else:
                new_names.append(name)
        node.names = new_names
        return node

# =====================================================================
# CORE OBFUSCATION PIPELINE
# =====================================================================

def obfuscate_source(source_code, level, renaming_style, project_modules=None, project_globals=None, current_module=None, is_package=False, keyword_args=None):
    tree = ast.parse(source_code)
    
    # 1. Remove docstrings
    tree = DocstringRemover().visit(tree)
    
    # 2. Rewrite F-Strings to additions
    tree = FStringRewriter().visit(tree)
    
    # 3. Collect keyword arguments from calls
    if keyword_args is None:
        kw_collector = KeywordArgCollector()
        kw_collector.visit(tree)
        keyword_args = kw_collector.keywords
        
    mappings_count = 0
    
    # 4. Identifier Renaming (Medium, Strong, Extreme)
    if level in ("medium", "strong", "extreme"):
        collector = NameCollector()
        collector.visit(tree)
        existing_names = collector.names
        
        name_generator = NameGenerator(style=renaming_style)
        name_generator.existing = existing_names
        
        scope_builder = ScopeBuilder(project_modules or set(), current_module, is_package)
        scope_builder.visit(tree)
        scope_tree = scope_builder.current_scope
        node_scopes = scope_builder.node_scopes
        
        # Collect and map private attributes globally
        private_collector = PrivateAttrCollector()
        private_collector.visit(tree)
        private_attrs = private_collector.private_attrs
        
        private_attr_map = {}
        for attr in private_attrs:
            while True:
                candidate = name_generator.get_next()
                if candidate not in existing_names:
                    private_attr_map[attr] = candidate
                    break
                    
        # Build mappings
        mappings = build_name_mappings(
            tree, scope_tree, node_scopes, name_generator, keyword_args,
            project_globals=project_globals, current_module=current_module
        )
        mappings_count = len(mappings) + len(private_attr_map)
        
        # Run identifier renamer
        renamer = IdentifierRenamer(
            node_scopes, mappings, private_attr_map,
            project_modules or set(), project_globals, current_module, is_package
        )
        tree = renamer.visit(tree)
        
        # Re-build scope tree for BuiltinObfuscator
        scope_builder = ScopeBuilder(project_modules or set(), current_module, is_package)
        scope_builder.visit(tree)
        node_scopes = scope_builder.node_scopes
        scope_tree = scope_builder.current_scope
    else:
        node_scopes = {}
        scope_tree = None
        
    # 5. String Obfuscator
    string_obf = StringObfuscator(level)
    tree = string_obf.visit(tree)
    
    # 6. Constant Obfuscator (Extreme Mode)
    if level == "extreme":
        tree = NumberObfuscator().visit(tree)
        
    # 7. Builtin Obfuscator (Extreme Mode)
    if level == "extreme":
        builtin_obf = BuiltinObfuscator(scope_tree, node_scopes, "_0x_builtins", "_0x_getattr")
        tree = builtin_obf.visit(tree)
        
    # 8. Control Flow Flattening (Extreme Mode)
    if level == "extreme":
        tree = ControlFlowFlattener().visit(tree)
        
    # 9. Inject helpers
    if level in ("strong", "extreme"):
        if level == "extreme":
            helper_code = """
import builtins as _0x_builtins
_0x_getattr = _0x_builtins.getattr
def _0x_dec(b, k):
    return bytearray(x ^ k for x in b).decode('utf-8')
"""
        else: # strong
            helper_code = """
def _0x_dec(b, k):
    return bytearray(x ^ k for x in b).decode('utf-8')
"""
        helper_ast = ast.parse(helper_code).body
        tree.body = helper_ast + tree.body
        
    # Fix and unparse
    ast.fix_missing_locations(tree)
    obfuscated_code = ast.unparse(tree)
    
    # AST Round-trip safety validation
    try:
        ast.parse(obfuscated_code)
    except Exception as e:
        raise ValueError(f"Generated code is syntactically invalid: {e}")
        
    return obfuscated_code, mappings_count, string_obf.string_count

def build_name_mappings(root_node, scope_tree, node_scopes, name_generator, keyword_args, project_globals=None, current_module=None):
    mappings = {}
    builtin_names = set(dir(builtins))
    preserved_names = {'__main__', '__name__', 'main', 'self', 'cls'}
    
    root_scope = scope_tree
    
    # Map globals
    for name in root_scope.defined:
        if name.startswith('__') and name.endswith('__'):
            continue
        if name in builtin_names or name in preserved_names:
            continue
            
        if project_globals is not None and current_module is not None:
            key = (current_module, name)
            if key in project_globals:
                new_name = project_globals[key]
            else:
                new_name = name_generator.get_next()
                project_globals[key] = new_name
        else:
            new_name = name_generator.get_next()
            
        mappings[(root_scope, name)] = new_name

    # Recursive mapper for child scopes (local variables/args)
    def map_scope(scope):
        if not scope.is_class:
            for name in scope.defined:
                if name.startswith('__') and name.endswith('__'):
                    continue
                if name in builtin_names or name in preserved_names:
                    continue
                if name in keyword_args:
                    continue
                    
                new_name = name_generator.get_next()
                mappings[(scope, name)] = new_name
                
        for child in scope.children:
            map_scope(child)
            
    for child in root_scope.children:
        map_scope(child)
        
    return mappings

# =====================================================================
# PROJECT & FILE PROCESSORS
# =====================================================================

def process_file(src_file, dest_file, level, renaming_style):
    with open(src_file, 'r', encoding='utf-8') as f:
        code = f.read()
        
    obf_code, renamed, strings = obfuscate_source(
        code, level, renaming_style
    )
    
    with open(dest_file, 'w', encoding='utf-8') as f:
        f.write(obf_code)
        
    return {
        'files_processed': 1,
        'renamed_identifiers': renamed,
        'strings_obfuscated': strings,
        'errors': []
    }

def process_project(src_dir, dest_dir, level, renaming_style):
    src_dir = os.path.abspath(src_dir)
    dest_dir = os.path.abspath(dest_dir)
    
    py_files = []
    other_files = []
    
    for root, dirs, files in os.walk(src_dir):
        if os.path.commonpath([root, dest_dir]) == dest_dir:
            continue
            
        for file in files:
            full_path = os.path.join(root, file)
            rel_path = os.path.relpath(full_path, src_dir)
            if file.endswith('.py'):
                py_files.append((full_path, rel_path))
            else:
                other_files.append((full_path, rel_path))
                
    project_modules = set()
    file_modules = {}
    
    for full_path, rel_path in py_files:
        mod_name = get_module_name(full_path, src_dir)
        project_modules.add(mod_name)
        file_modules[full_path] = mod_name
        
    # Scan all files for keyword arguments and existing names
    keyword_args = set()
    all_existing_names = set()
    
    for full_path, _ in py_files:
        try:
            with open(full_path, 'r', encoding='utf-8') as f:
                code = f.read()
            tree = ast.parse(code)
            
            collector = NameCollector()
            collector.visit(tree)
            all_existing_names.update(collector.names)
            
            kw_collector = KeywordArgCollector()
            kw_collector.visit(tree)
            keyword_args.update(kw_collector.keywords)
        except Exception as e:
            print(f"Warning: Failed to parse {full_path}: {e}")
            
    name_generator = NameGenerator(style=renaming_style)
    name_generator.existing = all_existing_names
    
    # Pre-map project globals
    project_globals = {}
    builtin_names = set(dir(builtins))
    preserved_names = {'__main__', '__name__', 'main', 'self', 'cls'}
    
    for full_path, _ in py_files:
        mod_name = file_modules.get(full_path)
        if not mod_name:
            continue
        try:
            with open(full_path, 'r', encoding='utf-8') as f:
                code = f.read()
            tree = ast.parse(code)
            
            is_pkg = os.path.basename(full_path) == '__init__.py'
            scope_builder = ScopeBuilder(project_modules, mod_name, is_pkg)
            scope_builder.visit(tree)
            root_scope = scope_builder.current_scope
            
            for name in root_scope.defined:
                if name.startswith('__') and name.endswith('__'):
                    continue
                if name in builtin_names or name in preserved_names:
                    continue
                key = (mod_name, name)
                if key not in project_globals:
                    project_globals[key] = name_generator.get_next()
        except Exception:
            pass
            
    # Recreate structure and copy other assets
    if not os.path.exists(dest_dir):
        os.makedirs(dest_dir)
        
    for full_path, rel_path in other_files:
        dest_path = os.path.join(dest_dir, rel_path)
        dest_parent = os.path.dirname(dest_path)
        if not os.path.exists(dest_parent):
            os.makedirs(dest_parent)
        shutil.copy2(full_path, dest_path)
        
    stats = {
        'files_processed': 0,
        'renamed_identifiers': 0,
        'strings_obfuscated': 0,
        'errors': []
    }
    
    for full_path, rel_path in py_files:
        dest_path = os.path.join(dest_dir, rel_path)
        dest_parent = os.path.dirname(dest_path)
        if not os.path.exists(dest_parent):
            os.makedirs(dest_parent)
            
        mod_name = file_modules[full_path]
        is_pkg = os.path.basename(full_path) == '__init__.py'
        
        try:
            with open(full_path, 'r', encoding='utf-8') as f:
                code = f.read()
                
            obf_code, renamed, strings = obfuscate_source(
                code, level, renaming_style,
                project_modules=project_modules,
                project_globals=project_globals,
                current_module=mod_name,
                is_package=is_pkg,
                keyword_args=keyword_args
            )
            
            with open(dest_path, 'w', encoding='utf-8') as f:
                f.write(obf_code)
                
            stats['files_processed'] += 1
            stats['renamed_identifiers'] += renamed
            stats['strings_obfuscated'] += strings
        except Exception as e:
            stats['errors'].append((rel_path, str(e)))
            print(f"Error obfuscating {rel_path}: {e}")
            
    return stats

# =====================================================================
# CLI / TUI INTERFACE
# =====================================================================

def print_logo():
    logo = r"""
\033[1;35m  ____  _                                
 / __ \| |                               
| |  | | |__  ___  ___ _   _ _ __ __ _   
| |  | | '_ \\/ __|/ __| | | | '__/ _` |  
| |__| | |_) \\__ \\ (__| |_| | | | (_| |  
 \\____/|_.__/|___/\\___|\\__,_|_|  \\__,_|  \033[0m
\033[1;36m     AST-Based Python Source Obfuscator v1.0.0\033[0m
\033[1;37m     Compatible with Python 3.10+ | Single Script\033[0m
"""
    print(logo)

def print_summary(stats, elapsed_time, output_path):
    print("\n\033[1;32m==================================================\033[0m")
    print("\033[1;32m               OBFUSCATION COMPLETE               \033[0m")
    print("\033[1;32m==================================================\033[0m")
    print(f" Files Processed:      {stats['files_processed']}")
    print(f" Identifiers Renamed:  {stats['renamed_identifiers']}")
    print(f" Strings Obfuscated:   {stats['strings_obfuscated']}")
    print(f" Processing Time:      {elapsed_time:.3f} seconds")
    
    if os.path.isfile(output_path):
        size_bytes = os.path.getsize(output_path)
        print(f" Output File Size:     {size_bytes:,} bytes")
    elif os.path.isdir(output_path):
        total_size = 0
        for root, _, files in os.walk(output_path):
            for f in files:
                total_size += os.path.getsize(os.path.join(root, f))
        print(f" Output Folder Size:   {total_size:,} bytes")
        
    print(f" Output Location:      {output_path}")
    
    if stats['errors']:
        print("\033[1;31m\nErrors Encountered:\033[0m")
        for rel_path, err in stats['errors']:
            print(f" - {rel_path}: {err}")
            
    print("\033[1;32m==================================================\033[0m")

def select_level_interactive():
    print("\nSelect Obfuscation Level:")
    print(" [1] Basic   - Strips comments/docstrings.")
    print(" [2] Medium  - Strips comments/docstrings, renames local variables, escapes strings.")
    print(" [3] Strong  - Strips comments/docstrings, renames globals/locals, XOR encrypts strings. (Recommended)")
    print(" [4] Extreme - Strong + control flow flattening + math obfuscation + builtin hiding.")
    
    while True:
        lvl = input("Level [1-4]: ").strip()
        if lvl == "1":
            return "basic"
        elif lvl == "2":
            return "medium"
        elif lvl == "3":
            return "strong"
        elif lvl == "4":
            return "extreme"
        print("\033[1;31mInvalid choice. Try again.\033[0m")

def select_style_interactive(level):
    if level == "basic":
        return "hex"
    print("\nSelect Identifier Renaming Style:")
    print(" [1] Hexadecimal (`_0x1a`) - Clean and standard.")
    print(" [2] Confusing (`lO1lIO`)   - Hard to distinguish in typical editors.")
    
    while True:
        style = input("Style [1-2]: ").strip()
        if style == "1":
            return "hex"
        elif style == "2":
            return "confusing"
        print("\033[1;31mInvalid choice. Try again.\033[0m")

def obfuscate_single_file_flow():
    print("\n--- Obfuscate Single File ---")
    while True:
        src = input("Drag & drop file path here (or type path): ").strip().strip('\'"')
        if not src:
            return
        if not os.path.isfile(src):
            print("\033[1;31mError: File not found.\033[0m")
            continue
        break
        
    level = select_level_interactive()
    style = select_style_interactive(level)
    
    default_dest = src.rsplit('.', 1)[0] + "_obf.py"
    dest = input(f"Output path [{default_dest}]: ").strip().strip('\'"')
    if not dest:
        dest = default_dest
        
    start_time = time.time()
    print(f"\nObfuscating {os.path.basename(src)}...")
    try:
        stats = process_file(src, dest, level, style)
        print_summary(stats, time.time() - start_time, dest)
    except Exception as e:
        print(f"\033[1;31mObfuscation failed: {e}\033[0m")

def obfuscate_project_flow():
    print("\n--- Obfuscate Project Folder ---")
    while True:
        src = input("Drag & drop folder path here (or type path): ").strip().strip('\'"')
        if not src:
            return
        if not os.path.isdir(src):
            print("\033[1;31mError: Directory not found.\033[0m")
            continue
        break
        
    level = select_level_interactive()
    style = select_style_interactive(level)
    
    default_dest = src.rstrip('/\\') + "_obf"
    dest = input(f"Output folder path [{default_dest}]: ").strip().strip('\'"')
    if not dest:
        dest = default_dest
        
    start_time = time.time()
    print(f"\nObfuscating project {os.path.basename(src)}...")
    try:
        stats = process_project(src, dest, level, style)
        print_summary(stats, time.time() - start_time, dest)
    except Exception as e:
        print(f"\033[1;31mObfuscation failed: {e}\033[0m")

def run_interactive():
    print_logo()
    while True:
        print("\n\033[1;36m==================================================\033[0m")
        print("\033[1;36m                OBSCURA OBFUSCATOR                \033[0m")
        print("\033[1;36m==================================================\033[0m")
        print(" [1] Obfuscate Single Python File")
        print(" [2] Obfuscate Project Folder")
        print(" [3] Exit")
        print("\033[1;36m==================================================\033[0m")
        
        choice = input("Select an option [1-3]: ").strip()
        if choice == "3":
            print("\nGoodbye!")
            break
        elif choice == "1":
            obfuscate_single_file_flow()
        elif choice == "2":
            obfuscate_project_flow()
        else:
            print("\033[1;31mInvalid choice. Please select 1, 2, or 3.\033[0m")

def main():
    parser = argparse.ArgumentParser(description="Obscura: Professional AST-Based Python Obfuscator")
    parser.add_argument("-f", "--file", help="Path to a single Python file to obfuscate")
    parser.add_argument("-d", "--directory", help="Path to a folder/project to obfuscate")
    parser.add_argument("-o", "--output", help="Output path (file name for single-file, folder name for project)")
    parser.add_argument("-l", "--level", choices=["basic", "medium", "strong", "extreme"], default=None,
                        help="Obfuscation level: basic, medium, strong, extreme")
    parser.add_argument("-s", "--style", choices=["hex", "confusing"], default="hex",
                        help="Variable renaming style: hex, confusing")
    parser.add_argument("-i", "--interactive", action="store_true", help="Force interactive mode")
    
    args = parser.parse_args()
    
    # If no arguments are provided, or interactive flag is set, run interactive mode
    if len(sys.argv) == 1 or args.interactive:
        run_interactive()
    else:
        if not args.file and not args.directory:
            print("Error: You must specify either -f/--file or -d/--directory.")
            sys.exit(1)
            
        level = args.level or "strong"
        style = args.style
        start_time = time.time()
        
        if args.file:
            src = args.file.strip('\'"')
            if not os.path.isfile(src):
                print(f"Error: File not found: {src}")
                sys.exit(1)
            dest = args.output or (src.rsplit('.', 1)[0] + "_obf.py")
            print(f"Obfuscating file: {src} -> {dest} (Level: {level}, Style: {style})...")
            try:
                stats = process_file(src, dest, level, style)
                print_summary(stats, time.time() - start_time, dest)
            except Exception as e:
                print(f"Obfuscation failed: {e}")
                sys.exit(1)
        else:
            src = args.directory.strip('\'"')
            if not os.path.isdir(src):
                print(f"Error: Directory not found: {src}")
                sys.exit(1)
            dest = args.output or (src.rstrip('/\\') + "_obf")
            print(f"Obfuscating project: {src} -> {dest} (Level: {level}, Style: {style})...")
            try:
                stats = process_project(src, dest, level, style)
                print_summary(stats, time.time() - start_time, dest)
            except Exception as e:
                print(f"Obfuscation failed: {e}")
                sys.exit(1)

if __name__ == "__main__":
    main()
