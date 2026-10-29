"""
ARYA V3 - Complete Desktop Agent API Server
FINAL FIX: Removed extra play_pause call - search_and_play already plays the song!
"""

from flask import Flask, request, jsonify, Response, stream_with_context
from flask_cors import CORS
import asyncio
import time
import requests
from threading import Thread
import json
import os
from dotenv import load_dotenv
import uuid

load_dotenv()

# Import your agents
from desktop_agent_v2 import DesktopAgent
from whatsapp_agent import WhatsAppAgent
from vscode_agent import VSCodeAgent
# AdvancedBrowserAgent removed — browser tasks now handled by arya_browser_api.py on port 8000

app = Flask(__name__)
CORS(app)

# Initialize agents
desktop = DesktopAgent()
whatsapp = WhatsAppAgent()
vscode = VSCodeAgent()
# browser = AdvancedBrowserAgent()  ← removed, use arya_browser_api.py on port 8000

BROWSER_API = "http://localhost:8000"  # arya_browser_api.py
N8N_WEBHOOK_URL = os.getenv("N8N_WEBHOOK_URL", "http://localhost:5678/webhook/arya")

# Session storage (simple in-memory, replace with Redis for production)
sessions = {}

# ==================== CHAT ENDPOINT (for arya.html frontend) ====================

@app.route('/chat', methods=['POST'])
def chat():
    """
    Main chat endpoint for ARYA web UI
    Integrates with n8n workflow and returns streaming response
    
    POST body: {"message": "user message", "session_id": "optional"}
    Returns: Server-Sent Events (SSE) stream or JSON
    """
    data = request.json
    user_message = data.get('message', '')
    session_id = data.get('session_id') or str(uuid.uuid4())
    
    if not user_message:
        return jsonify({"error": "message required"}), 400
    
    # Initialize session if new
    if session_id not in sessions:
        sessions[session_id] = {
            "history": [],
            "created_at": time.time()
        }
    
    # Add user message to history
    sessions[session_id]["history"].append({
        "role": "user",
        "content": user_message,
        "timestamp": time.time()
    })
    
    def generate():
        """Generator function for SSE streaming"""
        
        # Send session_id first
        yield f"data: {json.dumps({'session_id': session_id})}\n\n"
        
        # Send activity event
        yield f"data: {json.dumps({'activity': {'event': 'Query', 'message': user_message}})}\n\n"
        
        try:
            # Send to n8n workflow
            yield f"data: {json.dumps({'activity': {'event': 'Processing', 'message': 'Sending to n8n workflow...'}})}\n\n"
            
            # Send to n8n workflow with both session_id and user_id
            response = requests.post(
                N8N_WEBHOOK_URL,
                json={
                    "message": user_message, 
                    "session_id": session_id,
                    "user_id": "arya_test_user"  # Your profile user_id
                },
                timeout=60
            )
            
            if response.status_code == 200:
                result = response.json()
                
                # Handle both array and object responses from n8n
                if isinstance(result, list) and len(result) > 0:
                    response_text = result[0].get("output", result[0].get("response", "No response"))
                else:
                    response_text = result.get("output", result.get("response", "No response from workflow"))
                
                # Add to session history
                sessions[session_id]["history"].append({
                    "role": "assistant",
                    "content": response_text,
                    "timestamp": time.time()
                })
                
                # Stream response in chunks (simulate streaming)
                words = response_text.split()
                for i, word in enumerate(words):
                    chunk = word + (" " if i < len(words) - 1 else "")
                    yield f"data: {json.dumps({'chunk': chunk})}\n\n"
                    time.sleep(0.02)  # Small delay for smooth streaming
                
                # Send completion event
                yield f"data: {json.dumps({'activity': {'event': 'Complete', 'message': 'Response delivered'}})}\n\n"
                yield f"data: {json.dumps({'done': True})}\n\n"
                
            else:
                error_msg = f"n8n error: {response.status_code}"
                yield f"data: {json.dumps({'chunk': 'Sorry, I encountered an error processing your request.'})}\n\n"
                yield f"data: {json.dumps({'activity': {'event': 'Error', 'message': error_msg}})}\n\n"
                yield f"data: {json.dumps({'done': True})}\n\n"
                
        except requests.exceptions.ConnectionError:
            error_msg = "Can't connect to n8n. Is it running on port 5678?"
            yield f"data: {json.dumps({'chunk': error_msg})}\n\n"
            yield f"data: {json.dumps({'activity': {'event': 'Error', 'message': 'n8n connection failed'}})}\n\n"
            yield f"data: {json.dumps({'done': True})}\n\n"
            
        except Exception as e:
            error_msg = f"Error: {str(e)}"
            yield f"data: {json.dumps({'chunk': 'Something went wrong. Please try again.'})}\n\n"
            yield f"data: {json.dumps({'activity': {'event': 'Error', 'message': error_msg}})}\n\n"
            yield f"data: {json.dumps({'done': True})}\n\n"
    
    # Return SSE stream
    return Response(
        stream_with_context(generate()),
        mimetype='text/event-stream',
        headers={
            'Cache-Control': 'no-cache',
            'X-Accel-Buffering': 'no'
        }
    )

