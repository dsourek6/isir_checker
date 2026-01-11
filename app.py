from flask import Flask, jsonify, request
from flask_cors import CORS
import requests
from bs4 import BeautifulSoup
import re
from typing import Dict, Any

app = Flask(__name__)
CORS(app)

class ISIRChecker:
    """
    Main class that handles checking the ISIR website for updates.
    Keeps track of which entries we've already seen so we can detect new ones.
    """
    def __init__(self):
        # Set to store IDs we've already seen (e.g., "C1 - 1.", "A2 - 3.")
        self.seen_ids = set()
    
    def natural_sort_key(self, s: str):
        """
        Helper function for sorting strings with numbers naturally.
        Example: ["C1", "C2", "C10"] instead of ["C1", "C10", "C2"]
        Splits string into text and number parts for proper sorting.
        """
        return [int(text) if text.isdigit() else text.lower() for text in re.split('([0-9]+)', s)]

    def fetch_and_parse(self, url: str) -> Dict[str, Any]:
        """
        Main function that:
        1. Fetches the HTML from the ISIR URL
        2. Parses it to extract case info and all entries
        3. Organizes entries by section (A, B, C, D, P)
        4. Returns structured data ready for display
        """
        try:
            # === STEP 1: FETCH THE PAGE ===
            headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0 Safari/537.36'}
            response = requests.get(url, headers=headers, timeout=20)
            response.raise_for_status()  # Raises error if request failed
            
            # === STEP 2: PARSE HTML ===
            soup = BeautifulSoup(response.text, 'html.parser')
            sections = {}  # Will store entries organized by section letter
            current_batch_ids = set()  # IDs found in this check (to track new ones)
            
            # Extract case information
            case_info = {}
            detail_table = soup.find('table', {'class': 'evidenceUpadcuDetail'})
            if detail_table:
                rows = detail_table.find_all('tr')
                for row in rows:
                    cells = row.find_all('td')
                    if len(cells) >= 2:
                        label_cell = cells[0] if len(cells) > 1 else cells[0]
                        value_cell = cells[-1]
                        
                        label = label_cell.get_text(separator=' ', strip=True)
                        
                        if 'nadpis' in str(row).lower():
                            h2_tags = row.find_all('h2')
                            if len(h2_tags) >= 2:
                                case_info['name'] = h2_tags[1].get_text(separator=' ', strip=True)
                        elif 'Aktuální stav' in label:
                            case_info['status'] = value_cell.get_text(separator=' ', strip=True)
                        elif 'Spisová značka' in label:
                            # Parse the cell to extract bold parts properly
                            raw_html = str(value_cell)
                            # Extract case number (in strong tag)
                            case_num_match = re.search(r'<strong>\s*([^<]+)\s*</strong>', raw_html)
                            case_number = case_num_match.group(1).strip() if case_num_match else ''
                            
                            # Extract court name (in strong tag with font color)
                            court_match = re.search(r'<strong>\s*<font[^>]*>\s*([^<]+)\s*</font>\s*</strong>', raw_html)
                            court_name = court_match.group(1).strip() if court_match else ''
                            
                            case_info['case_number'] = case_number
                            case_info['court'] = court_name
            
            section_divs = soup.find_all('div', id=lambda x: x and x.startswith('zalozka'))
            
            for section_div in section_divs:
                section_letter = section_div.get('id', '').replace('zalozka', '').upper()
                if section_letter not in ['A', 'B', 'C', 'D', 'P']: continue
                
                table = section_div.find('table', {'class': 'evidenceUpadcuDetailTable'})
                if not table:
                    sections[section_letter] = []
                    continue
                
                rows = table.find_all('tr')[1:]
                rows.reverse() 
                
                parsed_entries = []
                group_metadata = {}  # Store metadata like case numbers for C/P sections
                
                for row in rows:
                    cells = row.find_all('td')
                    if len(cells) < 5: continue
                    
                    # === EXTRACT BASIC INFO ===
                    # Added separator=' ' to ensure multiline text in cells (like address or description) is separated by spaces
                    doc_id = cells[0].get_text(separator=' ', strip=True)  
                    time_str = f"{cells[1].get_text(separator=' ', strip=True)} {cells[2].get_text(separator=' ', strip=True)}"
                    desc = cells[3].get_text(separator=' ', strip=True)
                    
                    # === CHECK IF ENTRY IS GREYED OUT (INVALID/UNAVAILABLE) ===
                    # Greyed entries don't have the 'posledniCislo' class in their spans
                    is_greyed = False
                    first_span = cells[0].find('span')
                    if first_span:
                        span_classes = first_span.get('class', [])
                        # If the span doesn't have 'posledniCislo' class, it's greyed out
                        if 'posledniCislo' not in span_classes:
                            is_greyed = True
                    
                    # === FIND PDF LINK ===
                    # We need to search through multiple cells because PDF links can be in different columns
                    pdf_url = None
                    has_valid_doc = False
                    
                    # Search ALL cells for PDF links (not just specific columns)
                    for cell in cells:
                        # Method 1: Check for direct HREF links (most common now)
                        # Look for <a href="/isir/doc/dokument.PDF?id=...">
                        href_link = cell.find('a', href=re.compile(r'dokument\.PDF\?id=', re.IGNORECASE))
                        if href_link:
                            raw_href = href_link['href']
                            # Construct absolute URL
                            if raw_href.startswith('/'):
                                pdf_url = f"https://isir.justice.cz{raw_href}"
                            else:
                                pdf_url = raw_href if raw_href.startswith('http') else f"https://isir.justice.cz/{raw_href}"
                            has_valid_doc = True
                            break

                        # Method 2: Check for ONCLICK links (legacy/fallback)
                        # Find ANY element with onclick attribute (sometimes it's on <img>, sometimes on <a>)
                        elements_with_onclick = cell.find_all(attrs={"onclick": True})
                        
                        for element in elements_with_onclick:
                            onclick_val = element['onclick']
                            # Extract document ID from: zobrazDokument('12345')
                            # Regex handles single quotes, double quotes, and spaces
                            match = re.search(r"zobrazDokument\s*\(\s*['\"]?(\d+)['\"]?\s*\)", onclick_val)
                            
                            if match:
                                doc_id_extracted = match.group(1)
                                pdf_url = f"https://isir.justice.cz/isir/doc/dokument.PDF?id={doc_id_extracted}"
                                has_valid_doc = True
                                break
                        if has_valid_doc:
                            break
                    
                    # If no PDF found, mark as unavailable
                    if not pdf_url:
                        pdf_url = "#"
                    
                    # === EXTRACT METADATA FOR SECTIONS C AND P ===
                    additional_info = ""
                    
                    if section_letter == 'C' and len(cells) > 8:
                        # For section C: Get "Spisová značka incidenčního sporu" from column 8
                        case_mark = cells[8].get_text(separator=' ', strip=True)
                        if case_mark and case_mark not in ['&nbsp;', '']:
                            additional_info = case_mark
                            # Store this metadata for the group (e.g., "C1")
                            prefix_match = re.match(f'({section_letter}\\d+)', doc_id)
                            if prefix_match:
                                group_key = prefix_match.group(1)
                                if group_key not in group_metadata:
                                    group_metadata[group_key] = additional_info
                    
                    elif section_letter == 'P' and len(cells) > 6:
                        # For section P: Get "Platní věřitelé" from column 7 (index 6)
                        # Note: Index 6 because lists are 0-indexed (column 7 = index 6)
                        platni_cell = cells[8].get_text(separator=' ', strip=True)
                        if platni_cell and platni_cell not in ['&nbsp;', '']:
                            additional_info = platni_cell
                            prefix_match = re.match(f'({section_letter}\\d+)', doc_id)
                            if prefix_match:
                                group_key = prefix_match.group(1)
                                if group_key not in group_metadata:
                                    group_metadata[group_key] = additional_info
                    
                    # === CHECK IF THIS IS A NEW ENTRY ===
                    # New entries are ones we haven't seen before (only after first check)
                    is_new = doc_id not in self.seen_ids and len(self.seen_ids) > 0
                    current_batch_ids.add(doc_id)

                    # === ADD ENTRY TO LIST ===
                    parsed_entries.append({
                        "id": doc_id, 
                        "time": time_str, 
                        "desc": desc, 
                        "pdf_url": pdf_url, 
                        "is_new": is_new,
                        "additional_info": additional_info,
                        "is_greyed": is_greyed,
                        "has_valid_doc": has_valid_doc
                    })

                # === STEP 6: ORGANIZE ENTRIES FOR C AND P SECTIONS ===
                # These sections are grouped (e.g., C1, C2) with multiple sub-entries
                if section_letter in ['C', 'P']:
                    groups = {}
                    prefix_pattern = re.compile(f'({section_letter}\\d+)')
                    
                    # Group entries by their prefix (C1, C2, etc.)
                    for entry in parsed_entries:
                        match = prefix_pattern.match(entry['id'])
                        group_key = match.group(1) if match else "Other"
                        
                        if group_key not in groups: 
                            groups[group_key] = {
                                "entries": [],
                                "metadata": group_metadata.get(group_key, "")
                            }
                        groups[group_key]["entries"].append(entry)
                    
                    # Sort groups naturally (C1, C2, C10 not C1, C10, C2)
                    sorted_keys = sorted(groups.keys(), key=self.natural_sort_key)
                    sections[section_letter] = [
                        {
                            "group": key, 
                            "entries": groups[key]["entries"],
                            "metadata": groups[key]["metadata"]
                        } 
                        for key in sorted_keys
                    ]
                else:
                    # For A, B, D sections: just list all entries (no grouping)
                    sections[section_letter] = parsed_entries
            
            # === STEP 7: UPDATE SEEN IDs ===
            # Remember all IDs from this check so we can detect new ones next time
            self.seen_ids.update(current_batch_ids)
            
            # === STEP 8: RETURN RESULTS ===
            return {"status": "success", "sections": sections, "case_info": case_info}
            
        except Exception as e:
            # If anything goes wrong, return error message
            return {"status": "error", "message": str(e)}

