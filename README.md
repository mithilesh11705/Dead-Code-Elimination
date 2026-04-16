# 🧹 Dead Code Eliminator — DCE Visualizer

An interactive web-based tool that demonstrates **Dead Code Elimination (DCE)** via **Backward Liveness Analysis** on **Three-Address Code (TAC)**.

Write mini-language source code → watch it get parsed into TAC → see dead assignments highlighted in real time → view the clean optimized output.

---

## 📸 Preview

| TAC View | Clean Output |
|----------|--------------|
| Dead instructions struck-through in red, live in green | Only surviving instructions, numbered |

---

## 🚀 Getting Started

### Prerequisites

- Python 3.8+
- pip

### Install & Run

```bash
# 1. Clone / navigate to the project folder
cd dead-code

# 2. Install dependencies
pip install flask flask-cors

# 3. Start the server
python server.py

# 4. Open in your browser
#    http://localhost:5000
```

> Press **Ctrl+C** in the terminal to stop the server.

---

## 📁 Project Structure

```
dead-code/
├── dce_engine.py   # Core DCE library (TAC model, parser, liveness analysis)
├── server.py       # Flask dev server — serves UI + /api/dce endpoint
├── index.html      # Interactive single-page visualizer
└── README.md       # This file
```

---

## 🧠 How It Works

### Pipeline

```
Source Code  →  TACParser  →  TAC Instructions  →  DeadCodeEliminator  →  Annotated JSON
                                                         ↓
                                               Backward Liveness Analysis
                                               (2-pass over flat IR)
```

### 1. TAC Instruction Model (`Instruction`)

Each instruction tracks:
- `defines()` — the variable it **writes** (LHS)
- `uses()` — the variables it **reads** (RHS operands)

Supported instruction kinds:

| Kind | Example TAC |
|------|-------------|
| `assign` | `_t1 = a + 5` |
| `copy` | `x = _t1` |
| `ifgoto` | `IF i >= 5 GOTO WHILE_END2` |
| `goto` | `GOTO WHILE_START1` |
| `label` | `WHILE_START1:` |
| `return` | `RETURN x` |
| `print` | `PRINT c` |

### 2. Mini-Language Parser (`TACParser`)

Recursive-descent parser that compiles a tiny imperative language into flat TAC, auto-generating temporaries (`_t1`, `_t2`, …) and labels (`WHILE_START1`, `IF_FALSE2`, …).

**Supported grammar:**
```
stmt     := assign | if | while | print | return
assign   := IDENT '=' expr ';'
if       := 'if' '(' cond ')' '{' stmt* '}'
while    := 'while' '(' cond ')' '{' stmt* '}'
print    := 'print' '(' expr ')' ';'
return   := 'return' expr ';'
expr     := term (('+' | '-') term)*
term     := factor (('*' | '/') factor)*
cond     := expr ('==' | '!=' | '<' | '<=' | '>' | '>=') expr
```

### 3. Liveness Analysis + DCE (`DeadCodeEliminator`)

Runs **two backward passes** over the instruction list:

```
live_out[i]  =  live[i+1]               (variables alive after instruction i)
live_in[i]   =  (live_out[i] - def(i))  ∪  use(i)
```

An assignment `x = ...` is **DEAD** if `x ∉ live_out[i]` — nobody reads `x` before it is overwritten or the program ends.

Two passes handle simple back-edges from `while` loops.

---

## 🖥️ Web UI

The visualizer has **4 tabs**:

| Tab | Description |
|-----|-------------|
| 📋 **TAC View** | All instructions color-coded. 🟢 LIVE / 🔴 DEAD. Click any row to inspect its `live_in`, `live_out`, `defines`, `uses`. |
| ✅ **Clean Output** | The optimized program after dead code is removed. |
| 📊 **Liveness Table** | Full per-instruction liveness data in a table. |
| 🗂️ **Block View** | Instructions grouped into basic blocks. |

**Stats bar** (top right) shows:
- Total instructions before DCE
- Live instructions kept
- Dead assignments eliminated
- Percentage reduction

---

## ✏️ Writing Your Own Programs

Use the **Source Editor** on the left panel. Press **Ctrl+Enter** or click **Run DCE Analysis**.

```js
// Line comments supported
a = 10;
b = 20;           // will be marked DEAD if b is never read
c = a + 5;
print(c);
```

```js
// if-else
if (x > 0) {
    result = x * 2;
}
print(result);
```

```js
// while loop
i = 0;
while (i < 10) {
    i = i + 1;
    dead = i * 99;   // dead: overwritten next iteration, never read
}
print(i);
```

---

## 📦 API

The server exposes a single endpoint:

### `POST /api/dce`

**Request body:**
```json
{ "source": "x = 10;\ny = x + 5;\nprint(y);" }
```

**Response:**
```json
{
  "instructions": [
    {
      "index": 0,
      "kind": "copy",
      "text": "x = 10",
      "dead": false,
      "defines": "x",
      "uses": [],
      "live_in": ["x"],
      "live_out": ["x"]
    },
    ...
  ],
  "stats": {
    "total_before": 5,
    "total_after": 4,
    "dead_count": 1,
    "pct_eliminated": 20.0
  }
}
```

**Error response:**
```json
{ "error": "Syntax error: Expected ';' but got '}' at position 12" }
```

---

## 🎓 Demo Programs

Four built-in demos bundled in the UI:

| # | Name | What it shows |
|---|------|---------------|
| 1 | **Dead Variables** | `b` and `unused_sum` assigned but never read → eliminated |
| 2 | **Pythagorean Sum** | `x = 99` after the last use of `x` → dead re-assignment |
| 3 | **Loop + Scratch** | `scratch` and `discarded` dead every iteration → eliminated |
| 4 | **Branching Code** | Dead assignments inside an `if` body |

---

## 🔧 Tech Stack

| Layer | Technology |
|-------|------------|
| Backend | Python 3 · Flask · flask-cors |
| Frontend | Vanilla HTML/CSS/JS (zero dependencies) |
| Fonts | Inter · JetBrains Mono (Google Fonts) |
| Analysis | Custom backward liveness algorithm |

---

## 📚 Further Reading

- [Liveness Analysis — Wikipedia](https://en.wikipedia.org/wiki/Live-variable_analysis)
- [Three-Address Code — Dragon Book (Aho et al.)](https://en.wikipedia.org/wiki/Three-address_code)
- [LLVM Dead Code Elimination Pass](https://llvm.org/docs/Passes.html#dce-dead-code-elimination)

---

## 📄 License

MIT — free to use, modify, and distribute.
