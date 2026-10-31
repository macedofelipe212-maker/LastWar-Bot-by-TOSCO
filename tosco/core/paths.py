"""Pastas de dados. No .exe (PyInstaller) os dados ficam ao lado do executável, não na pasta temporária."""
import os
import sys

if getattr(sys, "frozen", False):
    ROOT = os.path.dirname(sys.executable)
else:
    ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

DATA_DIR = os.path.join(ROOT, "data")
TEMPLATE_DIR = os.path.join(DATA_DIR, "templates")
LOG_DIR = os.path.join(DATA_DIR, "logs")
REPORT_DIR = os.path.join(DATA_DIR, "relatorios")
MODEL_DIR = os.path.join(DATA_DIR, "modelos")
for _d in (DATA_DIR, TEMPLATE_DIR, LOG_DIR, REPORT_DIR, MODEL_DIR):
    os.makedirs(_d, exist_ok=True)
