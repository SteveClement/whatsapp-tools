import os
import re
import zipfile
import html
import shutil
import json
import argparse
from datetime import datetime
from pathlib import Path

def extract_zip(zip_path, extract_dir):
    """Extract the WhatsApp export zip file to the specified directory."""
    os.makedirs(extract_dir, exist_ok=True)
    
    with zipfile.ZipFile(zip_path, 'r') as zip_ref:
        zip_ref.extractall(extract_dir)
    
    print(f"Extracted zip file to {extract_dir}")

def find_chat_file(extract_dir):
    """Find the WhatsApp chat text file in the extract directory."""
    # Look for a file named _chat.txt or similar
    for root, _, files in os.walk(extract_dir):
        for file in files:
            if file.endswith('_chat.txt'):
                return os.path.join(root, file)
    
    raise FileNotFoundError("Could not find _chat.txt file in the extracted directory")

def find_info_file(extract_dir):
    """Find the info.txt file in the extract directory if it exists."""
    for root, _, files in os.walk(extract_dir):
        for file in files:
            if file.lower() == 'info.txt':
                return os.path.join(root, file)
    
    return None

def parse_chat(chat_file_path):
    """Parse the WhatsApp chat file and return structured data."""
    with open(chat_file_path, 'r', encoding='utf-8') as f:
        lines = f.readlines()
    
    print(f"Parsing chat file with {len(lines)} lines")
    
    # Regular expressions for parsing different WhatsApp export formats
    
    # Format 1: Desktop export with brackets [DD/MM/YYYY, HH:MM:SS]
    # Format 2: Mobile export with no brackets DD/MM/YY, HH:MM
    timestamp_pattern = r'^\[?(\d{1,2}/\d{1,2}/\d{2,4},\s\d{1,2}:\d{1,2}(?::\d{1,2})?)\]?'
    
    # Matches media attachments like <attached: 00000179-PHOTO-2025-04-24-16-21-11.jpg>
    # or VID-20230822-WA0001.mp4 (file attached)
    attachment_pattern_1 = r'<attached:\s(\d+-\w+-\d{4}-\d{2}-\d{2}-\d{2}-\d{2}-\d{2}\.\w+)>'
    attachment_pattern_2 = r'([\w-]+\.(?:mp4|jpg|jpeg|png|gif|pdf|doc|docx|xls|xlsx|ppt|pptx))\s*\(file attached\)'
    
    # Matches "image omitted", "<Media omitted>", etc.
    omitted_pattern_1 = r'(?:image|video|audio|document|GIF)\s+omitted'
    omitted_pattern_2 = r'<Media omitted>'
    
    messages = []
    current_message = None
    
    for line_num, line in enumerate(lines):
        line = line.strip()
        if not line:
            continue
        
        timestamp_match = re.match(timestamp_pattern, line)
        
        if timestamp_match:
            # If we found a timestamp, it's the start of a new message
            if current_message:
                messages.append(current_message)
            
            # Extract timestamp and message content
            timestamp_str = timestamp_match.group(1)
            
            # Remove brackets if present
            if timestamp_str.startswith('['):
                timestamp_str = timestamp_str[1:]
            if timestamp_str.endswith(']'):
                timestamp_str = timestamp_str[:-1]
                
            message_content = line[timestamp_match.end():].strip()
            
            # For desktop format, content starts with a colon
            # For mobile format, it starts with a dash
            if message_content.startswith(' - '):
                message_content = message_content[3:]
            elif message_content.startswith(':'):
                message_content = message_content[1:].strip()
            
            # Check for media file directly in message content (mobile format)
            file_attached_match = re.search(attachment_pattern_2, message_content)
            media_info = []
            
            if file_attached_match:
                media_file = file_attached_match.group(1)
                # Determine type from extension
                extension = media_file.split('.')[-1].lower()
                if extension in ['jpg', 'jpeg', 'png', 'gif']:
                    media_type = 'photo'
                elif extension in ['mp4', 'mov', 'avi']:
                    media_type = 'video'
                elif extension in ['mp3', 'wav', 'ogg']:
                    media_type = 'audio'
                else:
                    media_type = 'document'
                
                media_info.append({
                    'type': media_type,
                    'file': media_file
                })
                
                # Remove the file attachment text from content
                message_content = message_content.replace(file_attached_match.group(0), '').strip()
                print(f"Found mobile media in line {line_num+1}: {media_file} of type {media_type}")
            
            # Split the sender from the content
            parts = message_content.split(':', 1)
            if len(parts) > 1:
                sender = parts[0].strip()
                content = parts[1].strip()
            else:
                # This might be a system message or a sender without a message
                if ": " in line and not message_content:
                    # This is a case where the timestamp regex consumed part of the sender
                    # Attempt to reconstruct the original line
                    parts = line.split(": ", 1)
                    if len(parts) > 1:
                        sender = parts[0].replace(timestamp_str, '').strip()
                        if sender.startswith(' - '):
                            sender = sender[3:]
                        content = parts[1].strip()
                    else:
                        sender = "System"
                        content = message_content
                else:
                    sender = "System"
                    content = message_content
            
            current_message = {
                'timestamp': timestamp_str,
                'sender': sender,
                'content': content,
                'media': media_info
            }
        elif current_message:
            # This line is a continuation of the previous message or a media item
            attachment_match_1 = re.search(attachment_pattern_1, line)
            attachment_match_2 = re.search(attachment_pattern_2, line)
            omitted_match_1 = re.search(omitted_pattern_1, line)
            omitted_match_2 = re.search(omitted_pattern_2, line)
            
            if attachment_match_1:
                media_file = attachment_match_1.group(1)
                media_type = media_file.split('-')[1].lower()
                current_message['media'].append({
                    'type': media_type,
                    'file': media_file
                })
                print(f"Found desktop attachment in line {line_num+1}: {media_file}")
            elif attachment_match_2:
                media_file = attachment_match_2.group(1)
                # Determine type from extension
                extension = media_file.split('.')[-1].lower()
                if extension in ['jpg', 'jpeg', 'png', 'gif']:
                    media_type = 'photo'
                elif extension in ['mp4', 'mov', 'avi']:
                    media_type = 'video'
                elif extension in ['mp3', 'wav', 'ogg']:
                    media_type = 'audio'
                else:
                    media_type = 'document'
                
                current_message['media'].append({
                    'type': media_type,
                    'file': media_file
                })
                print(f"Found mobile attachment in line {line_num+1}: {media_file}")
            elif omitted_match_1 or omitted_match_2:
                # Determine media type
                if omitted_match_1:
                    media_type = omitted_match_1.group(0).split()[0].lower()
                else:
                    media_type = 'media'  # Generic type for <Media omitted>
                
                current_message['media'].append({
                    'type': media_type,
                    'file': None  # No file available
                })
            else:
                # Before appending, check if this line contains a file attached pattern
                file_attached_match = re.search(attachment_pattern_2, line)
                if file_attached_match:
                    media_file = file_attached_match.group(1)
                    # Determine type from extension
                    extension = media_file.split('.')[-1].lower()
                    if extension in ['jpg', 'jpeg', 'png', 'gif']:
                        media_type = 'photo'
                    elif extension in ['mp4', 'mov', 'avi']:
                        media_type = 'video'
                    elif extension in ['mp3', 'wav', 'ogg']:
                        media_type = 'audio'
                    else:
                        media_type = 'document'
                    
                    current_message['media'].append({
                        'type': media_type,
                        'file': media_file
                    })
                    print(f"Found follow-up mobile media in line {line_num+1}: {media_file}")
                else:
                    # Append to existing content
                    current_message['content'] += " " + line
    
    # Don't forget to add the last message
    if current_message:
        messages.append(current_message)
    
    print(f"Parsed {len(messages)} messages")
    
    # Final scan for media files in content
    for i, message in enumerate(messages):
        if '(file attached)' in message['content']:
            print(f"Message {i} may contain undetected media: {message['content']}")
            file_attached_match = re.search(r'([\w-]+\.(?:mp4|jpg|jpeg|png|gif|pdf|doc|docx|xls|xlsx|ppt|pptx))\s*\(file attached\)', message['content'])
            if file_attached_match:
                media_file = file_attached_match.group(1)
                # Determine type from extension
                extension = media_file.split('.')[-1].lower()
                if extension in ['jpg', 'jpeg', 'png', 'gif']:
                    media_type = 'photo'
                elif extension in ['mp4', 'mov', 'avi']:
                    media_type = 'video'
                elif extension in ['mp3', 'wav', 'ogg']:
                    media_type = 'audio'
                else:
                    media_type = 'document'
                
                message['media'].append({
                    'type': media_type,
                    'file': media_file
                })
                
                # Remove the file attachment text from content
                message['content'] = message['content'].replace(file_attached_match.group(0), '').strip()
                print(f"Added missing media to message {i}: {media_file}")
    
    return messages