# ==================== SPOTIFY ENDPOINTS ====================

@app.route('/desktop/spotify/search', methods=['POST'])
def spotify_search():
    """Search and play music on Spotify"""
    data = request.json
    query = data.get('query')
    
    if not query:
        return jsonify({"success": False, "error": "Query required"}), 400
    
    # desktop.spotify_search already calls search_and_play which plays the song
    # NO need to call play_pause() - that would just toggle the old song!
    result = desktop.spotify_search(query)
    
    return jsonify(result)

@app.route('/desktop/spotify/play_pause', methods=['POST'])
def spotify_play_pause():
    """Toggle Spotify play/pause"""
    result = desktop.spotify_play_pause()
    return jsonify(result)

@app.route('/desktop/spotify/next', methods=['POST'])
def spotify_next():
    """Next track on Spotify"""
    result = desktop.spotify_next()
    return jsonify(result)

@app.route('/desktop/spotify/previous', methods=['POST'])
def spotify_previous():
    """Previous track on Spotify"""
    result = desktop.spotify_previous()
    return jsonify(result)

# ==================== WHATSAPP ENDPOINTS ====================

@app.route('/desktop/whatsapp/open', methods=['POST'])
def whatsapp_open():
    """Open WhatsApp Desktop"""
    result = whatsapp.open_whatsapp()
    return jsonify(result)

@app.route('/desktop/whatsapp/send_message', methods=['POST'])
def whatsapp_send():
    """
    Send a WhatsApp message
    POST body: {"contact": "John", "message": "Hello!"}
    """
    data = request.json
    contact = data.get('contact')
    message = data.get('message')
    
    if not contact or not message:
        return jsonify({"success": False, "error": "contact and message required"}), 400
    
    result = whatsapp.send_message(contact, message)
    return jsonify(result)

@app.route('/desktop/whatsapp/read_messages', methods=['POST'])
def whatsapp_read():
    """
    Read recent messages from a contact's chat.
    POST body: {"num_messages": 5, "contact": "Neel"}
    Navigates to contact's chat first if provided.
    """
    data = request.json or {}
    num_messages = data.get('num_messages', 5)
    contact = (data.get('contact') or '').strip()

    if contact and contact.lower() not in ('', 'unknown'):
        print(f'[WhatsApp] Navigating to chat: {contact}')
        # search_contact focuses WhatsApp, opens search, navigates to contact
        whatsapp.search_contact(contact)
        import time
        time.sleep(1.0)  # wait for chat to load fully

    result = whatsapp.read_last_messages(num_messages)
    return jsonify(result)

@app.route('/desktop/whatsapp/voice_call', methods=['POST'])
def whatsapp_voice_call():
    """Initiate voice call in current chat"""
    result = whatsapp.click_voice_call()
    return jsonify(result)

# ==================== VS CODE ENDPOINTS ====================

@app.route('/desktop/vscode/open', methods=['POST'])
def vscode_open():
    """
    Open VS Code — uses DETACHED_PROCESS so no CMD window appears
    POST body: {"folder": "/path/to/project"} (optional)
    """
    data = request.json or {}
    folder = data.get('folder')

    try:
        import subprocess
        cmd = ['code']
        if folder:
            cmd.append(folder)
        subprocess.Popen(
            cmd,
            shell=False,
            creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
            if hasattr(subprocess, 'DETACHED_PROCESS') else 0,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )
        return jsonify({"success": True, "message": "Opened VS Code"})
    except Exception as e:
        # Fallback to VSCodeAgent if PATH issue
        result = vscode.open_vscode(folder)
        return jsonify(result)

