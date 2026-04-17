"""
Dead Code Elimination (DCE) via Liveness Analysis on Three-Address Code (TAC)
=============================================================================
This module:
  1. Defines a simple Three-Address Code (TAC) instruction set
  2. Parses a mini-language into TAC
  3. Runs backward liveness analysis
  4. Eliminates dead assignments (variables assigned but never used)
  5. Returns structured JSON output for web visualization
"""

from dataclasses import dataclass, field
from typing import Optional
import re
import json


# ──────────────────────────────────────────────
# 1.  TAC INSTRUCTION MODEL
# ──────────────────────────────────────────────

@dataclass
class Instruction:
    """
    A single three-address instruction.

    Forms supported
    ---------------
    Assignment  : result = op1 op op2   (op2 optional for unary)
    Copy        : result = op1
    Goto        : GOTO label
    IfGoto      : IF op1 op op2 GOTO label
    Label       : LABEL name
    Return      : RETURN op1
    Print       : PRINT op1
    """
    kind: str          # 'assign' | 'copy' | 'goto' | 'ifgoto' | 'label' | 'return' | 'print'
    result: Optional[str] = None
    op1: Optional[str] = None
    operator: Optional[str] = None
    op2: Optional[str] = None
    label: Optional[str] = None
    dead: bool = False  # marked True by DCE pass

    def uses(self) -> set:
        """Variables READ by this instruction (potential rhs operands)."""
        used = set()
        for operand in (self.op1, self.op2):
            if operand and not _is_const(operand):
                used.add(operand)
        return used

    def defines(self) -> Optional[str]:
        """Variable WRITTEN by this instruction (lhs), if any."""
        if self.kind in ('assign', 'copy') and self.result:
            return self.result
        return None

    def __str__(self) -> str:
        if self.kind == 'label':
            return f"{self.label}:"
        if self.kind == 'goto':
            return f"GOTO {self.label}"
        if self.kind == 'ifgoto':
            return f"IF {self.op1} {self.operator} {self.op2} GOTO {self.label}"
        if self.kind == 'return':
            return f"RETURN {self.op1}"
        if self.kind == 'print':
            return f"PRINT {self.op1}"
        if self.kind == 'copy':
            return f"{self.result} = {self.op1}"
        if self.kind == 'assign':
            if self.op2:
                return f"{self.result} = {self.op1} {self.operator} {self.op2}"
            return f"{self.result} = {self.operator}{self.op1}"
        return f"<unknown {self.kind}>"

    def to_dict(self, index: int, live_in: set, live_out: set) -> dict:
        """Serialize to JSON-friendly dict for the web UI."""
        defined = self.defines()
        return {
            "index": index,
            "kind": self.kind,
            "text": str(self),
            "dead": self.dead,
            "defines": defined,
            "uses": list(self.uses()),
            "live_in": sorted(list(live_in)),
            "live_out": sorted(list(live_out)),
            "is_control_flow": self.kind in ('goto', 'ifgoto', 'label'),
        }


def _is_const(token: str) -> bool:
    """True if token is a numeric literal."""
    try:
        float(token)
        return True
    except ValueError:
        return False


# ──────────────────────────────────────────────
# 2.  MINI-LANGUAGE PARSER  →  TAC
# ──────────────────────────────────────────────