def parse_timestamp(timestamp_str):
    """Parse timestamp string into a datetime object, handling multiple formats."""
    # Remove any brackets if present
    timestamp_str = timestamp_str.strip()
    if timestamp_str.startswith('['):
        timestamp_str = timestamp_str[1:]
    if timestamp_str.endswith(']'):
        timestamp_str = timestamp_str[:-1]
    
    # Try different formats
    formats = [
        '%d/%m/%Y, %H:%M:%S',  # Desktop format: 16/04/2024, 11:59:24
        '%d/%m/%Y, %H:%M',     # Desktop format without seconds
        '%m/%d/%y, %H:%M',     # US mobile format: 8/22/23, 10:33
        '%d/%m/%y, %H:%M',     # European mobile format: 22/8/23, 10:33
        '%d/%m/%y, %H:%M:%S',  # European mobile format with seconds
        '%m/%d/%Y, %H:%M',     # US format with 4-digit year
        '%m/%d/%Y, %H:%M:%S'   # US format with 4-digit year and seconds
    ]
    
    for fmt in formats:
        try:
            return datetime.strptime(timestamp_str, fmt)
        except ValueError:
            continue
    
    # If all formats fail, raise an error with the timestamp that caused problems
    raise ValueError(f"Could not parse timestamp: '{timestamp_str}'")

