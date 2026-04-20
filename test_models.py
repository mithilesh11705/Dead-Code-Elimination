# =============================================================================
#  Gemini Model Tester  -  test_models.py
# =============================================================================
#  Tests every known Gemini model against your GEMINI_API_KEY and reports:
#    OK      - model responded successfully
#    BLOCKED - API key lacks access / model requires allowlist
#    NOFOUND - model name does not exist
#    QUOTA   - rate-limit / quota hit (key works, just throttled)
#    BADKEY  - invalid API key
#    ERROR   - other API error
#
#  Also includes a MANUAL CODE SECTION at the bottom where you can paste
#  any mini-language source and run it through the full DCE + LLM pipeline.
# =============================================================================
#  Usage:
#      python test_models.py
# =============================================================================

import os
import sys

# ── Load .env ----------------------------------------------------------------
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

try:
    from google import genai
    from google.genai import types as genai_types
    NEW_SDK = True
except ImportError:
    try:
        import google.generativeai as genai_legacy
        NEW_SDK = False
    except ImportError:
        print("\nERROR: google-genai (or google-generativeai) not installed.")
        print("  Run:  pip install google-genai\n")
        sys.exit(1)

# =============================================================================
#  CONFIG
# =============================================================================

API_KEY = os.environ.get("GEMINI_API_KEY", "").strip()

# All known Gemini text-capable models (as of mid-2025)
ALL_MODELS = [
    # Gemma (Default)
    "gemma-3-27b-it",
    # Gemini 2.5
    "gemini-2.5-pro-preview-05-06",
    "gemini-2.5-pro-exp-03-25",
    "gemini-2.5-flash-preview-04-17",
    # Gemini 2.0
    "gemini-2.0-flash",
    "gemini-2.0-flash-001",
    "gemini-2.0-flash-exp",
    "gemini-2.0-flash-lite",
    "gemini-2.0-flash-lite-001",
    "gemini-2.0-flash-thinking-exp-01-21",
    "gemini-2.0-pro-exp-02-05",
    # Gemini 1.5
    "gemini-1.5-pro",
    "gemini-1.5-pro-001",
    "gemini-1.5-pro-002",
    "gemini-1.5-flash",
    "gemini-1.5-flash-001",
    "gemini-1.5-flash-002",
    "gemini-1.5-flash-8b",
    "gemini-1.5-flash-8b-001",
    # Gemini 1.0
    "gemini-1.0-pro",
    "gemini-1.0-pro-001",
    "gemini-1.0-pro-002",
    "gemini-pro",
    # Gemma
    "gemma-3-12b-it",
    "gemma-3-4b-it",
    "gemma-3-1b-it",
]

# Super-short prompt - just checking connectivity
TEST_PROMPT = "Reply with exactly one word: OK"

# =============================================================================
#  MANUAL CODE  -  Edit the string below to test your own source code
# =============================================================================

MANUAL_CODE = (
    "a = 10;\n"
    "b = 20;\n"
    "c = a + 5;\n"
    "unused_sum = c + b;\n"
    "print(c);\n"
)

# =============================================================================
#  TERMINAL COLORS  (safe ASCII fallback on Windows)
# =============================================================================

def _supports_ansi():
    """Return True if the terminal likely supports ANSI codes."""
    if os.name == "nt":
        # Windows 10+ supports ANSI in ConEmu/WT; classic cmd might not
        try:
            import ctypes
            kernel = ctypes.windll.kernel32
            kernel.SetConsoleMode(kernel.GetStdHandle(-11), 7)
            return True
        except Exception:
            return False
    return True

USE_COLOR = _supports_ansi()

def clr(text, code):
    return f"\033[{code}m{text}\033[0m" if USE_COLOR else text

GREEN  = "92"
RED    = "91"
YELLOW = "93"
CYAN   = "96"
BOLD   = "1"
DIM    = "2"

def hr(n=70, char="-"):
    return char * n

# =============================================================================
#  MODEL TESTER
# =============================================================================

def test_model_new_sdk(client, model_name: str) -> dict:
    """Test using new google.genai SDK."""
    result = {"model": model_name, "status": None, "snippet": "", "error": ""}
    try:
        response = client.models.generate_content(
            model=model_name,
            contents=TEST_PROMPT,
            config=genai_types.GenerateContentConfig(
                temperature=0.0,
                max_output_tokens=16,
            ),
        )
        text = response.text.strip() if response.text else "(empty)"
        result["status"]  = "ok"
        result["snippet"] = text[:80]
    except Exception as exc:
        result["status"], result["error"] = _classify_error(exc)
    return result