class TACParser:
    """
    Parses a tiny imperative language into TAC.

    Grammar (simplified)
    --------------------
    program  := stmt*
    stmt     := assign | if | while | print | return
    assign   := IDENT '=' expr ';'
    if       := 'if' '(' cond ')' '{' stmt* '}'
    while    := 'while' '(' cond ')' '{' stmt* '}'
    print    := 'print' '(' expr ')' ';'
    return   := 'return' expr ';'
    expr     := term (('+' | '-') term)*
    term     := factor (('*' | '/') factor)*
    factor   := NUMBER | IDENT | '(' expr ')'
    cond     := expr ('==' | '!=' | '<' | '<=' | '>' | '>=') expr
    """

    def __init__(self, source: str):
        self.tokens = self._tokenise(source)
        self.pos = 0
        self.instructions: list = []
        self._tmp_counter = 0
        self._label_counter = 0

    # ── tokeniser ──────────────────────────────

    _TOKEN_RE = re.compile(
        r'\s*(?:'
        r'(//[^\n]*)'               # line comment
        r'|(\d+(?:\.\d+)?)'        # number
        r'|([a-zA-Z_]\w*)'         # identifier / keyword
        r'|(<=|>=|==|!=|&&|\|\|)'  # multi-char operators
        r'|([+\-*/(){};=<>!,])'    # single-char symbols
        r')\s*'
    )

    def _tokenise(self, src: str) -> list:
        tokens = []
        for m in self._TOKEN_RE.finditer(src):
            comment, num, ident, multi, single = m.groups()
            if comment:
                continue
            tokens.append(num or ident or multi or single)
        return tokens

    # ── helpers ────────────────────────────────

    def _peek(self) -> Optional[str]:
        return self.tokens[self.pos] if self.pos < len(self.tokens) else None

    def _consume(self, expected: Optional[str] = None) -> str:
        tok = self.tokens[self.pos]
        if expected and tok != expected:
            raise SyntaxError(f"Expected {expected!r} but got {tok!r} at position {self.pos}")
        self.pos += 1
        return tok

    def _new_tmp(self) -> str:
        self._tmp_counter += 1
        return f"_t{self._tmp_counter}"

    def _new_label(self, prefix='L') -> str:
        self._label_counter += 1
        return f"{prefix}{self._label_counter}"

    def _emit(self, instr: Instruction):
        self.instructions.append(instr)

    # ── parser ─────────────────────────────────

    def parse(self) -> list:
        while self._peek():
            self._parse_stmt()
        return self.instructions

    def _parse_stmt(self):
        tok = self._peek()
        if tok == 'if':
            self._parse_if()
        elif tok == 'while':
            self._parse_while()
        elif tok == 'print':
            self._parse_print()
        elif tok == 'return':
            self._parse_return()
        elif tok and re.match(r'[a-zA-Z_]\w*', tok):
            self._parse_assign()
        else:
            raise SyntaxError(f"Unexpected token: {tok!r}")

    def _parse_assign(self):
        ident = self._consume()
        self._consume('=')
        result = self._parse_expr()
        self._consume(';')
        if result != ident:
            self._emit(Instruction('copy', result=ident, op1=result))

    def _parse_if(self):
        self._consume('if')
        self._consume('(')
        _, op, lhs, rhs = self._parse_cond()
        self._consume(')')
        self._consume('{')
        false_label = self._new_label('IF_FALSE')
        end_label = self._new_label('IF_END')
        neg_op = {'==': '!=', '!=': '==', '<': '>=', '<=': '>', '>': '<=', '>=': '<'}[op]
        self._emit(Instruction('ifgoto', op1=lhs, operator=neg_op, op2=rhs, label=false_label))
        while self._peek() != '}':
            self._parse_stmt()
        self._consume('}')
        self._emit(Instruction('goto', label=end_label))
        self._emit(Instruction('label', label=false_label))
        self._emit(Instruction('label', label=end_label))

    def _parse_while(self):
        self._consume('while')
        self._consume('(')
        _, op, lhs, rhs = self._parse_cond()
        self._consume(')')
        self._consume('{')
        loop_label = self._new_label('WHILE_START')
        end_label = self._new_label('WHILE_END')
        self._emit(Instruction('label', label=loop_label))
        neg_op = {'==': '!=', '!=': '==', '<': '>=', '<=': '>', '>': '<=', '>=': '<'}[op]
        self._emit(Instruction('ifgoto', op1=lhs, operator=neg_op, op2=rhs, label=end_label))
        while self._peek() != '}':
            self._parse_stmt()
        self._consume('}')
        self._emit(Instruction('goto', label=loop_label))
        self._emit(Instruction('label', label=end_label))

    def _parse_print(self):
        self._consume('print')
        self._consume('(')
        val = self._parse_expr()
        self._consume(')')
        self._consume(';')
        self._emit(Instruction('print', op1=val))

    def _parse_return(self):
        self._consume('return')
        val = self._parse_expr()
        self._consume(';')
        self._emit(Instruction('return', op1=val))

    def _parse_cond(self):
        lhs = self._parse_expr()
        op = self._consume()
        rhs = self._parse_expr()
        return None, op, lhs, rhs

    def _parse_expr(self) -> str:
        left = self._parse_term()
        while self._peek() in ('+', '-'):
            op = self._consume()
            right = self._parse_term()
            tmp = self._new_tmp()
            self._emit(Instruction('assign', result=tmp, op1=left, operator=op, op2=right))
            left = tmp
        return left

    def _parse_term(self) -> str:
        left = self._parse_factor()
        while self._peek() in ('*', '/'):
            op = self._consume()
            right = self._parse_factor()
            tmp = self._new_tmp()
            self._emit(Instruction('assign', result=tmp, op1=left, operator=op, op2=right))
            left = tmp
        return left

    def _parse_factor(self) -> str:
        tok = self._peek()
        if tok == '(':
            self._consume('(')
            val = self._parse_expr()
            self._consume(')')
            return val
        self._consume()
        return tok


