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
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap" rel="stylesheet">
    <style>
        * { 
            margin: 0; 
            padding: 0; 
            box-sizing: border-box; 
        }
        body {
            font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
            background: #0f172a;
            min-height: 100vh;
            padding: 40px 20px;
            position: relative;
            overflow-x: hidden;
        }
        body::before {
            content: '';
            position: fixed;
            top: -50%;
            left: -50%;
            width: 200%;
            height: 200%;
            background: 
                radial-gradient(circle at 20% 50%, rgba(120, 119, 198, 0.3), transparent 50%),
                radial-gradient(circle at 80% 80%, rgba(99, 102, 241, 0.3), transparent 50%),
                radial-gradient(circle at 40% 20%, rgba(168, 85, 247, 0.2), transparent 50%);
            animation: gradient 15s ease infinite;
            z-index: 0;
        }
        @keyframes gradient {
            0%, 100% { transform: translate(0, 0) rotate(0deg); }
            50% { transform: translate(5%, 5%) rotate(180deg); }
        }
        .container {
            max-width: 1000px;
            margin: 0 auto;
            background: rgba(30, 41, 59, 0.7);
            backdrop-filter: blur(20px);
            border: 1px solid rgba(148, 163, 184, 0.1);
            border-radius: 24px;
            padding: 40px;
            box-shadow: 0 25px 50px -12px rgba(0, 0, 0, 0.5);
            position: relative;
            z-index: 1;
        }
        .header {
            display: flex;
            align-items: center;
            gap: 16px;
            margin-bottom: 12px;
        }
        .icon-wrapper {
            width: 56px;
            height: 56px;
            background: linear-gradient(135deg, #6366f1 0%, #a855f7 100%);
            border-radius: 16px;
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 28px;
            box-shadow: 0 8px 16px rgba(99, 102, 241, 0.3);
        }
        h1 {
            color: #f1f5f9;
            font-size: 32px;
            font-weight: 700;
            letter-spacing: -0.5px;
        }
        .subtitle {
            color: #94a3b8;
            margin-bottom: 40px;
            font-size: 15px;
            font-weight: 400;
        }
        .input-group {
            margin-bottom: 24px;
        }
        label {
            display: block;
            margin-bottom: 10px;
            font-weight: 500;
            color: #cbd5e1;
            font-size: 14px;
            letter-spacing: 0.3px;
        }
        input[type="url"], input[type="number"] {
            width: 100%;
            padding: 14px 16px;
            background: rgba(15, 23, 42, 0.5);
            border: 1px solid rgba(148, 163, 184, 0.2);
            border-radius: 12px;
            font-size: 15px;
            color: #f1f5f9;
            transition: all 0.3s ease;
            font-family: 'Inter', sans-serif;
        }
        input[type="url"]::placeholder, input[type="number"]::placeholder {
            color: #64748b;
        }
        input:focus {
            outline: none;
            border-color: #6366f1;
            background: rgba(15, 23, 42, 0.7);
            box-shadow: 0 0 0 3px rgba(99, 102, 241, 0.1);
        }
        .button-group {
            display: flex;
            gap: 12px;
            flex-wrap: wrap;
        }
        .btn {
            padding: 14px 28px;
            border: none;
            border-radius: 12px;
            font-size: 15px;
            font-weight: 600;
            cursor: pointer;
            transition: all 0.3s ease;
            display: inline-flex;
            align-items: center;
            gap: 10px;
            font-family: 'Inter', sans-serif;
            letter-spacing: 0.3px;
        }
        .btn-primary {
            background: linear-gradient(135deg, #6366f1 0%, #8b5cf6 100%);
            color: white;
            box-shadow: 0 4px 12px rgba(99, 102, 241, 0.4);
        }
        .btn-primary:hover {
            transform: translateY(-2px);
            box-shadow: 0 8px 20px rgba(99, 102, 241, 0.5);
        }
        .btn-primary:active {
            transform: translateY(0);
        }
        .btn-success {
            background: rgba(16, 185, 129, 0.15);
            color: #10b981;
            border: 1px solid rgba(16, 185, 129, 0.3);
        }
        .btn-success:hover {
            background: rgba(16, 185, 129, 0.25);
            transform: translateY(-2px);
        }
        .status-box {
            margin-top: 24px;
            padding: 16px 20px;
            border-radius: 12px;
            display: none;
            font-size: 14px;
            animation: slideDown 0.3s ease;
        }
        @keyframes slideDown {
            from {
                opacity: 0;
                transform: translateY(-10px);
            }
            to {
                opacity: 1;
                transform: translateY(0);
            }
        }
        .status-box.show {
            display: block;
        }
        .status-success {
            background: rgba(16, 185, 129, 0.15);
            border: 1px solid rgba(16, 185, 129, 0.3);
            color: #6ee7b7;
        }
        .status-error {
            background: rgba(239, 68, 68, 0.15);
            border: 1px solid rgba(239, 68, 68, 0.3);
            color: #fca5a5;
        }
        .status-info {
            background: rgba(59, 130, 246, 0.15);
            border: 1px solid rgba(59, 130, 246, 0.3);
            color: #93c5fd;
        }
        .monitoring-status {
            display: flex;
            align-items: center;
            gap: 12px;
            padding: 16px 20px;
            background: rgba(16, 185, 129, 0.1);
            border: 1px solid rgba(16, 185, 129, 0.2);
            border-radius: 12px;
            margin: 24px 0;
            color: #6ee7b7;
            font-size: 14px;
            font-weight: 500;
        }
        .pulse {
            width: 10px;
            height: 10px;
            background: #10b981;
            border-radius: 50%;
            box-shadow: 0 0 0 0 rgba(16, 185, 129, 0.7);
            animation: pulse-ring 2s infinite;
        }
        @keyframes pulse-ring {
            0% {
                box-shadow: 0 0 0 0 rgba(16, 185, 129, 0.7);
            }
            50% {
                box-shadow: 0 0 0 8px rgba(16, 185, 129, 0);
            }
            100% {
                box-shadow: 0 0 0 0 rgba(16, 185, 129, 0);
            }
        }
        .stats {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 20px;
            margin: 32px 0;
        }
        .stat-card {
            background: rgba(15, 23, 42, 0.5);
            border: 1px solid rgba(148, 163, 184, 0.1);
            padding: 24px;
            border-radius: 16px;
            text-align: center;
            transition: all 0.3s ease;
        }
        .stat-card:hover {
            transform: translateY(-4px);
            border-color: rgba(99, 102, 241, 0.3);
            box-shadow: 0 8px 24px rgba(0, 0, 0, 0.2);
        }
        .stat-value {
            font-size: 36px;
            font-weight: 700;
            background: linear-gradient(135deg, #6366f1 0%, #a855f7 100%);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            background-clip: text;
            margin-bottom: 8px;
        }
        .stat-label {
            font-size: 13px;
            color: #94a3b8;
            font-weight: 500;
            text-transform: uppercase;
            letter-spacing: 0.5px;
        }
        .new-entries {
            margin-top: 40px;
        }
        .entries-header {
            color: #f1f5f9;
            font-size: 20px;
            font-weight: 600;
            margin-bottom: 20px;
            display: flex;
            align-items: center;
            gap: 10px;
        }
        .entry-item {
            background: rgba(251, 191, 36, 0.1);
            border-left: 3px solid #fbbf24;
            padding: 20px;
            margin-bottom: 16px;
            border-radius: 12px;
            animation: slideIn 0.4s ease-out;
            transition: all 0.3s ease;
        }
        .entry-item:hover {
            background: rgba(251, 191, 36, 0.15);
            transform: translateX(4px);
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
            color: #fde68a;
            margin-bottom: 10px;
            line-height: 1.6;
            font-size: 14px;
        }
        .entry-time {
            font-size: 12px;
            color: #fcd34d;
            font-weight: 500;
        }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <div class="icon-wrapper">🔔</div>
            <div>
                <h1>ISIR Monitor</h1>
            </div>
        </div>
        <p class="subtitle">Monitor Czech Insolvency Register from anywhere, in real-time</p>
        
        <div class="input-group">
            <label for="url">ISIR Page URL</label>
            <input type="url" id="url" placeholder="https://isir.justice.cz/isir/ui/rejstrik-seznam">
        </div>
        
        <div class="input-group">
            <label for="interval">Check Interval (minutes)</label>
            <input type="number" id="interval" value="5" min="1">
        </div>
        
        <div class="button-group">
            <button class="btn btn-primary" onclick="startMonitoring()">
                ▶ Start Monitoring
            </button>
            <button class="btn btn-success" onclick="checkNow()">
                🔄 Check Now
            </button>
        </div>
        
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
        
        <div class="new-entries" id="newEntries">
            <h2 class="entries-header" style="display: none;" id="entriesHeader">
                ⚡ New Entries Detected
            </h2>
        </div>
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
            const header = document.getElementById('entriesHeader');
            header.style.display = 'flex';
            
            items.forEach(item => {
                const div = document.createElement('div');
                div.className = 'entry-item';
                div.innerHTML = `
                    <div class="entry-text">${item.text}</div>
                    <div class="entry-time">⏰ Detected: ${new Date(item.timestamp).toLocaleString('cs-CZ')}</div>
                `;
                container.insertBefore(div, container.children[1]);
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