@app.route('/desktop/vscode/open_file', methods=['POST'])
def vscode_open_file():
    """
    Open a file in VS Code
    POST body: {"file": "test.py"}
    """
    data = request.json
    file_path = data.get('file')
    
    if not file_path:
        return jsonify({"success": False, "error": "file required"}), 400
    
    result = vscode.open_file(file_path)
    return jsonify(result)

@app.route('/desktop/vscode/run_command', methods=['POST'])
def vscode_run_command():
    """
    Run a terminal command in VS Code
    POST body: {"command": "npm install"}
    """
    data = request.json
    command = data.get('command')
    
    if not command:
        return jsonify({"success": False, "error": "command required"}), 400
    
    result = vscode.run_terminal_command(command)
    return jsonify(result)

@app.route('/desktop/vscode/search', methods=['POST'])
def vscode_search():
    """
    Search in files
    POST body: {"term": "function"}
    """
    data = request.json
    term = data.get('term')
    
    if not term:
        return jsonify({"success": False, "error": "term required"}), 400
    
    result = vscode.search_in_files(term)
    return jsonify(result)

@app.route('/desktop/vscode/format', methods=['POST'])
def vscode_format():
    """Format current document"""
    result = vscode.format_document()
    return jsonify(result)

# ==================== BROWSER ENDPOINTS ====================

# ==================== BROWSER ENDPOINTS ====================
# These now proxy to arya_browser_api.py on port 8000

@app.route('/desktop/browser/navigate', methods=['POST'])
def browser_navigate():
    data = request.json
    url = data.get('url')
    if not url:
        return jsonify({"success": False, "error": "url required"}), 400
    try:
        r = requests.post(f"{BROWSER_API}/run-task", json={"task": f"Navigate to {url} and report what you see."}, timeout=60)
        return jsonify(r.json())
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})

@app.route('/desktop/browser/search_google', methods=['POST'])
@app.route('/desktop/browser/search', methods=['POST'])
def browser_search_google():
    data = request.json
    query = data.get('query')
    if not query:
        return jsonify({"success": False, "error": "query required"}), 400
    result = desktop.search_google(query)
    return jsonify(result)

@app.route('/desktop/browser/search_amazon', methods=['POST'])
def browser_search_amazon():
    data = request.json
    product = data.get('product')
    if not product:
        return jsonify({"success": False, "error": "product required"}), 400
    try:
        r = requests.post(f"{BROWSER_API}/run-task",
            json={"task": f"Go to https://www.amazon.in/s?k={product}, find the first result, report its name and price."},
            timeout=90)
        return jsonify(r.json())
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})

@app.route('/desktop/browser/youtube', methods=['POST'])
def browser_youtube():
    data = request.json
    query = data.get('query')
    if not query:
        return jsonify({"success": False, "error": "query required"}), 400
    result = desktop.youtube_search(query)
    return jsonify(result)

@app.route('/desktop/browser/add_to_cart', methods=['POST'])
def browser_add_to_cart():
    return jsonify({"success": False, "error": "Use /desktop/browser/autonomous_shop instead"})

@app.route('/desktop/browser/autonomous_shop', methods=['POST'])
def browser_auto_shop():
    data = request.json
    product = data.get('product')
    max_price = data.get('max_price', 100.0)
    if not product:
        return jsonify({"success": False, "error": "product required"}), 400
    try:
        from urllib.parse import quote
        r = requests.post(f"{BROWSER_API}/run-task",
            json={"task": f"Go to https://blinkit.com/s/?q={quote(product)} and add the first result to cart. Stop before checkout. Report what was added and its price."},
            timeout=120)
        return jsonify(r.json())
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})

# ==================== DESKTOP ENDPOINTS ====================