# ──────────────────────────────────────────────
# 3.  LIVENESS ANALYSIS  +  DCE
# ──────────────────────────────────────────────

class DeadCodeEliminator:
    """
    Backward liveness analysis + dead assignment elimination.

    live_out[i]  = variables live AFTER instruction i
    live_in[i]   = (live_out[i] - def(i)) ∪ use(i)

    An assignment  x = ...  is DEAD if x ∉ live_out[i].
    """

    def __init__(self, instructions: list):
        self.instructions = instructions
        self.live_in: list = []
        self.live_out: list = []

    def analyse_and_eliminate(self):
        instrs = self.instructions
        n = len(instrs)
        live = [set() for _ in range(n + 1)]

        # Two backward passes (handles simple back-edges from while loops)
        for _ in range(2):
            for i in range(n - 1, -1, -1):
                instr = instrs[i]
                live_in_i = live[i + 1].copy()
                defined = instr.defines()
                if defined:
                    live_in_i.discard(defined)
                live_in_i |= instr.uses()
                live[i] = live_in_i

        # Store per-instruction live sets
        self.live_in = [live[i] for i in range(n)]
        self.live_out = [live[i + 1] for i in range(n)]

        # Mark dead
        eliminated = 0
        for i, instr in enumerate(instrs):
            defined = instr.defines()
            if defined and defined not in self.live_out[i]:
                instr.dead = True
                eliminated += 1

        return instrs, eliminated

    def get_live_program(self) -> list:
        return [instr for instr in self.instructions if not instr.dead]

    def to_json(self) -> dict:
        instrs = self.instructions
        n = len(instrs)
        result_instrs = []
        for i, instr in enumerate(instrs):
            lin = self.live_in[i] if i < len(self.live_in) else set()
            lout = self.live_out[i] if i < len(self.live_out) else set()
            result_instrs.append(instr.to_dict(i, lin, lout))

        dead_count = sum(1 for instr in instrs if instr.dead)
        total = len(instrs)
        live_count = total - dead_count

        return {
            "instructions": result_instrs,
            "stats": {
                "total_before": total,
                "total_after": live_count,
                "dead_count": dead_count,
                "pct_eliminated": round(dead_count / total * 100, 1) if total else 0,
            }
        }


# ──────────────────────────────────────────────
# 4.  OPTIMIZATION PASSES
# ──────────────────────────────────────────────

import operator as _op

_ARITH = {
    '+': _op.add,
    '-': _op.sub,
    '*': _op.mul,
    '/': _op.truediv,
}