def export_json(messages, output_file):
    """Export the parsed messages to a JSON file."""
    # Create a serializable version of the messages
    json_data = []
    for message in messages:
        # Convert timestamp to a consistent format
        try:
            timestamp = parse_timestamp(message['timestamp'])
            timestamp_iso = timestamp.isoformat()
        except ValueError as e:
            print(f"Warning: {e}. Using original timestamp string.")
            timestamp_iso = message['timestamp']
        
        # Create a serializable message object
        msg_obj = {
            'timestamp': message['timestamp'],
            'timestamp_iso': timestamp_iso,
            'sender': message['sender'],
            'content': message['content'],
            'media': []
        }
        
        # Add media files
        for media in message['media']:
            media_obj = {
                'type': media['type'],
                'file': media['file']
            }
            msg_obj['media'].append(media_obj)
        
        json_data.append(msg_obj)
    
    # Write the JSON file with proper formatting and encoding
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(json_data, f, ensure_ascii=False, indent=2)
    
    print(f"Generated JSON file: {output_file}")

def find_media_file(extract_dir, filename):
    """Find a media file in the extract directory."""
    # Direct match first
    for root, _, files in os.walk(extract_dir):
        if filename in files:
            return os.path.join(root, filename)
    
    # Try different approaches based on file naming patterns
    if '-' in filename:
        # Handle desktop format: 00000179-PHOTO-2024-04-24-16-21-11.jpg
        parts = filename.split('-')
        if len(parts) >= 2:
            file_id = parts[0]
            file_type = parts[1].lower()
            
            # Try matching by ID and type
            for root, _, files in os.walk(extract_dir):
                for file in files:
                    if file.startswith(file_id) and file_type.lower() in file.lower():
                        return os.path.join(root, file)
    
    # Handle mobile format: IMG-20250425-WA0051.jpg
    # Extract the base pattern (IMG-20250425-WA0051)
    base_name = os.path.splitext(filename)[0]
    extension = os.path.splitext(filename)[1]
    
    for root, _, files in os.walk(extract_dir):
        for file in files:
            # Check if file matches the pattern (exact or with different extension)
            if file.startswith(base_name) or (base_name in file and file.endswith(extension)):
                return os.path.join(root, file)
    
    # Last resort: try a fuzzy match based on key parts of the filename
    # For WhatsApp mobile exports like IMG-20250425-WA0051.jpg
    if filename.startswith(('IMG-', 'VID-', 'AUD-', 'DOC-')) and 'WA' in filename:
        pattern_parts = filename.split('-')
        if len(pattern_parts) >= 3:
            wa_part = next((part for part in pattern_parts if part.startswith('WA')), None)
            date_part = next((part for part in pattern_parts if len(part) == 8 and part.isdigit()), None)
            
            if wa_part or date_part:
                for root, _, files in os.walk(extract_dir):
                    for file in files:
                        if (wa_part and wa_part in file) or (date_part and date_part in file):
                            return os.path.join(root, file)
    
    # If all fails, return None
    return None