checker = ISIRChecker()

HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="cs">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>ISIR Monitor</title>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800&display=swap" rel="stylesheet">
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        
        body { 
            font-family: 'Inter', sans-serif; 
            background: radial-gradient(ellipse at top left, #1a0b0f 0%, #0a0a0a 50%, #000000 100%);
            background-attachment: fixed;
            color: #e5e5e5; 
            min-height: 100vh;
            display: flex;
            align-items: center;
            justify-content: center;
            padding: 40px 20px;
        }

        .landing-container {
            max-width: 700px;
            width: 100%;
            text-align: center;
        }

        .logo-landing {
            font-size: 48px;
            font-weight: 800;
            margin-bottom: 16px;
            background: linear-gradient(135deg, #ff6b35 0%, #f7931e 100%);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            letter-spacing: -1px;
        }

        .subtitle-landing {
            color: #666;
            margin-bottom: 50px;
            font-size: 16px;
        }

        .search-landing {
            position: relative;
            margin-bottom: 30px;
        }

        .search-landing input {
            width: 100%;
            padding: 20px 28px;
            background: rgba(255, 255, 255, 0.03);
            border: 1px solid rgba(255, 255, 255, 0.08);
            border-radius: 16px;
            color: white;
            font-size: 15px;
            font-family: 'Inter';
            transition: all 0.4s ease;
        }

        .search-landing input:focus {
            outline: none;
            background: rgba(255, 255, 255, 0.05);
            border-color: rgba(255, 107, 53, 0.4);
            box-shadow: 0 0 0 4px rgba(255, 107, 53, 0.1);
        }

        .btn-start {
            padding: 18px 48px;
            background: linear-gradient(135deg, #ff6b35 0%, #f7931e 100%);
            border: none;
            border-radius: 14px;
            color: white;
            font-weight: 700;
            font-size: 16px;
            cursor: pointer;
            transition: all 0.3s ease;
            box-shadow: 0 8px 30px rgba(255, 107, 53, 0.3);
            position: relative;
            overflow: hidden;
        }

        .btn-start::before {
            content: '';
            position: absolute;
            top: 50%;
            left: 50%;
            width: 0;
            height: 0;
            border-radius: 50%;
            background: rgba(255, 255, 255, 0.2);
            transform: translate(-50%, -50%);
            transition: width 0.6s, height 0.6s;
        }

        .btn-start:hover::before {
            width: 300px;
            height: 300px;
        }

        .btn-start:hover {
            transform: translateY(-2px);
            box-shadow: 0 12px 40px rgba(255, 107, 53, 0.4);
        }

        @keyframes pulse {
            0%, 100% { box-shadow: 0 8px 30px rgba(255, 107, 53, 0.3); }
            50% { box-shadow: 0 8px 50px rgba(255, 107, 53, 0.5); }
        }

        .btn-start {
            animation: pulse 2s infinite;
            position: relative;
            z-index: 1;
        }

        .loader {
            position: fixed;
            top: 50%;
            left: 50%;
            transform: translate(-50%, -50%);
            display: none;
            flex-direction: column;
            align-items: center;
            gap: 20px;
            z-index: 1000;
        }

        .loader.active {
            display: flex;
            animation: fadeIn 0.3s ease;
        }

        .spinner {
            width: 60px;
            height: 60px;
            border: 4px solid rgba(255, 107, 53, 0.1);
            border-top-color: #ff6b35;
            border-radius: 50%;
            animation: spin 1s linear infinite;
        }

        @keyframes spin {
            to { transform: rotate(360deg); }
        }

        .loader-text {
            color: #ff6b35;
            font-weight: 600;
            font-size: 16px;
        }

        .status-indicator {
            display: flex;
            align-items: center;
            gap: 8px;
        }

        .live-dot {
            width: 8px;
            height: 8px;
            background: #10b981;
            border-radius: 50%;
            animation: livePulse 2s ease-in-out infinite;
        }

        @keyframes livePulse {
            0%, 100% {
                box-shadow: 0 0 0 0 rgba(16, 185, 129, 0.7);
            }
            50% {
                box-shadow: 0 0 0 8px rgba(16, 185, 129, 0);
            }
        }

        .dashboard { 
            max-width: 1200px;
            width: 100%;
            background: rgba(20, 20, 20, 0.6);
            backdrop-filter: blur(20px);
            border: 1px solid rgba(255, 255, 255, 0.05);
            border-radius: 24px;
            box-shadow: 0 25px 50px -12px rgba(0, 0, 0, 0.8);
            overflow: hidden;
            display: none;
            animation: slideIn 0.5s ease;
        }

        @keyframes slideIn {
            from { opacity: 0; transform: translateY(20px); }
            to { opacity: 1; transform: translateY(0); }
        }

        .header { 
            padding: 30px 40px;
            display: flex;
            justify-content: space-between;
            align-items: center;
            border-bottom: 1px solid rgba(255, 255, 255, 0.05);
            background: linear-gradient(90deg, rgba(255, 107, 53, 0.05) 0%, transparent 100%);
        }

        .logo {
            font-size: 24px;
            font-weight: 800;
            background: linear-gradient(135deg, #ff6b35 0%, #f7931e 100%);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
        }

        .header-right {
            display: flex;
            align-items: center;
            gap: 24px;
        }

        .timer {
            color: #666;
            font-size: 14px;
        }

        .timer span {
            color: #ff6b35;
            font-weight: 700;
        }

        .case-info-box {
            margin: 30px 40px;
            padding: 30px;
            background: linear-gradient(135deg, rgba(255, 107, 53, 0.08) 0%, rgba(247, 147, 30, 0.08) 100%);
            border: 1px solid rgba(255, 107, 53, 0.2);
            border-radius: 16px;
        }

        .case-info-title {
            font-size: 28px;
            font-weight: 700;
            margin-bottom: 20px;
            color: #fff;
        }

        .case-info-row {
            display: grid;
            grid-template-columns: 200px 1fr;
            padding: 12px 0;
            border-bottom: 1px solid rgba(255, 255, 255, 0.05);
        }

        .case-info-row:last-child {
            border-bottom: none;
        }

        .case-info-label {
            color: #888;
            font-size: 14px;
        }

        .case-info-value {
            color: #fff;
            font-weight: 500;
            line-height: 1.6;
        }

        .case-info-value strong {
            font-weight: 700;
        }

        .group-header-meta {
            color: #ff6b35;
            font-size: 12px;
            font-weight: 500;
            margin-top: 4px;
        }

        .tabs {
            display: flex;
            padding: 0 40px;
            background: rgba(0, 0, 0, 0.3);
            overflow-x: auto;
        }

        .tab {
            padding: 18px 28px;
            cursor: pointer;
            color: #666;
            transition: all 0.3s;
            font-weight: 600;
            font-size: 14px;
            border-bottom: 3px solid transparent;
            white-space: nowrap;
        }

        .tab:hover {
            color: #999;
            background: rgba(255, 255, 255, 0.02);
        }

        .tab.active {
            color: #ff6b35;
            border-bottom-color: #ff6b35;
            background: rgba(255, 107, 53, 0.05);
        }

        .content-section {
            display: none;
            padding-bottom: 30px;
        }

        .content-section.active {
            display: block;
            animation: fadeIn 0.4s ease;
        }

        @keyframes fadeIn {
            from { opacity: 0; transform: translateY(10px); }
            to { opacity: 1; transform: translateY(0); }
        }

        .entry-item {
            padding: 24px 40px;
            display: grid;
            grid-template-columns: 140px 180px 1fr 120px;
            align-items: center;
            gap: 24px;
            border-bottom: 1px solid rgba(255, 255, 255, 0.03);
            transition: all 0.3s ease;
        }

        .entry-item:hover {
            background: rgba(255, 255, 255, 0.02);
        }

        .entry-item.is-new {
            background: linear-gradient(90deg, rgba(255, 107, 53, 0.15) 0%, rgba(255, 107, 53, 0.05) 100%);
            border-left: 4px solid #ff6b35;
            animation: highlight 0.6s ease;
        }

        .entry-item.unavailable {
            opacity: 0.4;
            background: rgba(100, 100, 100, 0.1);
        }

        .entry-item.unavailable:hover {
            background: rgba(100, 100, 100, 0.15);
        }

        @keyframes highlight {
            0% { background: rgba(255, 107, 53, 0.3); }
            100% { background: linear-gradient(90deg, rgba(255, 107, 53, 0.15) 0%, rgba(255, 107, 53, 0.05) 100%); }
        }

        .new-badge {
            background: linear-gradient(135deg, #ff6b35 0%, #f7931e 100%);
            color: white;
            font-size: 10px;
            padding: 3px 10px;
            border-radius: 12px;
            font-weight: 800;
            margin-left: 10px;
            box-shadow: 0 2px 8px rgba(255, 107, 53, 0.4);
        }

        .accordion-group {
            margin: 20px 40px;
            background: rgba(255, 255, 255, 0.02);
            border: 1px solid rgba(255, 255, 255, 0.05);
            border-radius: 12px;
            overflow: hidden;
        }

        .accordion-header {
            padding: 20px 28px;
            cursor: pointer;
            display: flex;
            justify-content: space-between;
            align-items: center;
            font-weight: 600;
            transition: all 0.3s;
        }

        .accordion-header:hover {
            background: rgba(255, 255, 255, 0.03);
        }

        .accordion-body {
            display: none;
            background: rgba(0, 0, 0, 0.3);
        }

        .accordion-body.open {
            display: block;
        }

        .pdf-link {
            text-decoration: none;
            font-weight: 600;
            font-size: 13px;
            padding: 10px 18px;
            border: 1px solid rgba(255, 107, 53, 0.3);
            border-radius: 10px;
            color: #ff6b35;
            transition: all 0.3s;
            text-align: center;
            display: inline-block;
        }

        .pdf-link:hover {
            background: rgba(255, 107, 53, 0.15);
            border-color: #ff6b35;
            transform: translateY(-2px);
        }

        .empty-state {
            padding: 80px 40px;
            text-align: center;
            color: #555;
            font-size: 15px;
        }
    </style>
</head>
<body>

<div class="loader" id="loader">
    <div class="spinner"></div>
    <div class="loader-text">Načítání dat...</div>
</div>

<div class="landing-container" id="landing">
    <div class="logo-landing">ISIR MONITOR</div>
    <p class="subtitle-landing">Real-time insolvency registry monitoring</p>
    <div class="search-landing">
        <input type="text" id="urlInput" placeholder="Vložte URL insolvenčního řízení...">
    </div>
    <button class="btn-start" onclick="startMonitoring()">
        <span style="position: relative; z-index: 1;">Spustit monitoring</span>
    </button>
</div>

<div class="dashboard" id="dashboard">
    <div class="header">
        <div class="logo">ISIR MONITOR</div>
        <div class="header-right">
            <div class="status-indicator">
                <div class="live-dot"></div>
                <span style="color: #10b981; font-weight: 600; font-size: 13px;">LIVE</span>
            </div>
            <div class="timer">
                Auto-refresh in <span id="countdown">5:00</span>
            </div>
        </div>
    </div>

    <div id="caseInfo"></div>

    <div class="tabs">
        <div class="tab active" onclick="switchTab('A', this)">Oddíl A - Řízení do úpadku</div>
        <div class="tab" onclick="switchTab('B', this)">Oddíl B - Řízení po úpadku</div>
        <div class="tab" onclick="switchTab('C', this)">Oddíl C - Incidenční spory</div>
        <div class="tab" onclick="switchTab('D', this)">Oddíl D - Ostatní</div>
        <div class="tab" onclick="switchTab('P', this)">Oddíl P - Přihlášky</div>
    </div>

    <div id="container">
        <div id="content-A" class="content-section active"></div>
        <div id="content-B" class="content-section"></div>
        <div id="content-C" class="content-section"></div>
        <div id="content-D" class="content-section"></div>
        <div id="content-P" class="content-section"></div>
    </div>
</div>

<script>
    let timer;
    let secondsLeft = 300;
    let monitoringUrl = '';

    function startMonitoring() {
        monitoringUrl = document.getElementById('urlInput').value;
        if (!monitoringUrl) {
            alert('Prosím vložte URL');
            return;
        }
        
        // Fade out landing, show loader
        const landing = document.getElementById('landing');
        landing.classList.add('hiding');
        
        setTimeout(() => {
            landing.style.display = 'none';
            document.getElementById('loader').classList.add('active');
        }, 300);
        
        // Wait a bit before showing dashboard
        setTimeout(() => {
            triggerCheck();
        }, 400);
    }

    async function triggerCheck() {
        try {
            const res = await fetch('/check', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({url: monitoringUrl})
            });
            const data = await res.json();
            
            if (data.status === 'success') {
                // Hide loader, show dashboard
                document.getElementById('loader').classList.remove('active');
                
                setTimeout(() => {
                    document.getElementById('dashboard').style.display = 'block';
                    document.body.style.alignItems = 'flex-start';
                    document.body.style.paddingTop = '40px';
                }, 300);
                
                renderCaseInfo(data.case_info);
                renderAll(data.sections);
                resetTimer();
            }
        } catch (error) {
            console.error('Error:', error);
            document.getElementById('loader').classList.remove('active');
        }
    }

    function renderCaseInfo(info) {
        const container = document.getElementById('caseInfo');
        if (!info || Object.keys(info).length === 0) {
            container.innerHTML = '';
            return;
        }
        
        let caseNumberHtml = '';
        if (info.case_number) {
            caseNumberHtml = `<strong>${info.case_number}</strong>`;
            if (info.court) {
                caseNumberHtml += ` vedená u <strong>${info.court}</strong>`;
            }
        }
        
        container.innerHTML = `
            <div class="case-info-box">
                <div class="case-info-title">${info.name || 'Detail insolvenčního řízení'}</div>
                ${info.status ? `
                    <div class="case-info-row">
                        <div class="case-info-label">Aktuální stav</div>
                        <div class="case-info-value">${info.status}</div>
                    </div>
                ` : ''}
                ${caseNumberHtml ? `
                    <div class="case-info-row">
                        <div class="case-info-label">Spisová značka</div>
                        <div class="case-info-value">${caseNumberHtml}</div>
                    </div>
                ` : ''}
            </div>
        `;
    }

    function renderAll(sections) {
        ['A', 'B', 'D'].forEach(s => renderFlat(s, sections[s] || []));
        ['C', 'P'].forEach(s => renderGrouped(s, sections[s] || []));
    }

    function renderFlat(id, items) {
        const el = document.getElementById(`content-${id}`);
        if (!items || items.length === 0) {
            el.innerHTML = '<div class="empty-state">Žádné záznamy</div>';
            return;
        }
        
        el.innerHTML = items.map(i => {
            const unavailableClass = i.is_greyed || !i.has_valid_doc ? 'unavailable' : '';
            const newBadge = i.is_new && !unavailableClass ? '<span class="new-badge">NOVÝ</span>' : '';
            const pdfLink = i.pdf_url !== '#' && i.has_valid_doc 
                ? `<a href="${i.pdf_url}" target="_blank" class="pdf-link">PDF</a>` 
                : '<span style="color:#555; font-size:13px">—</span>';
            
            return `
            <div class="entry-item ${i.is_new ? 'is-new' : ''} ${unavailableClass}">
                <div style="font-weight:700; color:#fff">
                    ${i.id}${newBadge}
                </div>
                <div style="color:#888; font-size:13px">${i.time}</div>
                <div style="font-size:14px; color:#ccc">${i.desc}</div>
                ${pdfLink}
            </div>`;
        }).join('');
    }

    function renderGrouped(id, groups) {
        const el = document.getElementById(`content-${id}`);
        if (!groups || groups.length === 0) {
            el.innerHTML = '<div class="empty-state">Žádné záznamy</div>';
            return;
        }
        
        el.innerHTML = groups.map(g => {
            const hasNew = g.entries.some(e => e.is_new && !e.is_greyed && e.has_valid_doc);
            return `
            <div class="accordion-group">
                <div class="accordion-header" onclick="this.nextElementSibling.classList.toggle('open')">
                    <div>
                        <div style="color:#fff">${g.group} ${hasNew ? '<span class="new-badge">AKTUALIZACE</span>' : ''}</div>
                        ${g.metadata ? `<div class="group-header-meta">${g.metadata}</div>` : ''}
                    </div>
                    <span style="font-size:12px; color:#ff6b35">▼</span>
                </div>
                <div class="accordion-body">
                    ${g.entries.map(i => {
                        const unavailableClass = i.is_greyed || !i.has_valid_doc ? 'unavailable' : '';
                        const newBadge = i.is_new && !unavailableClass ? '<span class="new-badge">NOVÝ</span>' : '';
                        const pdfLink = i.pdf_url !== '#' && i.has_valid_doc
                            ? `<a href="${i.pdf_url}" target="_blank" class="pdf-link">PDF</a>`
                            : '<span style="color:#555; font-size:13px">—</span>';
                        
                        return `
                        <div class="entry-item ${i.is_new && !unavailableClass ? 'is-new' : ''} ${unavailableClass}">
                            <div style="font-weight:700; color:#fff">${i.id}${newBadge}</div>
                            <div style="color:#888; font-size:13px">${i.time}</div>
                            <div style="font-size:14px; color:#ccc">${i.desc}</div>
                            ${pdfLink}
                        </div>`;
                    }).join('')}
                </div>
            </div>`;
        }).join('');
    }

    function resetTimer() {
        secondsLeft = 300;
        if (timer) clearInterval(timer);
        timer = setInterval(() => {
            secondsLeft--;
            const m = Math.floor(secondsLeft / 60);
            const s = secondsLeft % 60;
            document.getElementById('countdown').innerText = `${m}:${s < 10 ? '0' : ''}${s}`;
            if (secondsLeft <= 0) triggerCheck();
        }, 1000);
    }

    function switchTab(s, el) {
        document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
        el.classList.add('active');
        document.querySelectorAll('.content-section').forEach(c => c.classList.remove('active'));
        document.getElementById(`content-${s}`).classList.add('active');
    }
</script>
</body>
</html>
"""

@app.route('/')
def index(): return HTML_TEMPLATE

@app.route('/check', methods=['POST'])
def check():
    url = request.json.get('url')
    return jsonify(checker.fetch_and_parse(url))

if __name__ == '__main__':
    app.run(debug=True, port=5000)