def _try_eval(op1, operator, op2):
    """Return (True, result_str) if both operands are numeric constants."""
    if _is_const(op1) and _is_const(op2) and operator in _ARITH:
        try:
            val = _ARITH[operator](float(op1), float(op2))
            # Keep as int if whole number
            return True, str(int(val)) if val == int(val) else str(round(val, 8))
        except ZeroDivisionError:
            return False, None
    return False, None


class ConstantFolder:
    """
    Constant Folding: replace  x = 3 + 5  with  x = 8.
    Works on 'assign' instructions where both operands are numeric literals.
    """

    def run(self, instructions: list) -> list:
        changes = []
        for instr in instructions:
            original = str(instr)
            if instr.kind == 'assign' and instr.op1 and instr.op2 and instr.operator:
                ok, val = _try_eval(instr.op1, instr.operator, instr.op2)
                if ok:
                    instr.kind = 'copy'
                    instr.op1 = val
                    instr.operator = None
                    instr.op2 = None
                    changes.append({'before': original, 'after': str(instr), 'changed': True})
                    continue
            changes.append({'before': original, 'after': str(instr), 'changed': False})
        return changes


class ConstantPropagator:
    """
    Constant Propagation: track variables that hold a known constant value and
    substitute them at use-sites.  e.g.  x=3; y=x+2  →  y=3+2.
    """

    def run(self, instructions: list) -> list:
        const_map: dict = {}   # var -> constant string
        changes = []
        for instr in instructions:
            original = str(instr)
            changed = False

            # Substitute known constants into operands
            if instr.op1 and not _is_const(instr.op1) and instr.op1 in const_map:
                instr.op1 = const_map[instr.op1]
                changed = True
            if instr.op2 and not _is_const(instr.op2) and instr.op2 in const_map:
                instr.op2 = const_map[instr.op2]
                changed = True

            # After substitution, fold if possible
            if instr.kind == 'assign' and instr.op1 and instr.op2 and instr.operator:
                ok, val = _try_eval(instr.op1, instr.operator, instr.op2)
                if ok:
                    instr.kind = 'copy'
                    instr.op1 = val
                    instr.operator = None
                    instr.op2 = None
                    changed = True

            # Record if this instruction defines a constant
            if instr.kind == 'copy' and instr.result and _is_const(instr.op1):
                const_map[instr.result] = instr.op1
            elif instr.defines():
                # Non-constant assignment — invalidate
                const_map.pop(instr.defines(), None)

            changes.append({'before': original, 'after': str(instr), 'changed': changed})
        return changes


class CSEliminator:
    """
    Common Subexpression Elimination: if the same expression  a op b  was
    already computed into some variable, reuse that variable instead of
    recomputing it.
    """

    def run(self, instructions: list) -> list:
        # expr_map: (op1, operator, op2) -> result_var
        expr_map: dict = {}
        # which variables have been invalidated (reassigned)
        changes = []
        for instr in instructions:
            original = str(instr)
            changed = False

            if instr.kind == 'assign' and instr.op1 and instr.op2 and instr.operator:
                key = (instr.op1, instr.operator, instr.op2)
                if key in expr_map:
                    # Replace with copy from previously computed variable
                    prev_var = expr_map[key]
                    instr.kind = 'copy'
                    instr.op1 = prev_var
                    instr.operator = None
                    instr.op2 = None
                    changed = True
                else:
                    expr_map[key] = instr.result

            # Invalidate expressions that use a reassigned variable
            if instr.defines():
                stale = [k for k in expr_map if instr.defines() in k]
                for k in stale:
                    del expr_map[k]

            changes.append({'before': original, 'after': str(instr), 'changed': changed})
        return changes


