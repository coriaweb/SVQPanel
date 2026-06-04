"""
Configuración global de SVQPanel
"""
import os as _os

PANEL_NAME = "SVQPanel"

# Lee la versión desde VERSION (raíz del repo) para tener una única fuente de verdad.
# Fallback a "0.0.0" si el archivo no existe (entorno de desarrollo sin clonar).
_VERSION_FILE = _os.path.join(_os.path.dirname(_os.path.dirname(__file__)), "VERSION")
try:
    with open(_VERSION_FILE) as _f:
        PANEL_VERSION = _f.read().strip()
except OSError:
    PANEL_VERSION = "0.0.0"