def generate_html(messages, extract_dir, output_file, info_text=None, chat_title="WhatsApp Chat"):
    """Generate a nice HTML page from the parsed messages."""
    # Get relative path to JSON file
    json_file = os.path.basename(output_file).replace('.html', '.json')
    
    # Create CSS styles
    css = """
    :root {
        --bg-color: #f0f0f0;
        --container-bg: #fff;
        --header-bg: #128C7E;
        --header-color: white;
        --message-user-bg: #DCF8C6;
        --message-other-bg: #FFFFFF;
        --message-other-border: #E2E2E2;
        --message-system-bg: #f1f1f1;
        --message-system-color: #666;
        --sender-color: #128C7E;
        --time-color: #999;
        --placeholder-bg: #f1f1f1;
        --placeholder-color: #555;
        --link-color: #128C7E;
        --date-color: #666;
        --date-line-color: #e0e0e0;
        --text-color: #000;
        --container-shadow: 0 1px 3px rgba(0, 0, 0, 0.1);
    }
    
    [data-theme="dark"] {
        --bg-color: #121212;
        --container-bg: #1e1e1e;
        --header-bg: #075E54;
        --header-color: white;
        --message-user-bg: #056162;
        --message-other-bg: #2a2a2a;
        --message-other-border: #333;
        --message-system-bg: #2a2a2a;
        --message-system-color: #aaa;
        --sender-color: #25D366;
        --time-color: #808080;
        --placeholder-bg: #2a2a2a;
        --placeholder-color: #aaa;
        --link-color: #25D366;
        --date-color: #aaa;
        --date-line-color: #333;
        --text-color: #e0e0e0;
        --container-shadow: 0 1px 3px rgba(0, 0, 0, 0.3);
    }
    
    * {
        box-sizing: border-box;
        margin: 0;
        padding: 0;
        font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
    }
    
    body {
        background-color: var(--bg-color);
        padding: 20px;
        color: var(--text-color);
        transition: background-color 0.3s ease;
    }
    
    .chat-container {
        max-width: 800px;
        margin: 0 auto;
        background-color: var(--container-bg);
        border-radius: 10px;
        overflow: hidden;
        box-shadow: var(--container-shadow);
        transition: background-color 0.3s ease, box-shadow 0.3s ease;
    }
    
    .chat-header {
        background-color: var(--header-bg);
        color: var(--header-color);
        padding: 15px;
        text-align: center;
        display: flex;
        justify-content: space-between;
        align-items: center;
        transition: background-color 0.3s ease;
    }
    
    .chat-title {
        display: flex;
        align-items: center;
        gap: 10px;
    }
    
    .json-link, .info-button {
        font-size: 0.8em;
        color: rgba(255, 255, 255, 0.8);
        text-decoration: none;
        display: inline-flex;
        align-items: center;
        padding: 3px 8px;
        background: rgba(255, 255, 255, 0.2);
        border-radius: 4px;
        transition: background-color 0.2s;
        position: relative;
    }
    
    .json-link:hover, .info-button:hover {
        background: rgba(255, 255, 255, 0.3);
        text-decoration: none;
    }
    
    .info-tooltip {
        position: absolute;
        visibility: hidden;
        opacity: 0;
        width: 400px;
        background-color: var(--container-bg);
        color: var(--text-color);
        text-align: left;
        border-radius: 6px;
        padding: 15px;
        box-shadow: 0 3px 8px rgba(0, 0, 0, 0.3);
        z-index: 1;
        bottom: 125%;
        left: 50%;
        transform: translateX(-50%);
        transition: opacity 0.3s, visibility 0.3s;
        font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
        font-style: normal;
        font-weight: normal;
        font-size: 0.9em;
        line-height: 1.4;
        white-space: pre-wrap;
        overflow-y: auto;
        max-height: 500px;
        border: 1px solid var(--message-other-border);
    }
    
    .info-tooltip::after {
        content: "";
        position: absolute;
        top: 100%;
        left: 50%;
        margin-left: -5px;
        border-width: 5px;
        border-style: solid;
        border-color: var(--container-bg) transparent transparent transparent;
    }
    
    .modal {
        display: none;
        position: fixed;
        z-index: 10;
        left: 0;
        top: 0;
        width: 100%;
        height: 100%;
        overflow: auto;
        background-color: rgba(0, 0, 0, 0.5);
        backdrop-filter: blur(3px);
    }
    
    .modal-content {
        background-color: var(--container-bg);
        color: var(--text-color);
        margin: 10% auto;
        padding: 20px;
        border: 1px solid var(--message-other-border);
        border-radius: 10px;
        width: 80%;
        max-width: 700px;
        max-height: 70vh;
        box-shadow: 0 5px 15px rgba(0, 0, 0, 0.3);
        position: relative;
        transition: background-color 0.3s ease;
    }
    
    .close-button {
        color: var(--time-color);
        float: right;
        font-size: 28px;
        font-weight: bold;
        cursor: pointer;
        margin-top: -10px;
    }
    
    .close-button:hover {
        color: var(--sender-color);
    }
    
    .modal-body {
        margin-top: 15px;
        white-space: pre-wrap;
        overflow-y: auto;
        max-height: calc(70vh - 100px);
        line-height: 1.5;
    }
    
    .info-button {
        cursor: pointer;
    }
    
    .theme-toggle, .order-toggle {
        background: none;
        border: none;
        color: var(--header-color);
        cursor: pointer;
        font-size: 1.2em;
        display: flex;
        align-items: center;
        padding: 5px;
        border-radius: 50%;
        transition: background-color 0.2s;
    }
    
    .theme-toggle:hover, .order-toggle:hover {
        background-color: rgba(255, 255, 255, 0.1);
    }
    
    .theme-toggle i, .order-toggle i {
        font-style: normal;
    }
    
    .header-buttons {
        display: flex;
        gap: 5px;
    }
    
    .chat-messages {
        padding: 15px;
        overflow-y: auto;
        display: flex;
        flex-direction: column;
        gap: 10px;
    }
    
    .message {
        padding: 8px 12px;
        border-radius: 7.5px;
        position: relative;
        max-width: 75%;
        word-wrap: break-word;
        transition: background-color 0.3s ease, border-color 0.3s ease, color 0.3s ease;
    }
    
    .message.user {
        align-self: flex-end;
        background-color: var(--message-user-bg);
    }
    
    .message.other {
        align-self: flex-start;
        background-color: var(--message-other-bg);
        border: 1px solid var(--message-other-border);
    }
    
    .message.system {
        align-self: center;
        background-color: var(--message-system-bg);
        color: var(--message-system-color);
        font-style: italic;
        max-width: 90%;
        text-align: center;
    }
    
    .message-sender {
        font-weight: bold;
        margin-bottom: 3px;
        color: var(--sender-color);
        transition: color 0.3s ease;
    }
    
    .message-time {
        color: var(--time-color);
        font-size: 0.7em;
        margin-top: 5px;
        text-align: right;
        transition: color 0.3s ease;
    }
    
    .message-content {
        margin-bottom: 5px;
    }
    
    .media-container {
        margin-top: 5px;
        margin-bottom: 5px;
    }
    
    .media-image {
        max-width: 100%;
        max-height: 300px;
        border-radius: 5px;
    }
    
    .media-video {
        max-width: 100%;
        max-height: 300px;
        border-radius: 5px;
    }
    
    .media-placeholder {
        padding: 10px;
        background-color: var(--placeholder-bg);
        border-radius: 5px;
        color: var(--placeholder-color);
        font-style: italic;
        transition: background-color 0.3s ease, color 0.3s ease;
    }
    
    a {
        color: var(--link-color);
        text-decoration: none;
        transition: color 0.3s ease;
    }
    
    a:hover {
        text-decoration: underline;
    }

    .date-separator {
        text-align: center;
        margin: 15px 0;
        color: var(--date-color);
        font-size: 0.8em;
        position: relative;
        transition: color 0.3s ease;
    }
    
    .date-separator:before, .date-separator:after {
        content: "";
        display: inline-block;
        height: 1px;
        background-color: var(--date-line-color);
        width: 35%;
        vertical-align: middle;
        margin: 0 10px;
        transition: background-color 0.3s ease;
    }
    """
    
    # Start building the HTML content
    html_content = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{html.escape(chat_title)}</title>
    <style>{css}</style>