@app.route('/desktop/open_app', methods=['POST'])
def open_app():
    """Open application"""
    data = request.json
    app_name = data.get('app_name', '').lower().strip()
    
    if not app_name:
        return jsonify({"success": False, "error": "app_name required"}), 400
    
    # VS Code special case: launch silently without opening a CMD window
    # os.startfile and subprocess with shell=True both open a terminal — this doesn't
    if app_name in ('vscode', 'vs code', 'visual studio code', 'code'):
        try:
            import subprocess
            subprocess.Popen(
                ['code'],
                shell=False,                          # no CMD window
                creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
                if hasattr(subprocess, 'DETACHED_PROCESS') else 0,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL
            )
            return jsonify({"success": True, "message": "Opened VS Code"})
        except Exception as e:
            # Fallback to desktop agent if PATH issue
            pass
    
    result = desktop.open_app(app_name)
    return jsonify(result)

@app.route('/desktop/close_app', methods=['POST'])
def close_app():
    """Close application"""
    data = request.json
    app_name = data.get('app_name', '').lower().strip()
    
    if not app_name:
        return jsonify({"success": False, "error": "app_name required"}), 400
    
    # VS Code special case: taskkill by process name, no CMD window
    if app_name in ('vscode', 'vs code', 'visual studio code', 'code'):
        try:
            import subprocess
            subprocess.Popen(
                ['taskkill', '/F', '/IM', 'Code.exe'],
                shell=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL
            )
            return jsonify({"success": True, "message": "Closed VS Code"})
        except Exception as e:
            pass
    
    result = desktop.close_app(app_name)
    return jsonify(result)

@app.route('/desktop/type_text', methods=['POST'])
def type_text():
    """Type text"""
    data = request.json
    text = data.get('text')
    
    if not text:
        return jsonify({"success": False, "error": "text required"}), 400
    
    result = desktop.type_text(text)
    return jsonify(result)

@app.route('/desktop/system/volume', methods=['POST'])
def set_volume():
    """Set system volume"""
    data = request.json
    level = data.get('level')
    
    if level is None:
        return jsonify({"success": False, "error": "level required"}), 400
    
    result = desktop.set_volume(level)
    return jsonify(result)

@app.route('/desktop/system/lock', methods=['POST'])
def lock_screen():
    """Lock screen"""
    result = desktop.lock_screen()
    return jsonify(result)

@app.route('/desktop/screenshot', methods=['POST'])
def screenshot():
    """Take screenshot"""
    data = request.json or {}
    filename = data.get('filename')
    
    result = desktop.take_screenshot(filename)
    return jsonify(result)

@app.route('/desktop/files/downloads', methods=['POST'])
def open_downloads():
    """Open Downloads folder"""
    result = desktop.open_downloads()
    return jsonify(result)

@app.route('/desktop/files/documents', methods=['POST'])
def open_documents():
    """Open Documents folder"""
    result = desktop.open_documents()
    return jsonify(result)

# ==================== HEALTH CHECK ====================

@app.route('/health', methods=['GET'])
def health():
    """Health check endpoint"""
    return jsonify({
        "status": "healthy",
        "service": "ARYA Desktop Agent V3",
        "version": "3.0.2-FINAL"
    })

# ==================== ERROR HANDLERS ====================

@app.errorhandler(404)
def not_found(error):
    return jsonify({"success": False, "error": "Endpoint not found"}), 404

@app.errorhandler(500)
def server_error(error):
    return jsonify({"success": False, "error": "Internal server error"}), 500


if __name__ == '__main__':
    print("🤖 ARYA Desktop Agent V3.0.3-CHAT")
    print("=" * 70)
    print("💬 Chat Endpoint      | ✅ /chat (SSE streaming to n8n)")
    print("🎵 Spotify Control    | ✅ Search & Play")
    print("💬 WhatsApp Control   | ✅ Send/read messages")
    print("💻 VS Code Control    | ✅ Open files, run commands")
    print("🌐 Browser Automation | ✅ Navigate, search, shop")
    print("⚙️  System Control     | ✅ Apps, volume, typing")
    print("=" * 70)
    print("🔗 Server running on http://localhost:5000")
    print(f"📡 n8n Webhook: {N8N_WEBHOOK_URL}")
    print("✅ Web UI can now POST to /chat endpoint!")
    print()
    
    app.run(host='0.0.0.0', port=5000, debug=True)