class AlgebraicSimplifier:
    """
    Algebraic Simplification: apply identities such as
      x + 0  →  x
      x * 1  →  x
      x * 0  →  0
      x - 0  →  x
      x / 1  →  x
      x - x  →  0
      x * x  stays (no simplification)
    """

    IDENTITIES = [
        # (op, position_of_zero/one, neutral_val_or_action)
        # Each rule: (operator, check_fn(op1,op2)) -> result_str or None
    ]

    def _simplify(self, op1, operator, op2):
        """Return simplified op1 string, or None if no simplification."""
        if operator == '+':
            if op2 == '0': return op1
            if op1 == '0': return op2
        if operator == '-':
            if op2 == '0': return op1
            if op1 == op2 and not _is_const(op1): return '0'
        if operator == '*':
            if op2 == '1': return op1
            if op1 == '1': return op2
            if op2 == '0' or op1 == '0': return '0'
        if operator == '/':
            if op2 == '1': return op1
            if op1 == '0': return '0'
        return None

    def run(self, instructions: list) -> list:
        changes = []
        for instr in instructions:
            original = str(instr)
            changed = False

            if instr.kind == 'assign' and instr.op1 and instr.op2 and instr.operator:
                simplified = self._simplify(instr.op1, instr.operator, instr.op2)
                if simplified is not None:
                    instr.kind = 'copy'
                    instr.op1 = simplified
                    instr.operator = None
                    instr.op2 = None
                    changed = True

            changes.append({'before': original, 'after': str(instr), 'changed': changed})
        return changes


def run_optimization(source: str, pass_name: str) -> dict:
    """
    Run a named optimization pass on source code.
    pass_name: 'cf' | 'cp' | 'cse' | 'alg'
    Returns JSON-serializable result with before/after lines.
    """
    import copy as _copy

    PASSES = {
        'cf':  ConstantFolder,
        'cp':  ConstantPropagator,
        'cse': CSEliminator,
        'alg': AlgebraicSimplifier,
    }

    if pass_name not in PASSES:
        return {'error': f'Unknown pass: {pass_name}'}

    try:
        source = source.strip()
        if not source:
            return {'error': 'Empty source code.'}

        parser = TACParser(source)
        instructions = parser.parse()

        # Deep-copy so we preserve the original text
        original_texts = [str(i) for i in instructions]
        instrs_copy = _copy.deepcopy(instructions)

        optimizer = PASSES[pass_name]()
        changes = optimizer.run(instrs_copy)

        n_changed = sum(1 for c in changes if c['changed'])
        total = len(changes)

        return {
            'lines': changes,
            'stats': {
                'total': total,
                'changed': n_changed,
                'unchanged': total - n_changed,
                'pct_changed': round(n_changed / total * 100, 1) if total else 0,
            }
        }

    except SyntaxError as e:
        return {'error': f'Syntax error: {e}'}
    except Exception as e:
        return {'error': f'Internal error: {e}'}


# ──────────────────────────────────────────────
# 5.  PUBLIC API
# ──────────────────────────────────────────────

def run_dce(source: str) -> dict:
    """
    Parse source, run DCE, and return a JSON-serializable result dict.
    Returns {'error': str} on parse failure.
    """
    try:
        source = source.strip()
        if not source:
            return {"error": "Empty source code."}

        parser = TACParser(source)
        instructions = parser.parse()

        dce = DeadCodeEliminator(instructions)
        dce.analyse_and_eliminate()

        return dce.to_json()

    except SyntaxError as e:
        return {"error": f"Syntax error: {e}"}
    except Exception as e:
        return {"error": f"Internal error: {e}"}