</head>
<body>
    <div class="chat-container">
        <div class="chat-header">
            <div class="chat-title">
                <h1>{html.escape(chat_title)}</h1>
                <a href="{json_file}" class="json-link" download>JSON</a>
                {f'''<div class="info-button" onclick="toggleInfoModal()">
                    Info
                    <div class="info-tooltip">{html.escape(info_text)}</div>
                </div>''' if info_text else ''}
            </div>
            <div class="header-buttons">
                <button class="order-toggle" onclick="toggleChatOrder()" title="Reverse chat order">
                    <i id="order-icon">⏬</i>
                </button>
                <button class="theme-toggle" onclick="toggleTheme()" title="Toggle dark/light mode">
                    <i id="theme-icon">🌙</i>
                </button>
            </div>
        </div>
        
        {f'''<div id="info-modal" class="modal">
            <div class="modal-content">
                <span class="close-button" onclick="closeInfoModal()">&times;</span>
                <h2>Chat Information</h2>
                <div class="modal-body">{html.escape(info_text)}</div>
            </div>
        </div>''' if info_text else ''}
        
        <div class="chat-messages">
"""

    current_date = None
    
    for message in messages:
        # Parse and format the timestamp
        try:
            timestamp = parse_timestamp(message['timestamp'])
            message_date = timestamp.strftime('%d %B %Y')
            message_time = timestamp.strftime('%H:%M')
        except ValueError as e:
            print(f"Warning when formatting date for display: {e}")
            # Fallback for unparseable dates - use the original string
            message_date = message['timestamp'].split(',')[0].strip()
            message_time = message['timestamp'].split(',')[1].strip() if ',' in message['timestamp'] else ""
        
        # Add date separator if it's a new day
        if message_date != current_date:
            html_content += f'            <div class="date-separator">{message_date}</div>\n'
            current_date = message_date
        
        sender = message['sender']
        
        # Determine the message type
        message_type = "system"
        if "~" in sender:
            if "added" in message['content'] or "joined using this group's invite link" in message['content'] or "left" in message['content'] or "changed" in message['content']:
                message_type = "system"
            else:
                message_type = "other"  # Group message from someone else
        elif sender != "System":
            message_type = "user"  # Assume messages without "~" are from the user
        
        # Create the message HTML
        html_content += f'            <div class="message {message_type}">\n'
        
        # Add sender if it's not a system message
        if message_type != "system":
            html_content += f'                <div class="message-sender">{html.escape(sender)}</div>\n'
        
        # Add message content if there is any
        content = message['content']
        if content:
            # First escape the HTML
            content = html.escape(content)
            
            # Then convert URLs to links
            url_pattern = r'(https?://[^\s]+)'
            content = re.sub(url_pattern, r'<a href="\1" target="_blank">\1</a>', content)
            
            html_content += f'                <div class="message-content">{content}</div>\n'
        
        # Add media files if there are any
        if message['media']:
            for media in message['media']:
                html_content += '                <div class="media-container">\n'
                
                if media['file']:
                    media_path = find_media_file(extract_dir, media['file'])
                    if media_path:
                        # Get the relative path from output file to media file
                        rel_path = os.path.relpath(
                            media_path, 
                            os.path.dirname(output_file)
                        )
                        
                        if media['type'] == 'photo':
                            html_content += f'                    <img class="media-image" src="{rel_path}" alt="Image">\n'
                        elif media['type'] == 'video':
                            html_content += f"""                    <video class="media-video" controls>
                        <source src="{rel_path}" type="video/mp4">
                        Your browser does not support video playback.
                    </video>\n"""
                        elif media['type'] == 'audio':
                            html_content += f"""                    <audio controls>
                        <source src="{rel_path}" type="audio/mpeg">
                        Your browser does not support audio playback.
                    </audio>\n"""
                        else:
                            html_content += f'                    <div class="media-placeholder">{media["type"]} file: <a href="{rel_path}" target="_blank">Open {media["file"]}</a></div>\n'
                    else:
                        html_content += f'                    <div class="media-placeholder">{media["type"]} file not found: {media["file"]}</div>\n'
                else:
                    html_content += f'                    <div class="media-placeholder">{media["type"]} file not available</div>\n'
                
                html_content += '                </div>\n'
        
        # Add message time
        html_content += f'                <div class="message-time">{message_time}</div>\n'
        html_content += '            </div>\n'
    
    # Close the HTML document
    html_content += """        </div>
    </div>
    
    <script>
        function toggleTheme() {
            const html = document.documentElement;
            const themeIcon = document.getElementById('theme-icon');
            
            if (html.getAttribute('data-theme') === 'dark') {
                html.removeAttribute('data-theme');
                themeIcon.textContent = '🌙'; // moon icon
                localStorage.setItem('theme', 'light');
            } else {
                html.setAttribute('data-theme', 'dark');
                themeIcon.textContent = '☀️'; // sun icon
                localStorage.setItem('theme', 'dark');
            }
        }
        
        function toggleChatOrder() {
            const chatMessages = document.querySelector('.chat-messages');
            const orderIcon = document.getElementById('order-icon');
            const currentOrder = localStorage.getItem('chatOrder') || 'reverse-chronological'; // Default to reverse now
            
            // Convert children to array for easier manipulation
            const messagesArray = Array.from(chatMessages.children);
            
            // Get date separators and their corresponding messages
            const dateGroups = [];
            let currentGroup = [];
            let currentDate = null;
            
            messagesArray.forEach(element => {
                if (element.classList.contains('date-separator')) {
                    if (currentDate) {
                        dateGroups.push({
                            dateSeparator: currentDate,
                            messages: currentGroup
                        });
                    }
                    currentDate = element;
                    currentGroup = [];
                } else {
                    currentGroup.push(element);
                }
            });
            
            // Don't forget to add the last group
            if (currentDate) {
                dateGroups.push({
                    dateSeparator: currentDate,
                    messages: currentGroup
                });
            }
            
            // Clear the current content
            chatMessages.innerHTML = '';
            
            if (currentOrder === 'chronological') {
                // Reverse the order of date groups
                dateGroups.reverse();
                
                // For each date group, add the date separator and then the messages in reverse order
                dateGroups.forEach(group => {
                    chatMessages.appendChild(group.dateSeparator);
                    group.messages.reverse().forEach(message => {
                        chatMessages.appendChild(message);
                    });
                });
                
                orderIcon.textContent = '⏬'; // Down arrow
                localStorage.setItem('chatOrder', 'reverse-chronological');
            } else {
                // Restore chronological order
                dateGroups.reverse();
                
                dateGroups.forEach(group => {
                    chatMessages.appendChild(group.dateSeparator);
                    group.messages.reverse().forEach(message => {
                        chatMessages.appendChild(message);
                    });
                });
                
                orderIcon.textContent = '⏫'; // Up arrow
                localStorage.setItem('chatOrder', 'chronological');
            }
        }
        
        // Function to set initial chat order
        function setInitialChatOrder() {
            const chatMessages = document.querySelector('.chat-messages');
            const orderIcon = document.getElementById('order-icon');
            const savedOrder = localStorage.getItem('chatOrder');
            
            // If no saved preference, set to reverse chronological by default
            if (!savedOrder) {
                localStorage.setItem('chatOrder', 'reverse-chronological');
            }
            
            // If we want reverse chronological (either by default or saved preference)
            if (!savedOrder || savedOrder === 'reverse-chronological') {
                // Directly manipulate the DOM instead of toggling
                const messagesArray = Array.from(chatMessages.children);
                
                // Get date separators and their corresponding messages
                const dateGroups = [];
                let currentGroup = [];
                let currentDate = null;
                
                messagesArray.forEach(element => {
                    if (element.classList.contains('date-separator')) {
                        if (currentDate) {
                            dateGroups.push({
                                dateSeparator: currentDate,
                                messages: currentGroup
                            });
                        }
                        currentDate = element;
                        currentGroup = [];
                    } else {
                        currentGroup.push(element);
                    }
                });
                
                // Don't forget to add the last group
                if (currentDate) {
                    dateGroups.push({
                        dateSeparator: currentDate,
                        messages: currentGroup
                    });
                }
                
                // Clear the current content
                chatMessages.innerHTML = '';
                
                // Reverse the order of date groups
                dateGroups.reverse();
                
                // For each date group, add the date separator and then the messages in reverse order
                dateGroups.forEach(group => {
                    chatMessages.appendChild(group.dateSeparator);
                    group.messages.reverse().forEach(message => {
                        chatMessages.appendChild(message);
                    });
                });
                
                // Set the icon to show we're in reverse-chronological mode
                orderIcon.textContent = '⏬'; // Down arrow
            }
        }
        
        function toggleInfoModal() {
            const modal = document.getElementById('info-modal');
            if (modal) {
                modal.style.display = 'block';
            }
        }
        
        function closeInfoModal() {
            const modal = document.getElementById('info-modal');
            if (modal) {
                modal.style.display = 'none';
            }
        }
        
        // Set theme based on time or saved preference
        function setInitialTheme() {
            const savedTheme = localStorage.getItem('theme');
            const themeIcon = document.getElementById('theme-icon');
            const currentHour = new Date().getHours();
            
            // Apply dark mode if after 9 PM (21:00) or before 6 AM, or if user previously selected dark mode
            if (savedTheme === 'dark' || currentHour >= 21 || currentHour < 6) {
                document.documentElement.setAttribute('data-theme', 'dark');
                themeIcon.textContent = '☀️'; // sun icon
                localStorage.setItem('theme', 'dark');
            }
        }
        
        // Close modal when clicking outside of it
        window.onclick = function(event) {
            const modal = document.getElementById('info-modal');
            if (modal && event.target === modal) {
                modal.style.display = 'none';
            }
        };
        
        // Check for saved preferences
        document.addEventListener('DOMContentLoaded', () => {
            // Apply theme preference based on time or saved setting
            setInitialTheme();
            
            // Set initial chat order (newest first by default)
            setInitialChatOrder();
        });
    </script>
