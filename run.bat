@echo off
cd /d "%~dp0"
python -c "import PySide6, cv2, numpy, PIL, keyboard" 2>nul || python -m pip install --user -r requirements.txt
start "" pythonw main.py