def run_all_passes(source: str) -> dict:
    """
    Run the full optimization pipeline:
      1. Constant Folding
      2. Constant Propagation
      3. Algebraic Simplification
      4. Common Subexpression Elimination
      5. Dead Code Elimination

    Returns a JSON-serializable dict with:
      - original_lines  : TAC before any optimization
      - passes          : per-pass summary + diff
      - final_lines     : TAC after all passes (only live instructions)
      - stats           : overall reduction numbers
    """
    import copy as _copy

    try:
        source = source.strip()
        if not source:
            return {"error": "Empty source code."}

        # ── Parse once ────────────────────────────────────
        parser = TACParser(source)
        base_instrs = parser.parse()
        original_lines = [str(i) for i in base_instrs]

        # ── Pipeline ──────────────────────────────────────
        pipeline = [
            ("Constant Folding",                   "cf",  ConstantFolder),
            ("Constant Propagation",               "cp",  ConstantPropagator),
            ("Algebraic Simplification",           "alg", AlgebraicSimplifier),
            ("Common Subexpression Elimination",   "cse", CSEliminator),
        ]

        working = _copy.deepcopy(base_instrs)
        passes_summary = []

        for pass_name, pass_id, PassClass in pipeline:
            snapshot_before = [str(i) for i in working]
            instrs_copy = _copy.deepcopy(working)
            changes = PassClass().run(instrs_copy)

            n_changed = sum(1 for c in changes if c['changed'])
            passes_summary.append({
                "name": pass_name,
                "id":   pass_id,
                "total": len(changes),
                "changed": n_changed,
                "lines": changes,
            })

            # Use the mutated copies as the input to the next pass
            working = instrs_copy

        # ── DCE on the fully-optimised TAC ────────────────
        dce = DeadCodeEliminator(working)
        dce.analyse_and_eliminate()

        # Final live lines only
        final_lines = [str(i) for i in working if not i.dead]

        # All lines with dead flag for side-by-side view
        final_all = []
        for instr in working:
            final_all.append({
                "text": str(instr),
                "dead": instr.dead,
                "is_control_flow": instr.kind in ('goto', 'ifgoto', 'label'),
                "kind": instr.kind,
            })

        dead_count  = sum(1 for i in working if i.dead)
        total_orig  = len(original_lines)
        total_final = len(final_lines)
        removed     = total_orig - total_final

        return {
            "original_lines": original_lines,
            "passes": passes_summary,
            "final_all": final_all,
            "final_lines": final_lines,
            "stats": {
                "original_count":  total_orig,
                "final_count":     total_final,
                "removed":         removed,
                "pct_reduced":     round(removed / total_orig * 100, 1) if total_orig else 0,
                "total_optimized": sum(p["changed"] for p in passes_summary),
                "dce_eliminated":  dead_count,
            }
        }

    except SyntaxError as e:
        return {"error": f"Syntax error: {e}"}
    except Exception as e:
        return {"error": f"Internal error: {e}"}


# ──────────────────────────────────────────────
# 5.  CLI  (python dce_engine.py)
# ──────────────────────────────────────────────

DEMO1 = """
// Dead variables: b, unused_sum are never printed/returned
a = 10;
b = 20;
c = a + 5;
unused_sum = c + b;
print(c);
"""

DEMO2 = """
// Only 'result' is live at the end
x = 3;
y = 4;
temp = x * x;
result = temp + y * y;
print(result);
x = 99;
"""

DEMO3 = """
// Loop with dead scratch variable
i = 0;
total = 0;
discarded = 1000;
while (i < 5) {
    total = total + i;
    i = i + 1;
    scratch = i * 2;
}
print(total);
"""


def _cli_print(source: str, name: str):
    print(f"\n{'═'*60}")
    print(f"  DCE: {name}")
    print(f"{'═'*60}")
    result = run_dce(source)
    if "error" in result:
        print(f"  ERROR: {result['error']}")
        return
    print(f"\n{'─'*60}  TAC (before DCE)")
    for instr in result["instructions"]:
        dead_tag = "  [DEAD]" if instr["dead"] else "        "
        print(f"  {instr['index']:>3}  {dead_tag}  {instr['text']}")
    s = result["stats"]
    print(f"\n  Before: {s['total_before']}  After: {s['total_after']}  "
          f"Eliminated: {s['dead_count']} ({s['pct_eliminated']}%)")


if __name__ == '__main__':
    _cli_print(DEMO1, "Dead variables")
    _cli_print(DEMO2, "Pythagorean sum")
    _cli_print(DEMO3, "Loop with dead scratch")
