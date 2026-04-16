"""
Minimal Flask server — serves index.html and exposes /api/dce endpoint.
Run:  python server.py
Then open:  http://localhost:5000
"""

from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
import os
from dce_engine import run_dce

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

if __name__ == '__main__':
    print("\n  ==========================================")
    print("   DCE Visualizer  ->  http://localhost:5000")
    print("  ==========================================\n")
    app.run(debug=True, port=5000)