def test_model_legacy_sdk(model_name: str) -> dict:
    """Test using old google.generativeai SDK."""
    result = {"model": model_name, "status": None, "snippet": "", "error": ""}
    try:
        model = genai_legacy.GenerativeModel(model_name)
        resp  = model.generate_content(
            TEST_PROMPT,
            generation_config=genai_legacy.types.GenerationConfig(
                temperature=0.0,
                max_output_tokens=16,
            ),
        )
        text = resp.text.strip() if resp.text else "(empty)"
        result["status"]  = "ok"
        result["snippet"] = text[:80]
    except Exception as exc:
        result["status"], result["error"] = _classify_error(exc)
    return result


def _classify_error(exc):
    msg = str(exc).lower()
    short = str(exc)[:200]
    if any(k in msg for k in ("not found", "does not exist", "404")):
        return "not_found", short
    if any(k in msg for k in ("permission", "access", "403", "enable billing", "iam")):
        return "blocked", short
    if any(k in msg for k in ("quota", "resource exhausted", "429")):
        return "quota", short
    if any(k in msg for k in ("deprecated", "sunset")):
        return "deprecated", short
    if "invalid" in msg and "key" in msg:
        return "bad_key", short
    return "error", short


def print_result(r: dict):
    s     = r["status"]
    model = r["model"]
    if s == "ok":
        line = f"  [OK]      {model}  ->  {r['snippet']}"
        print(clr(line, GREEN))
    elif s == "blocked":
        print(clr(f"  [BLOCKED] {model}", YELLOW))
    elif s == "not_found":
        print(clr(f"  [NOFOUND] {model}", DIM))
    elif s == "quota":
        print(clr(f"  [QUOTA]   {model}", YELLOW))
    elif s == "bad_key":
        print(clr(f"  [BADKEY]  {model}", RED))
    elif s == "deprecated":
        print(clr(f"  [RETIRED] {model}", DIM))
    else:
        short = r["error"][:70] if r["error"] else "?"
        print(clr(f"  [ERROR]   {model}  [{short}]", RED))

# =============================================================================
#  MAIN
# =============================================================================

