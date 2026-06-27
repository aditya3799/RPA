#!/usr/bin/env python3
"""
Launch the macOS RPA Control UI
Usage: python run_mac_ui.py
"""

import sys
import os

# Ensure we're in the correct directory
script_dir = os.path.dirname(os.path.abspath(__file__))
os.chdir(script_dir)

# Add current directory to path
sys.path.insert(0, script_dir)

from mac_ui import run_mac_ui

if __name__ == "__main__":
    print("🚀 Starting macOS RPA Control UI...")
    print("💡 Tip: Press Ctrl+Shift+Space to toggle the UI")
    print("📝 Tip: Press Escape to hide the UI")
    run_mac_ui()
