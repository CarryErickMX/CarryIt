"""CarryIt: aplicación de escritorio para descargar video o solo el audio, con yt-dlp."""
import os

APP_NAME = "CarryIt"
APP_ID = "CarryIt"                 # carpeta de datos: %APPDATA%\CarryIt
AUTHOR = "CARRY (キャリー)"
__version__ = "1.0.1"

# Repositorio de GitHub donde se publican las versiones, como "usuario/CarryIt".
# Mientras esté vacío, la app no busca versiones nuevas de sí misma.
GITHUB_REPO = "CarryErickMX/CarryIt"

# Nombre del mutex de Windows: el instalador lo usa para saber si la app está abierta.
APP_MUTEX = "CarryIt.Mutex"
APP_USER_MODEL_ID = "Carry.CarryIt"

_RESOURCES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "resources")


def resource(name: str) -> str:
    """Ruta de un archivo de carryit/resources (funciona también dentro del .exe)."""
    return os.path.join(_RESOURCES, name)
