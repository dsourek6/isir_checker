"""
ISIR Web Monitor - Flask Application
Deploy to Render.com, Railway.app, or PythonAnywhere (all have free tiers)
"""

from flask import Flask, render_template, jsonify, request
from flask_cors import CORS
import requests
from bs4 import BeautifulSoup
import hashlib
import json
from datetime import datetime
from pathlib import Path
import threading
import time

app = Flask(__name__)
CORS(app)

# Configuration
CONFIG = {
    "check_interval": 300,  # 5 minutes
    "state_file": "isir_state.json",
    "monitored_urls": {}  # Will store multiple URLs with their states
}

class ISIRChecker:
    def __init__(self):
        self.state_file = Path(CONFIG["state_file"])
        self.load_state()
        self.new_entries = []
        self.last_check = None
        self.is_monitoring = False
        
    def load_state(self):
        if self.state_file.exists():
            try:
                with open(self.state_file, 'r', encoding='utf-8') as f:
                    CONFIG["monitored_urls"] = json.load(f)
            except:
                CONFIG["monitored_urls"] = {}
        
    def save_state(self):
        try:
            with open(self.state_file, 'w', encoding='utf-8') as f:
                json.dump(CONFIG["monitored_urls"], f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"Error saving state: {e}")
    
    def fetch_and_parse(self, url):
        try:
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
            }
            response = requests.get(url, headers=headers, timeout=30)
            response.raise_for_status()
            
            soup = BeautifulSoup(response.text, 'html.parser')
            entries = {}
            
            # Parse table rows
            rows = soup.find_all('tr')[1:] if soup.find_all('tr') else []
            
            for row in rows:
                text = row.get_text(strip=True, separator=' ')
                if not text or len(text) < 10:
                    continue
                    
                entry_hash = hashlib.md5(text.encode()).hexdigest()
                entries[entry_hash] = {
                    'text': text[:500],
                    'timestamp': datetime.now().isoformat()
                }
            
            return entries, None
        except Exception as e:
            return None, str(e)
    
    def check_url(self, url):
        current_entries, error = self.fetch_and_parse(url)
        
        if error:
            return {"status": "error", "message": error}
        
        if url not in CONFIG["monitored_urls"]:
            CONFIG["monitored_urls"][url] = {
                "entries": current_entries,
                "last_check": datetime.now().isoformat(),
                "new_count": 0
            }
            self.save_state()
            return {
                "status": "initialized",
                "message": "URL added to monitoring",
                "count": len(current_entries)
            }
        
        previous = CONFIG["monitored_urls"][url]["entries"]
        new_hashes = set(current_entries.keys()) - set(previous.keys())
        
        new_items = []
        if new_hashes:
            for h in new_hashes:
                new_items.append(current_entries[h])
                self.new_entries.append({
                    "url": url,
                    "entry": current_entries[h],
                    "detected_at": datetime.now().isoformat()
                })
            
            CONFIG["monitored_urls"][url]["entries"] = current_entries
            CONFIG["monitored_urls"][url]["new_count"] = len(new_hashes)
        
        CONFIG["monitored_urls"][url]["last_check"] = datetime.now().isoformat()
        self.save_state()
        
        return {
            "status": "checked",
            "new_entries": len(new_hashes),
            "total_entries": len(current_entries),
            "items": new_items
        }

checker = ISIRChecker()

