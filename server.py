"""
Minimal Flask server — serves index.html and exposes /api/dce and /api/optimize endpoints.
Run:  python server.py
Then open:  http://localhost:5000
"""

from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
import os
from dce_engine import run_dce, run_optimization, run_all_passes

app = Flask(__name__, static_folder='.')
CORS(app)

@app.route('/')
def index():
    return send_from_directory('.', 'index.html')

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

if __name__ == '__main__':
    print("\n  ==========================================")
    print("   DCE Visualizer  ->  http://localhost:5000")
    print("  ==========================================\n")
    app.run(debug=True, port=5000)

