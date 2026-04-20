"""
JavaScript Dead Code Analyzer
==============================
Pure Python static analyzer for JavaScript dead code detection.
No external dependencies required — works alongside dce_engine.py.

Detects:
  1. Unused variables  (let/const/var declared but never read)
  2. Unused functions  (function declarations never called/referenced)
  3. Unreachable code  (statements after return/throw/break/continue)
  4. Dead branches     (if(false)/while(false)/if(0) etc.)

Returns JSON-serializable output compatible with the web UI.
"""

import re
import json
from typing import Optional, List, Dict, Set

# ─────────────────────────────────────────────────────────────────────────────
# 1.  CONSTANTS
# ─────────────────────────────────────────────────────────────────────────────

_JS_KEYWORDS: Set[str] = frozenset({
    # Language keywords
    'break', 'case', 'catch', 'class', 'const', 'continue', 'debugger',
    'default', 'delete', 'do', 'else', 'export', 'extends', 'false',
    'finally', 'for', 'function', 'if', 'import', 'in', 'instanceof',
    'let', 'new', 'null', 'of', 'return', 'static', 'super', 'switch',
    'this', 'throw', 'true', 'try', 'typeof', 'undefined', 'var', 'void',
    'while', 'with', 'yield', 'async', 'await',
    # Common built-ins — always considered live
    'console', 'Math', 'Array', 'Object', 'String', 'Number', 'Boolean',
    'Promise', 'JSON', 'Date', 'RegExp', 'Error', 'Map', 'Set', 'Symbol',
    'WeakMap', 'WeakSet', 'Proxy', 'Reflect',
    'parseInt', 'parseFloat', 'isNaN', 'isFinite',
    'encodeURI', 'decodeURI', 'encodeURIComponent', 'decodeURIComponent',
    'setTimeout', 'setInterval', 'clearTimeout', 'clearInterval',
    'requestAnimationFrame', 'cancelAnimationFrame',
    'window', 'document', 'navigator', 'location', 'history',
    'localStorage', 'sessionStorage', 'fetch', 'XMLHttpRequest',
    'process', 'require', 'module', 'exports',
    '__dirname', '__filename', 'global', 'Buffer',
    'setImmediate', 'clearImmediate', 'Infinity', 'NaN',
    'eval', 'arguments', 'prototype', 'constructor',
    'alert', 'confirm', 'prompt', 'addEventListener', 'removeEventListener',
    'querySelector', 'querySelectorAll', 'getElementById', 'getElementsByClassName',
    'log', 'warn', 'error', 'info', 'debug', 'table', 'dir',
    'push', 'pop', 'shift', 'unshift', 'splice', 'slice', 'map', 'filter',
    'reduce', 'forEach', 'find', 'findIndex', 'includes', 'indexOf',
    'join', 'split', 'trim', 'replace', 'match', 'test', 'exec',
    'keys', 'values', 'entries', 'assign', 'freeze', 'create',
    'then', 'catch', 'finally', 'resolve', 'reject', 'all', 'race',
    'length', 'name', 'message', 'stack', 'toString', 'valueOf',
    'hasOwnProperty', 'isPrototypeOf', 'propertyIsEnumerable',
    'call', 'apply', 'bind',
})

# Dead condition patterns: if(false), while(0), if(null), etc.
_DEAD_COND_PATTERN = re.compile(
    r'^\s*(?:if|while)\s*\(\s*(false|0|null|undefined|""|\'\'|``)\s*\)',
    re.IGNORECASE
)

# Terminal statement pattern
_TERMINAL_PATTERN = re.compile(r'^\s*(return|throw|break|continue)\b')

# Variable declaration pattern
_VAR_DECL_PATTERN = re.compile(
    r'\b(var|let|const)\s+([a-zA-Z_$][a-zA-Z0-9_$]*)'
)

# Function declaration pattern
_FN_DECL_PATTERN = re.compile(
    r'\bfunction\s+([a-zA-Z_$][a-zA-Z0-9_$]*)\s*\('
)

# Identifier pattern
_IDENT_PATTERN = re.compile(r'\b([a-zA-Z_$][a-zA-Z0-9_$]*)\b')

# Call site pattern: name(
_CALL_PATTERN = re.compile(r'\b([a-zA-Z_$][a-zA-Z0-9_$]*)\s*\(')


# ─────────────────────────────────────────────────────────────────────────────
# 2.  COMMENT STRIPPING
# ─────────────────────────────────────────────────────────────────────────────

