# Project Overview

This project, "whatsapp-tools," is a collection of Python scripts for working with WhatsApp data. It consists of two main components:

1.  **WhatsApp Group Members Extractor**: A tool that uses Selenium to automate WhatsApp Web and extract group member information.
2.  **WhatsApp Chat Export to HTML**: A tool that converts WhatsApp chat export files into interactive HTML files, with features like media support, dark/light mode, and JSON export.

The project is written in Python and uses `selenium` and `webdriver-manager` for browser automation.

# Building and Running

## Prerequisites

*   Python 3.7+
*   Google Chrome (for the Group Members Extractor)

## Installation

1.  **Create a virtual environment (optional but recommended):**

    ```bash
    python3 -m venv venv
    source venv/bin/activate
    ```

2.  **Install dependencies:**

    ```bash
    pip install -r requirements.txt
    ```

## Running the Tools

### WhatsApp Chat Export to HTML

This tool converts WhatsApp chat export ZIP files into HTML.

*   **To convert a new export:**

    ```bash
    python whatsapp_converter.py convert <path_to_zip_file> -o <output_directory>
    ```

*   **To update an existing export:**

    ```bash
    python whatsapp_converter.py update <path_to_zip_file> -o <output_directory>
    ```

### WhatsApp Group Members Extractor

This tool automates WhatsApp Web to extract group members.

1.  **Create a `config.py` file** in the `group_extractor` directory by copying `group_extractor/config.py.sample`.

2.  **Edit `config.py`** to set your Chrome profile path and the name of the group you want to extract members from.

3.  **Run the script:**

    ```bash
    python group_extractor/main.py
    ```

# Development Conventions

*   The project follows standard Python conventions.
*   The `whatsapp_converter.py` script uses `argparse` for command-line argument parsing.
*   The `group_extractor` uses a `config.py` file for configuration.
*   The code is organized into modules (`chat_exporter`, `group_extractor`).
*   The project includes a `.gitignore` file to exclude common files and directories from version control.
*   The project uses `.flake8` for code linting.
