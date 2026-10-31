@echo off
rem Gera dist\TOSCO.exe (um arquivo só). Precisa de Python 3.12 com as dependências do requirements.txt.
cd /d "%~dp0"
python -m pip install --user -r requirements.txt pyinstaller
python -c "from PySide6.QtWidgets import QApplication; app=QApplication([]); from tosco.ui.widgets import make_icon; make_icon(256)[1].save('tosco.png')"
python -c "from PIL import Image; Image.open('tosco.png').save('tosco.ico', sizes=[(16,16),(32,32),(48,48),(64,64),(128,128),(256,256)])"
python -m PyInstaller --noconfirm --clean --onefile --windowed --name TOSCO --icon tosco.ico ^
  --collect-submodules winrt --collect-binaries winrt --collect-binaries onnxruntime ^
  --exclude-module tkinter --exclude-module matplotlib ^
  main.py
echo.
echo Pronto: dist\TOSCO.exe