def _strip_comments(source: str) -> List[str]:
    """
    Remove JS comments while preserving line count.
    Returns list of cleaned lines (same length as original).
    """
    # Remove /* ... */ block comments (preserve line structure)
    def replace_block(m: re.Match) -> str:
        s = m.group(0)
        return '\n' * s.count('\n')

    no_block = re.sub(r'/\*.*?\*/', replace_block, source, flags=re.DOTALL)

    cleaned = []
    for line in no_block.split('\n'):
        # Remove // line comments (naive — doesn't handle // inside strings,
        # but sufficient for static dead-code heuristics)
        cleaned.append(re.sub(r'//.*$', '', line))
    return cleaned


def _strip_strings(line: str) -> str:
    """Replace string literal contents with empty placeholders."""
    line = re.sub(r'"(?:[^"\\]|\\.)*"', '""', line)
    line = re.sub(r"'(?:[^'\\]|\\.)*'", "''", line)
    line = re.sub(r'`(?:[^`\\]|\\.)*`', '``', line)
    return line


# ─────────────────────────────────────────────────────────────────────────────
# 3.  MAIN ANALYZER
# ─────────────────────────────────────────────────────────────────────────────

class JSScopeAnalyzer:
    """
    Single-pass JavaScript dead code analyzer.

    Conservative approach: when in doubt, marks a symbol as live.
    Focuses on the most common and unambiguous dead code patterns.
    """

    def __init__(self, source: str):
        self.source = source
        self.original_lines: List[str] = source.split('\n')
        n = len(self.original_lines)

        # Cleaned lines for analysis (no comments, same line count)
        self.clean_lines: List[str] = _strip_comments(source)

        # Per-line state (1-indexed; index 0 unused)
        self.line_dead:   List[bool]          = [False] * (n + 2)
        self.line_kind:   List[Optional[str]] = [None]  * (n + 2)
        self.line_reason: List[str]           = ['']    * (n + 2)

        # Symbol tables
        self._declarations: Dict[str, dict] = {}   # name → {line, decl_kind}
        self._fn_decls:     Dict[str, dict] = {}   # name → {line}
        self._references:   Set[str]        = set()  # all ident names read anywhere
        self._call_sites:   Set[str]        = set()  # function names called

        # Aggregated findings
        self.findings: List[dict] = []

    # ── public entry point ────────────────────────────────────────────────────

    def analyze(self) -> dict:
        self._pass1_collect_symbols()
        self._pass2_detect_unreachable()
        self._pass3_detect_dead_branches()
        self._pass4_compute_unused()
        # De-duplicate findings (same line, same kind)
        seen = set()
        deduped = []
        for f in self.findings:
            key = (f['line'], f['kind'], f.get('name'))
            if key not in seen:
                seen.add(key)
                deduped.append(f)
        self.findings = sorted(deduped, key=lambda f: f['line'])
        return self._build_result()

    # ── Pass 1: collect declarations and all references ───────────────────────

    def _pass1_collect_symbols(self):
        for lineno, raw_line in enumerate(self.clean_lines, 1):
            line = raw_line

            # ── Variable declarations ──
            for m in _VAR_DECL_PATTERN.finditer(line):
                decl_kind, name = m.group(1), m.group(2)
                if name not in self._declarations:
                    self._declarations[name] = {'line': lineno, 'decl_kind': decl_kind}

            # ── Function declarations ──
            for m in _FN_DECL_PATTERN.finditer(line):
                name = m.group(1)
                if name not in self._fn_decls:
                    self._fn_decls[name] = {'line': lineno}

            # ── Reference scanning ──
            # Blank out var/let/const NAME and function NAME so the declared
            # identifier itself doesn't count as a reference on that line.
            ref_line = _VAR_DECL_PATTERN.sub(
                lambda m: ' ' * len(m.group(0)), line)
            ref_line = _FN_DECL_PATTERN.sub(
                lambda m: ' ' * len(m.group(0)), ref_line)
            # Strip string contents to avoid idents inside strings
            ref_line = _strip_strings(ref_line)

            for m in _IDENT_PATTERN.finditer(ref_line):
                tok = m.group(1)
                if tok not in _JS_KEYWORDS:
                    self._references.add(tok)

            # ── Call sites: name( ──
            for m in _CALL_PATTERN.finditer(line):
                name = m.group(1)
                if name not in _JS_KEYWORDS:
                    self._call_sites.add(name)

    # ── Pass 2: unreachable code after return/throw/break/continue ────────────

    def _pass2_detect_unreachable(self):
        """
        Track brace depth and set of depths where a terminal statement fired.
        Lines at a depth that already saw a terminal are unreachable.
        """
        brace_depth = 0
        terminal_at: Set[int] = set()   # depths that have a terminal stmt

        for lineno, line in enumerate(self.clean_lines, 1):
            stripped = line.strip()
            if not stripped:
                continue

            # Count braces on this line
            open_cnt  = stripped.count('{')
            close_cnt = stripped.count('}')

            # ── Handle closing braces first ──
            if stripped.startswith('}'):
                # Pop depth levels as we close braces
                for _ in range(close_cnt):
                    terminal_at.discard(brace_depth)
                    brace_depth = max(0, brace_depth - 1)

                # What's left after the closing brace(s)?
                remainder = stripped.lstrip('}').strip()
                if not remainder:
                    continue

                # Process remainder as a normal statement at current depth
                if brace_depth in terminal_at:
                    self._mark_dead(lineno, 'unreachable',
                                    'Code after return/throw/break/continue')

                if _TERMINAL_PATTERN.match(remainder):
                    terminal_at.add(brace_depth)

                brace_depth += remainder.count('{') - remainder.count('}')
                brace_depth = max(0, brace_depth)
                continue

            # ── Not starting with '}': check if current depth is terminal ──
            if brace_depth in terminal_at:
                if not stripped.startswith('//'):
                    self._mark_dead(lineno, 'unreachable',
                                    'Code after return/throw/break/continue')

            # ── Check if THIS line introduces a terminal ──
            if _TERMINAL_PATTERN.match(line):
                terminal_at.add(brace_depth)

            # ── Update brace depth ──
            net = open_cnt - close_cnt
            brace_depth = max(0, brace_depth + net)

            # Remove terminal markers for depths we've left
            if net < 0:
                for d in list(terminal_at):
                    if d > brace_depth:
                        terminal_at.discard(d)

    # ── Pass 3: dead branches if(false)/while(false) ─────────────────────────

    def _pass3_detect_dead_branches(self):
        """
        Detect if(false){...} and while(false){...} blocks.
        Everything inside is dead code.
        """
        in_dead = False
        dead_depth = 0
        brace_depth = 0

        for lineno, line in enumerate(self.clean_lines, 1):
            stripped = line.strip()
            if not stripped:
                brace_depth += stripped.count('{') - stripped.count('}')
                brace_depth = max(0, brace_depth)
                continue

            if not in_dead:
                if _DEAD_COND_PATTERN.match(line):
                    in_dead = True
                    dead_depth = brace_depth
                    self._mark_dead(lineno, 'dead_branch',
                                    'Condition is always falsy — branch never executes')
            else:
                # Inside a dead branch — mark this line
                self._mark_dead(lineno, 'dead_branch',
                                'Inside an always-false branch')

            net = stripped.count('{') - stripped.count('}')
            brace_depth = max(0, brace_depth + net)

            # Exit dead branch when we return to the starting depth
            if in_dead and brace_depth <= dead_depth:
                in_dead = False

    # ── Pass 4: unused variables and functions ────────────────────────────────

    def _pass4_compute_unused(self):
        n = len(self.original_lines)

        # Unused variables
        for name, info in self._declarations.items():
            if name not in self._references:
                lineno = info['line']
                if lineno > n:
                    continue
                orig = self.original_lines[lineno - 1]
                self.findings.append({
                    'line':     lineno,
                    'kind':     'unused_var',
                    'name':     name,
                    'text':     orig.strip(),
                    'severity': 'dead',
                    'message':  f"'{name}' ({info['decl_kind']}) declared but never read",
                })
                self._mark_dead(lineno, 'unused_var',
                                f"'{name}' is never read after declaration")

        # Unused functions
        for name, info in self._fn_decls.items():
            # Treat as used if the name appears in refs OR call_sites
            if name not in self._references and name not in self._call_sites:
                lineno = info['line']
                if lineno > n:
                    continue
                orig = self.original_lines[lineno - 1]
                self.findings.append({
                    'line':     lineno,
                    'kind':     'unused_fn',
                    'name':     name,
                    'text':     orig.strip(),
                    'severity': 'dead',
                    'message':  f"Function '{name}' is declared but never called",
                })
                self._mark_dead(lineno, 'unused_fn',
                                f"Function '{name}' is never called")

        # Add findings for unreachable / dead-branch lines (from passes 2 & 3)
        for lineno in range(1, n + 1):
            kind = self.line_kind[lineno]
            if kind in ('unreachable', 'dead_branch'):
                orig = self.original_lines[lineno - 1]
                if orig.strip():
                    self.findings.append({
                        'line':     lineno,
                        'kind':     kind,
                        'name':     None,
                        'text':     orig.strip(),
                        'severity': 'dead',
                        'message':  self.line_reason[lineno],
                    })

    # ── helpers ───────────────────────────────────────────────────────────────

    def _mark_dead(self, lineno: int, kind: str, reason: str):
        """Mark a line dead only if it hasn't already been marked."""
        if not self.line_dead[lineno]:
            self.line_dead[lineno] = True
            self.line_kind[lineno] = kind
            self.line_reason[lineno] = reason

    # ── clean code builder ────────────────────────────────────────────────────

    def _build_cleaned_code(self) -> str:
        """Return source with dead lines removed."""
        n = len(self.original_lines)
        kept = []
        for lineno, line in enumerate(self.original_lines, 1):
            if lineno <= n and self.line_dead[lineno]:
                continue
            kept.append(line)
        # Collapse multiple consecutive blank lines to at most one
        result = []
        prev_blank = False
        for ln in kept:
            is_blank = not ln.strip()
            if is_blank and prev_blank:
                continue
            result.append(ln)
            prev_blank = is_blank
        return '\n'.join(result).strip()

    # ── serialise ─────────────────────────────────────────────────────────────

    def _build_result(self) -> dict:
        n = len(self.original_lines)

        lines_data = []
        for lineno, orig in enumerate(self.original_lines, 1):
            dead   = self.line_dead[lineno]   if lineno <= n else False
            kind   = self.line_kind[lineno]   if lineno <= n else None
            reason = self.line_reason[lineno] if lineno <= n else ''
            lines_data.append({
                'line':   lineno,
                'text':   orig,
                'dead':   dead,
                'kind':   kind or '',
                'reason': reason,
            })

        dead_nonempty = [l for l in lines_data if l['dead'] and l['text'].strip()]

        unused_vars   = sum(1 for f in self.findings if f['kind'] == 'unused_var')
        unused_fns    = sum(1 for f in self.findings if f['kind'] == 'unused_fn')
        unreachable   = sum(1 for f in self.findings if f['kind'] == 'unreachable')
        dead_branches = sum(1 for f in self.findings if f['kind'] == 'dead_branch')

        return {
            'lines':        lines_data,
            'findings':     self.findings,
            'cleaned_code': self._build_cleaned_code(),
            'stats': {
                'total_lines':      n,
                'dead_line_count':  len(dead_nonempty),
                'unused_vars':      unused_vars,
                'unused_functions': unused_fns,
                'unreachable':      unreachable,
                'dead_branches':    dead_branches,
                'pct_eliminated':   round(len(dead_nonempty) / n * 100, 1) if n else 0,
            },
        }


