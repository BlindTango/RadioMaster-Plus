"""Launcher script for RadioMaster+ application."""

import sys
import os

# Add src directory to Python path
src_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'src')
if src_path not in sys.path:
    sys.path.insert(0, src_path)

# Import and run the application
from radiomaster.app import RadioMasterApp

if __name__ == '__main__':
    app = RadioMasterApp()
    app.MainLoop()
