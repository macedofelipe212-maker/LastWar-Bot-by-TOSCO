@echo off
rem Gera dist\TOSCO.exe (um arquivo so). Precisa de Python 3.12 com as dependencias do requirements.txt.
cd /d "%~dp0"
python -m pip install --user -r requirements.txt pyinstaller
rem baixa os modelos do RapidOCR uma vez para irem dentro do exe (sem isso o exe baixaria a cada abertura).
rem O RapidOCR so abre os modelos na primeira leitura, por isso le uma imagem em branco; aborta se faltarem.
python -c "import numpy as np; from rapidocr import RapidOCR; e=RapidOCR(); z=np.full((48,160,3),255,np.uint8); e(z,use_cls=False); e(z,use_det=False,use_cls=False)"
python -c "import os, rapidocr, sys; d=os.path.join(os.path.dirname(rapidocr.__file__),'models'); f=[x for x in os.listdir(d) if x.endswith('.onnx')]; print('modelos RapidOCR:', f); sys.exit(0 if len(f)>=2 else 1)"
if errorlevel 1 (
  echo ERRO: modelos do RapidOCR nao baixaram - confira a internet e rode de novo.
  exit /b 1
)
python -c "from PySide6.QtWidgets import QApplication; app=QApplication([]); from tosco.ui.widgets import make_icon; make_icon(256)[1].save('tosco.png')"
python -c "from PIL import Image; Image.open('tosco.png').save('tosco.ico', sizes=[(16,16),(32,32),(48,48),(64,64),(128,128),(256,256)])"
rem torch/ultralytics/paddle/openvino ficam de fora: o TOSCO usa so o onnxruntime (exe ficaria com GBs)
python -m PyInstaller --noconfirm --clean --onefile --windowed --name TOSCO --icon tosco.ico ^
  --collect-submodules winrt --collect-binaries winrt --collect-binaries onnxruntime ^
  --collect-data rapidocr --hidden-import rapidocr ^
  --exclude-module tkinter --exclude-module matplotlib --exclude-module torch --exclude-module torchvision ^
  --exclude-module ultralytics --exclude-module paddle --exclude-module openvino --exclude-module tensorrt ^
  main.py
echo.
echo Pronto: dist\TOSCO.exe
