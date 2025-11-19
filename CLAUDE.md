# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This repository contains two main tools for working with WhatsApp data:

1. **WhatsApp Chat Export to HTML** (`chat_exporter/`): Converts WhatsApp chat export files into interactive HTML viewers with JSON export capability
2. **WhatsApp Group Members Extractor** (`group_extractor/`): Uses Selenium WebDriver to automate extraction of group information and member details from WhatsApp Web

## Common Commands

### Chat Export to HTML

**Convert a new WhatsApp export:**
```bash
python whatsapp_converter.py convert <export.zip> -o <output_dir>
```

**Update an existing export with new messages:**
```bash
python whatsapp_converter.py update <export.zip> -o <output_dir> --highlight subtle
```

**Add custom info file:**
```bash
python whatsapp_converter.py convert <export.zip> -o <output_dir> -i info.txt
```

**Highlight levels:** `none`, `subtle`, `prominent`

### Group Members Extractor

```bash
cd group_extractor
python main.py
```

**Prerequisites:**
- Configure `group_extractor/config.py` with Chrome profile path and group name
- Chrome must be installed
- WhatsApp Web login session must be active in the Chrome profile

### Environment Setup

```bash
# Create virtual environment
python3 -m venv venv
source venv/bin/activate    # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt
```

## Architecture

### Chat Export to HTML Architecture

The chat exporter follows a modular pipeline architecture:

**Core Components:**

1. **`whatsapp_converter.py`** - CLI entry point with argparse commands (`convert`, `update`)
2. **`chat_exporter/exporter.py`** - Main orchestration layer
   - `process_export()`: Handles new exports
   - `process_update()`: Handles incremental updates to existing exports
   - `check_for_updates()`: Detects new messages by comparing message IDs
   - Media file copying and directory management

3. **`chat_exporter/parser.py`** - Chat file parsing
   - `detect_chat_format()`: Auto-detects desktop vs mobile WhatsApp export formats
   - `parse_chat()`: Converts raw chat text to Message objects
   - `find_chat_file()`: Intelligent chat file detection with scoring algorithm
   - Supports both bracketed `[DD/MM/YYYY, HH:MM:SS]` and unbracketed timestamps
   - Handles both `: ` (desktop) and ` - ` (mobile) separators

4. **`chat_exporter/models.py`** - Data models
   - `Message`: Individual message with ID generation for deduplication
   - `Media`: Media attachment metadata
   - `Chat`: Complete chat with messages and metadata
   - `ChatMetadata`: Tracking message IDs, timestamps, processing history
   - Message ID generation: `{timestamp}-{sender}-{content_hash}` for cross-export consistency

5. **`chat_exporter/renderer.py`** - HTML generation
   - Generates self-contained HTML with embedded CSS/JS
   - Creates local media directory structure
   - Supports dark/light mode toggle
   - Chronological ordering controls (newest-first/oldest-first)
   - Highlight styling for new messages

6. **`chat_exporter/media.py`** - Media handling
   - Media type detection from file extensions
   - Pattern matching for both desktop and mobile attachment formats
   - Handles `<attached: file>` and `file (file attached)` patterns
   - Detects omitted media (`<Media omitted>`, `image omitted`, etc.)

**Data Flow:**

1. Extract ZIP → Temporary directory
2. Find and parse chat file → List of Message objects
3. Create Chat object with metadata
4. For updates: Compare message IDs, merge new messages, mark with `is_new` flag
5. Copy media files to output/media directory
6. Generate HTML with embedded styling and JavaScript
7. Export JSON files (messages, metadata, full chat data)
8. Clean up temporary directory

**Key Design Decisions:**

- **Message Deduplication:** Message IDs are generated from timestamp, sender, and content hash. This allows detecting duplicate messages across multiple exports.
- **Cross-Platform Compatibility:** Auto-detection of desktop vs mobile export formats ensures no manual configuration needed.
- **Update Detection:** The system maintains `chat_data.json` with metadata tracking all message IDs, enabling incremental updates.
- **Self-Contained Output:** HTML files embed all CSS/JS and reference media via local `media/` directory for offline viewing.

