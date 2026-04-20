"""
Minimal Flask server — serves index.html and exposes:
  /api/dce              POST  { source }
  /api/optimize/<pass>  POST  { source }
  /api/all              POST  { source }
  /api/attribution      POST  { source }   ← Section 4.2.1 LOO scoring
  /api/llm              POST  { source }   ← Section 4.2.2 Gemini structured output

Run:  python server.py
Then open:  http://localhost:5000
"""

import os
from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS

# ── Load .env automatically (dotenv optional) ──────────────────────────────
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass  # dotenv not installed; rely on environment variables being set

from dce_engine import run_dce, run_optimization, run_all_passes, run_attribution, run_llm_analysis

app = Flask(__name__, static_folder='.')
CORS(app)


# ── Static pages ────────────────────────────────────────────────────────────
@app.route('/')
def index():
    return send_from_directory('.', 'index.html')


# ── Existing endpoints ───────────────────────────────────────────────────────
@app.route('/api/dce', methods=['POST'])
def dce_endpoint():
    data = request.get_json(force=True)
    source = data.get('source', '')
    result = run_dce(source)
    return jsonify(result)


@app.route('/api/optimize/<pass_name>', methods=['POST'])
def optimize_endpoint(pass_name):
    data = request.get_json(force=True)
    source = data.get('source', '')
    result = run_optimization(source, pass_name)
    return jsonify(result)


@app.route('/api/all', methods=['POST'])
def all_passes_endpoint():
    data = request.get_json(force=True)
    source = data.get('source', '')
    result = run_all_passes(source)
    return jsonify(result)


# ── NEW: Dead Code Attribution  (Section 4.2.1) ─────────────────────────────
@app.route('/api/attribution', methods=['POST'])
def attribution_endpoint():
    """
    Leave-One-Out attribution scoring.
    Returns per-instruction importance scores:
      aᵢ = max(f(C) − f(C₋ᵢ), 0)
    """
    data = request.get_json(force=True)
    source = data.get('source', '')
    result = run_attribution(source)
    return jsonify(result)


# ── NEW: LLM Structured Output  (Section 4.2.2) ─────────────────────────────
@app.route('/api/llm', methods=['POST'])
def llm_endpoint():
    """
    Gemini-powered structured analysis.
    Returns: dead_code, line_numbers, type, explanation, fixed_code.
    """
    data = request.get_json(force=True)
    source = data.get('source', '')
    result = run_llm_analysis(source)
    return jsonify(result)


if __name__ == '__main__':
    key_set = bool(os.environ.get('GEMINI_API_KEY'))
    print("\n  ==========================================")
    print("   DCE Visualizer  ->  http://localhost:5000")
    print(f"   Gemini API key : {'✅ loaded' if key_set else '❌ not set (set GEMINI_API_KEY in .env)'}")
    print("  ==========================================\n")
    app.run(debug=True, port=5000)