# HTML Template
HTML_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <title>ISIR Monitor</title>
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Arial, sans-serif;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            min-height: 100vh;
            padding: 20px;
        }
        .container {
            max-width: 900px;
            margin: 0 auto;
            background: white;
            border-radius: 12px;
            padding: 30px;
            box-shadow: 0 20px 60px rgba(0,0,0,0.3);
        }
        h1 {
            color: #333;
            margin-bottom: 10px;
            display: flex;
            align-items: center;
            gap: 10px;
        }
        .subtitle {
            color: #666;
            margin-bottom: 30px;
            font-size: 14px;
        }
        .input-group {
            margin-bottom: 20px;
        }
        label {
            display: block;
            margin-bottom: 8px;
            font-weight: 600;
            color: #555;
        }
        input[type="url"], input[type="number"] {
            width: 100%;
            padding: 12px;
            border: 2px solid #e0e0e0;
            border-radius: 8px;
            font-size: 14px;
            transition: border-color 0.3s;
        }
        input:focus {
            outline: none;
            border-color: #667eea;
        }
        .btn {
            padding: 12px 24px;
            border: none;
            border-radius: 8px;
            font-size: 16px;
            font-weight: 600;
            cursor: pointer;
            transition: all 0.3s;
            display: inline-flex;
            align-items: center;
            gap: 8px;
        }
        .btn-primary {
            background: #667eea;
            color: white;
        }
        .btn-primary:hover {
            background: #5568d3;
            transform: translateY(-2px);
            box-shadow: 0 4px 12px rgba(102, 126, 234, 0.4);
        }
        .btn-success {
            background: #48bb78;
            color: white;
        }
        .status-box {
            margin-top: 20px;
            padding: 15px;
            border-radius: 8px;
            display: none;
        }
        .status-box.show {
            display: block;
        }
        .status-success {
            background: #f0fdf4;
            border: 2px solid #48bb78;
            color: #22543d;
        }
        .status-error {
            background: #fef2f2;
            border: 2px solid #f56565;
            color: #742a2a;
        }
        .status-info {
            background: #eff6ff;
            border: 2px solid #3b82f6;
            color: #1e40af;
        }
        .new-entries {
            margin-top: 30px;
        }
        .entry-item {
            background: #fef3c7;
            border-left: 4px solid #f59e0b;
            padding: 15px;
            margin-bottom: 15px;
            border-radius: 6px;
            animation: slideIn 0.3s ease-out;
        }
        @keyframes slideIn {
            from {
                opacity: 0;
                transform: translateX(-20px);
            }
            to {
                opacity: 1;
                transform: translateX(0);
            }
        }
        .entry-text {
            color: #78350f;
            margin-bottom: 8px;
        }
        .entry-time {
            font-size: 12px;
            color: #92400e;
        }
        .monitoring-status {
            display: flex;
            align-items: center;
            gap: 8px;
            padding: 12px;
            background: #f3f4f6;
            border-radius: 8px;
            margin-bottom: 20px;
        }
        .pulse {
            width: 12px;
            height: 12px;
            background: #10b981;
            border-radius: 50%;
            animation: pulse 2s infinite;
        }
        @keyframes pulse {
            0%, 100% { opacity: 1; }
            50% { opacity: 0.5; }
        }
        .stats {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
            gap: 15px;
            margin: 20px 0;
        }
        .stat-card {
            background: #f9fafb;
            padding: 15px;
            border-radius: 8px;
            text-align: center;
        }
        .stat-value {
            font-size: 28px;
            font-weight: bold;
            color: #667eea;
        }
        .stat-label {
            font-size: 12px;
            color: #6b7280;
            margin-top: 5px;
        }
    </style>