### Group Members Extractor Architecture

**Core Components:**

1. **`group_extractor/main.py`** - Main automation script
   - `init_driver()`: Chrome WebDriver initialization with existing profile
   - `wait_for_qr_scan()`: QR code detection loop
   - `search_and_open_group()`: Group search automation
   - `list_all_groups()`: Enumerate all group chats
   - `open_group_info_panel()`: Navigate to group info via three-dot menu
   - `expand_all_members()`: Click "See all" to expand member list
   - `get_group_members()`: Extract member names from DOM

2. **`group_extractor/config.py`** - Configuration file
   - Chrome profile paths
   - Wait times (SHORT_WAIT, LONG_WAIT)
   - Group name filter
   - Debug flags and SLOW_MODE for typing

**Selenium Automation Flow:**

1. Initialize Chrome with existing profile to maintain WhatsApp Web session
2. Navigate to web.whatsapp.com
3. Wait for QR scan if not already logged in
4. List all groups or search specific group by name
5. For each group: open chat → group info panel → expand members → extract names
6. Handle various WhatsApp Web DOM selectors (with TODOs for brittle XPath)

**Important Notes:**

- **Brittle DOM Selectors:** The script uses XPath selectors that may break with WhatsApp Web updates. Search for `TODO` comments marking fragile selectors.
- **Chrome Profile:** Requires a separate Chrome profile directory to avoid conflicts with running Chrome instances.
- **Platform Detection:** `detect_chrome()` checks multiple paths for Chrome/Chromium on macOS, Linux, and Windows.

## File Organization

```
whatsapp-tools/
├── whatsapp_converter.py          # CLI entry point for chat exporter
├── chat_exporter/                 # Chat export package
│   ├── exporter.py               # Main export orchestration
│   ├── parser.py                 # Chat file parsing
│   ├── models.py                 # Data models (Message, Chat, etc.)
│   ├── renderer.py               # HTML generation
│   ├── media.py                  # Media detection/handling
│   └── utils.py                  # Utility functions
├── group_extractor/              # Group scraper package
│   ├── main.py                  # Selenium automation script
│   └── config.py                # Configuration template
├── requirements.txt              # Python dependencies
└── ingest.sh                    # Example batch processing script
```

## Key Implementation Details

### Chat Export Update Mechanism

Updates work by:
1. Loading existing `chat_data.json` (contains metadata with all message IDs)
2. Parsing new export ZIP
3. Computing set difference: `new_ids - existing_ids`
4. Merging new messages into existing Chat object
5. Marking new messages with `is_new=True` for HTML highlighting
6. Incrementing metadata counters and processing history

### WhatsApp Export Format Detection

The parser scores each text file based on:
- Filename patterns (`_chat.txt`, contains "chat")
- File size (larger = more likely chat export)
- Content analysis (percentage of lines matching timestamp regex)

Then selects highest-scoring file as the chat export.

### Media Directory Structure

The exporter creates a local `media/` directory in the output folder:
- All media files are copied from the ZIP to `<output_dir>/media/`
- HTML references media as `./media/<filename>`
- This creates self-contained output that can be moved/archived

## Testing Approach

When testing changes:
1. Use sample WhatsApp exports from both desktop and mobile
2. Test update flow by processing same chat at different times
3. Verify media files are correctly copied and referenced
4. Check HTML renders correctly in different browsers
5. For group extractor: Test with groups of varying sizes (especially >16 members)

## Common Issues

**Chat Exporter:**
- If timestamp parsing fails, check `parser.py:detect_chat_format()` patterns
- If media not showing, verify files exist in `<output_dir>/media/`
- Update failures usually indicate message ID generation changes - check `models.py:_generate_id()`

**Group Extractor:**
- XPath selectors break frequently with WhatsApp Web updates
- "See all members" button may not appear for small groups (<16 members)
- QR code selector may change - see `main.py:wait_for_qr_scan()` TODO
- Chrome profile conflicts if main Chrome is running with same profile