</body>
</html>"""
    
    # Write the HTML content to the output file
    with open(output_file, 'w', encoding='utf-8') as f:
        f.write(html_content)
    
    print(f"Generated HTML file: {output_file}")

def main():
    # Set up command line argument parsing
    parser = argparse.ArgumentParser(description='Convert WhatsApp chat export to HTML and JSON')
    parser.add_argument('zip_path', nargs='?', help='Path to WhatsApp export zip file')
    parser.add_argument('-o', '--output-dir', help='Output directory (default: ./html)', default='html')
    
    args = parser.parse_args()
    
    # Get input from user if not provided as argument
    zip_path = args.zip_path
    if not zip_path:
        zip_path = input("Enter path to WhatsApp export zip file: ")
    
    # Define paths
    script_dir = os.path.dirname(os.path.abspath(__file__))
    extract_dir = os.path.join(script_dir, args.output_dir)
    output_html = os.path.join(extract_dir, "whatsapp_chat.html")
    output_json = os.path.join(extract_dir, "whatsapp_chat.json")
    
    # Clean any existing extract directory
    if os.path.exists(extract_dir):
        shutil.rmtree(extract_dir)
    
    # Process the export
    try:
        extract_zip(zip_path, extract_dir)
        chat_file = find_chat_file(extract_dir)
        messages = parse_chat(chat_file)
        
        # Check if there's an info.txt file
        info_text = None
        chat_title = "WhatsApp Chat"
        info_file = find_info_file(extract_dir)
        if info_file:
            try:
                with open(info_file, 'r', encoding='utf-8') as f:
                    info_text = f.read()
                    
                    # Check if the first line starts with "Title:" and extract the title
                    lines = info_text.splitlines()
                    if lines and lines[0].startswith("Title:"):
                        chat_title = lines[0][6:].strip()
                        
                print(f"Found info.txt file: {info_file}")
                if chat_title != "WhatsApp Chat":
                    print(f"Using custom chat title: {chat_title}")
            except Exception as e:
                print(f"Warning: Found info.txt but couldn't read it: {e}")
        
        # Generate both HTML and JSON outputs
        generate_html(messages, extract_dir, output_html, info_text, chat_title)
        export_json(messages, output_json)
        
        print("\nProcessing complete!")
        print(f"Open {output_html} in your web browser to view the chat.")
        print(f"JSON data available at: {output_json}")
    
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    main()