</head>
<body>
    <div class="container">
        <h1>
            <span style="font-size: 32px;">🔔</span>
            ISIR Monitor
        </h1>
        <p class="subtitle">Monitor Czech Insolvency Register from anywhere</p>
        
        <div class="input-group">
            <label for="url">ISIR Page URL</label>
            <input type="url" id="url" placeholder="https://isir.justice.cz/isir/ui/rejstrik-seznam">
        </div>
        
        <div class="input-group">
            <label for="interval">Check Interval (minutes)</label>
            <input type="number" id="interval" value="5" min="1">
        </div>
        
        <button class="btn btn-primary" onclick="startMonitoring()">
            ▶ Start Monitoring
        </button>
        <button class="btn btn-success" onclick="checkNow()" style="margin-left: 10px;">
            🔄 Check Now
        </button>
        
        <div id="status" class="status-box"></div>
        
        <div id="monitoring" class="monitoring-status" style="display: none;">
            <div class="pulse"></div>
            <span>Monitoring active - Next check in <span id="countdown">-</span></span>
        </div>
        
        <div class="stats" id="stats" style="display: none;">
            <div class="stat-card">
                <div class="stat-value" id="totalEntries">-</div>
                <div class="stat-label">Total Entries</div>
            </div>
            <div class="stat-card">
                <div class="stat-value" id="newEntries">0</div>
                <div class="stat-label">New Entries</div>
            </div>
            <div class="stat-card">
                <div class="stat-value" id="lastCheck">-</div>
                <div class="stat-label">Last Check</div>
            </div>
        </div>
        
        <div class="new-entries" id="newEntries"></div>
    </div>
    
    <script>
        let monitoringInterval = null;
        let countdownInterval = null;
        let nextCheckTime = null;
        
        function showStatus(message, type) {
            const statusBox = document.getElementById('status');
            statusBox.className = 'status-box show status-' + type;
            statusBox.textContent = message;
        }
        
        function updateCountdown() {
            if (!nextCheckTime) return;
            const now = Date.now();
            const diff = Math.max(0, Math.floor((nextCheckTime - now) / 1000));
            const mins = Math.floor(diff / 60);
            const secs = diff % 60;
            document.getElementById('countdown').textContent = 
                `${mins}:${secs.toString().padStart(2, '0')}`;
        }
        
        async function checkNow() {
            const url = document.getElementById('url').value;
            if (!url) {
                showStatus('Please enter a URL', 'error');
                return;
            }
            
            showStatus('Checking...', 'info');
            
            try {
                const response = await fetch('/check', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({url})
                });
                
                const data = await response.json();
                
                if (data.status === 'error') {
                    showStatus('Error: ' + data.message, 'error');
                } else if (data.status === 'initialized') {
                    showStatus(`Monitoring initialized with ${data.count} entries`, 'success');
                    document.getElementById('stats').style.display = 'grid';
                    document.getElementById('totalEntries').textContent = data.count;
                } else {
                    showStatus(`Check complete: ${data.new_entries} new entries found`, 'success');
                    document.getElementById('stats').style.display = 'grid';
                    document.getElementById('totalEntries').textContent = data.total_entries;
                    document.getElementById('newEntries').textContent = data.new_entries;
                    document.getElementById('lastCheck').textContent = new Date().toLocaleTimeString('cs-CZ');
                    
                    if (data.new_entries > 0) {
                        displayNewEntries(data.items);
                        if ('Notification' in window && Notification.permission === 'granted') {
                            new Notification('ISIR - New Entry!', {
                                body: `${data.new_entries} new entries detected`
                            });
                        }
                    }
                }
            } catch (error) {
                showStatus('Network error: ' + error.message, 'error');
            }
        }
        
        function displayNewEntries(items) {
            const container = document.getElementById('newEntries');
            items.forEach(item => {
                const div = document.createElement('div');
                div.className = 'entry-item';
                div.innerHTML = `
                    <div class="entry-text">${item.text}</div>
                    <div class="entry-time">Detected: ${new Date(item.timestamp).toLocaleString('cs-CZ')}</div>
                `;
                container.insertBefore(div, container.firstChild);
            });
        }
        
        function startMonitoring() {
            const interval = parseInt(document.getElementById('interval').value) * 60 * 1000;
            
            if (monitoringInterval) {
                clearInterval(monitoringInterval);
                clearInterval(countdownInterval);
            }
            
            document.getElementById('monitoring').style.display = 'flex';
            
            checkNow();
            monitoringInterval = setInterval(checkNow, interval);
            
            nextCheckTime = Date.now() + interval;
            countdownInterval = setInterval(() => {
                updateCountdown();
                if (Date.now() >= nextCheckTime) {
                    nextCheckTime = Date.now() + interval;
                }
            }, 1000);
            
            if ('Notification' in window && Notification.permission !== 'granted') {
                Notification.requestPermission();
            }
        }
    </script>
</body>
</html>
"""

@app.route('/')
def index():
    return HTML_TEMPLATE

@app.route('/check', methods=['POST'])
def check():
    data = request.json
    url = data.get('url')
    
    if not url:
        return jsonify({"status": "error", "message": "No URL provided"})
    
    result = checker.check_url(url)
    return jsonify(result)

@app.route('/status')
def status():
    return jsonify({
        "monitored_urls": list(CONFIG["monitored_urls"].keys()),
        "new_entries": checker.new_entries[-10:]  # Last 10 new entries
    })

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)