def main():
    print()
    print(hr(70, "="))
    print("  Gemini Model Tester  -  DCE Visualizer Project")
    print(hr(70, "="))

    # Key check
    if not API_KEY or API_KEY == "your_gemini_api_key_here":
        print(clr("\n  ERROR: GEMINI_API_KEY is not set!", RED))
        print("  Add it to your .env file:  GEMINI_API_KEY=AIza...\n")
        sys.exit(1)

    key_preview = API_KEY[:8] + "..." + API_KEY[-4:]
    print(f"\n  API Key : {clr(key_preview, GREEN)}")
    print(f"  SDK     : {'google.genai (new)' if NEW_SDK else 'google.generativeai (legacy)'}")
    print(f"  Models  : {len(ALL_MODELS)} to test\n")
    print(hr())

    # Init client
    if NEW_SDK:
        client = genai.Client(api_key=API_KEY)
    else:
        genai_legacy.configure(api_key=API_KEY)
        client = None

    # Test all models
    results = []
    working = []
    print(f"\n  Testing each model... (this may take ~60 s)\n")

    for i, model_name in enumerate(ALL_MODELS, 1):
        label = f"  [{i:02d}/{len(ALL_MODELS)}] {model_name}"
        print(f"{label} ...", end="", flush=True)

        if NEW_SDK:
            r = test_model_new_sdk(client, model_name)
        else:
            r = test_model_legacy_sdk(model_name)

        results.append(r)
        print(f"\r{' ' * (len(label) + 6)}\r", end="")
        print_result(r)

        if r["status"] == "ok":
            working.append(model_name)

    # Summary
    print()
    print(hr(70, "="))
    print("  SUMMARY")
    print(hr(70, "="))

    by_status = {}
    for r in results:
        by_status.setdefault(r["status"], []).append(r["model"])

    counts = [
        ("[OK]      Working",       "ok"),
        ("[BLOCKED] Blocked",       "blocked"),
        ("[NOFOUND] Not found",     "not_found"),
        ("[QUOTA]   Quota hit",     "quota"),
        ("[BADKEY]  Bad key",       "bad_key"),
        ("[RETIRED] Retired",       "deprecated"),
        ("[ERROR]   Other errors",  "error"),
    ]
    for label, key in counts:
        n = len(by_status.get(key, []))
        if n > 0:
            print(f"  {label:<30} {clr(str(n), BOLD)}")

    if working:
        print()
        print(clr("  MODELS YOU CAN USE RIGHT NOW:", GREEN))
        for m in working:
            print(f"    -> {clr(m, GREEN)}")
    else:
        print()
        print(clr("  WARNING: No working models found - check your API key / billing.", YELLOW))

    # -------------------------------------------------------------------------
    #  Manual code test
    # -------------------------------------------------------------------------
    print()
    print(hr(70, "="))
    print("  MANUAL CODE TEST")
    print(hr(70, "="))
    print()
    print("  Source code:")
    print()
    for line in MANUAL_CODE.strip().splitlines():
        print(f"    {clr(line, CYAN)}")
    print()

    try:
        from dce_engine import run_dce, run_attribution, run_llm_analysis

        # [1] Static DCE
        print(clr("  [1] Static DCE Analysis", BOLD))
        dce_data = run_dce(MANUAL_CODE)
        if "error" in dce_data:
            print(f"      ERROR: {dce_data['error']}")
        else:
            s = dce_data["stats"]
            print(f"      Total        : {s['total_before']}")
            print(f"      Live (kept)  : {clr(str(s['total_after']), GREEN)}")
            print(f"      Dead (elim.) : {clr(str(s['dead_count']), RED)}")
            print(f"      Eliminated   : {clr(str(s['pct_eliminated']) + '%', YELLOW)}")
            print()
            print("      Instructions:")
            for instr in dce_data["instructions"]:
                tag   = "[DEAD]" if instr["dead"] else "[LIVE]"
                color = RED if instr["dead"] else GREEN
                print(f"        {clr(tag, color)} {instr['text']}")

        # [2] LOO Attribution
        print()
        print(clr("  [2] LOO Attribution Scores", BOLD))
        attr_data = run_attribution(MANUAL_CODE)
        if "error" in attr_data:
            print(f"      ERROR: {attr_data['error']}")
        else:
            print(f"      Baseline dead-code prob : {attr_data['baseline_dead_prob']}")
            print(f"      High-risk lines         : {clr(str(attr_data['stats']['high_importance']), RED)}")
            print()
            print(f"      {'IDX':<5} {'SCORE':<10} {'IMPORTANCE':<12} INSTRUCTION")
            print(f"      {hr(58, '-')}")
            for a in attr_data["attributions"]:
                imp      = a["importance"].upper()
                color    = RED if imp == "HIGH" else (YELLOW if imp == "MEDIUM" else (CYAN if imp == "LOW" else DIM))
                score_s  = f"{a['attribution']:.4f}"
                dead_tag = " [DEAD]" if a["is_dead_by_dce"] else ""
                print(f"      {a['index']:<5} "
                      f"{clr(score_s, color):<20} "
                      f"{clr(imp, color):<22} "
                      f"{a['text'][:40]}{clr(dead_tag, RED)}")

        # [3] LLM
        print()
        if working:
            chosen = working[0]
            print(clr(f"  [3] LLM Structured Analysis  (model: {chosen})", BOLD))
            llm_data = run_llm_analysis(MANUAL_CODE)
            if "error" in llm_data:
                print(f"      ERROR: {llm_data['error']}")
            else:
                verdict = clr("YES - dead code found", RED) if llm_data.get("dead_code") else clr("NO - code is clean", GREEN)
                print(f"      Dead code   : {verdict}")
                print(f"      Type        : {llm_data.get('type', 'N/A')}")
                print(f"      Lines       : {llm_data.get('line_numbers', [])}")
                print(f"      Explanation : {llm_data.get('explanation', '')}")
                if llm_data.get("fixed_code"):
                    print()
                    print(clr("      Fixed Code:", GREEN))
                    for line in llm_data["fixed_code"].splitlines():
                        print(f"        {clr(line, GREEN)}")
        else:
            print(clr("  [3] Skipping LLM - no working models found.", YELLOW))

    except ImportError as e:
        print(clr(f"  Cannot import dce_engine: {e}", RED))
    except Exception as e:
        print(clr(f"  Error: {e}", RED))

    print()
    print(hr(70, "="))
    print("  Done!")
    print(hr(70, "="))
    print()


if __name__ == "__main__":
    main()
