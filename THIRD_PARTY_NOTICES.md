# Componentes de terceros

El código propio de CarryIt (carpeta `carryit/`, `main.py` y los scripts del repositorio) se distribuye con la **licencia MIT** (archivo `LICENSE`).

El instalador y la versión portátil incluyen además los componentes siguientes, cada uno con su propia licencia. Como algunos son **GPL**, la distribución binaria se ofrece así:

- **El programa de Python empaquetado** (`CarryIt.exe` con sus bibliotecas, incluidos gallery-dl —GPL-2.0 únicamente— y mutagen) se distribuye bajo los términos de la **GPL versión 2**.
- **FFmpeg** (`ffmpeg/`) es un programa aparte, que CarryIt solo ejecuta, y se distribuye bajo la **GPL versión 3**.

El código fuente de cada componente está disponible en los enlaces indicados, y el de esta app en su repositorio.

| Componente | Uso en la app | Licencia | Código fuente |
|---|---|---|---|
| yt-dlp | Motor de descarga | Unlicense (dominio público) | https://github.com/yt-dlp/yt-dlp |
| gallery-dl | Motor de descarga de imágenes | GPL-2.0 (solo versión 2) | https://github.com/mikf/gallery-dl |
| yt-dlp-ejs | Scripts para resolver los retos de YouTube | Unlicense, MIT e ISC | https://github.com/yt-dlp/ejs |
| FFmpeg (compilación de yt-dlp/FFmpeg-Builds) | Unir video y audio, convertir formatos | GPL versión 3 | https://github.com/yt-dlp/FFmpeg-Builds · https://ffmpeg.org |
| Deno | Motor JavaScript que usa yt-dlp | MIT | https://github.com/denoland/deno |
| Python 3.12 | Intérprete incluido | Python Software Foundation License | https://www.python.org |
| CustomTkinter | Interfaz gráfica | MIT (según sus metadatos, también CC0-1.0) | https://github.com/TomSchimansky/CustomTkinter |
| darkdetect | Detectar el tema claro u oscuro | BSD-3-Clause | https://github.com/albertosottile/darkdetect |
| Pillow | Miniaturas e ícono | MIT-CMU | https://github.com/python-pillow/Pillow |
| mutagen | Portadas y datos en archivos de audio | GPL-2.0 o posterior | https://github.com/quodlibet/mutagen |
| requests | Conexiones HTTP | Apache-2.0 | https://github.com/psf/requests |
| urllib3 | Conexiones HTTP | MIT | https://github.com/urllib3/urllib3 |
| certifi | Certificados raíz | MPL-2.0 | https://github.com/certifi/python-certifi |
| charset-normalizer | Codificación de texto | MIT | https://github.com/jawah/charset_normalizer |
| idna | Nombres de dominio | BSD-3-Clause | https://github.com/kjd/idna |
| websockets | Conexiones WebSocket | BSD-3-Clause | https://github.com/python-websockets/websockets |
| Brotli | Descompresión | MIT | https://github.com/google/brotli |
| curl_cffi (incluye curl-impersonate) | Conexiones que imitan a un navegador (TikTok, X, Dailymotion…) | MIT | https://github.com/lexiforest/curl_cffi |
| pycryptodomex | Cifrado | BSD y dominio público | https://github.com/Legrandin/pycryptodome |
| packaging | Comparar versiones | Apache-2.0 o BSD-2-Clause | https://github.com/pypa/packaging |
| PyInstaller (cargador) | Empaquetar el .exe | GPL-2.0 con excepción para programas empaquetados | https://github.com/pyinstaller/pyinstaller |
| Inno Setup | Crear el instalador | Licencia de Inno Setup (gratuita) | https://jrsoftware.org/isinfo.php |

Los textos completos de las licencias están en los enlaces anteriores. La licencia de FFmpeg se incluye además en `ffmpeg/LICENSE.txt` dentro de la carpeta del programa.

## Aviso de uso

Descarga solo contenido del que tengas los derechos o cuyo autor permita descargarlo. Descargar videos de YouTube puede ir contra sus condiciones de servicio. El programa se ofrece «tal cual», sin garantía.