# ─────────────────────────────────────────────────────────────────────────────
# 4.  PUBLIC API
# ─────────────────────────────────────────────────────────────────────────────

def run_js_analysis(source: str) -> dict:
    """
    Analyze JavaScript source for dead code.
    Returns a JSON-serializable dict.
    """
    try:
        src = source.strip()
        if not src:
            return {'error': 'Empty source code.'}
        analyzer = JSScopeAnalyzer(src)
        return analyzer.analyze()
    except Exception as exc:
        import traceback
        return {'error': f'Analysis error: {exc}',
                'traceback': traceback.format_exc()}


# ─────────────────────────────────────────────────────────────────────────────
# 5.  CLI  (python js_analyzer.py)
# ─────────────────────────────────────────────────────────────────────────────

_CLI_DEMOS = {
    "Unused Variables": """\
// Demo 1 — Unused Variables
function greet(name) {
    let greeting = "Hello, " + name;
    let unusedMsg = "This message is never used";
    const prefix = "Mr.";
    console.log(greeting);
}
greet("World");
""",

    "Dead Function": """\
// Demo 2 — Unused Function
function add(a, b) {
    return a + b;
}

function multiply(a, b) {
    return a * b;
}

// Only add() is called; multiply() is dead
const result = add(3, 4);
console.log(result);
""",

    "Unreachable Code": """\
// Demo 3 — Unreachable Code
function calculate(x, y) {
    const result = x + y;
    return result;
    console.log("This is unreachable");
    let extra = x * 2;
    return extra;
}
console.log(calculate(3, 4));
""",

    "Dead Branch": """\
// Demo 4 — Dead Branch
const DEBUG = false;

if (false) {
    console.log("This block never runs");
    let debugValue = 42;
}

while (0) {
    console.log("Also dead");
}

console.log("Only this runs");
""",
}


if __name__ == '__main__':
    for name, src in _CLI_DEMOS.items():
        print(f"\n{'═' * 65}")
        print(f"  JS DCE: {name}")
        print(f"{'═' * 65}")
        result = run_js_analysis(src)
        if 'error' in result:
            print(f"  ERROR: {result['error']}")
            continue
        print(f"\n  Findings ({len(result['findings'])}):")
        for f in result['findings']:
            tag = f['kind'].ljust(12)
            name_part = f" [{f['name']}]" if f['name'] else ''
            print(f"  Line {f['line']:3d}  [{tag}]{name_part}  {f['message']}")
        s = result['stats']
        print(f"\n  Total lines: {s['total_lines']}  |  "
              f"Dead: {s['dead_line_count']}  ({s['pct_eliminated']}%)  |  "
              f"Unused vars: {s['unused_vars']}  "
              f"Unused fns: {s['unused_functions']}  "
              f"Unreachable: {s['unreachable']}  "
              f"Dead branches: {s['dead_branches']}")
