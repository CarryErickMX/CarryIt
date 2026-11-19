"""Idiomas de la interfaz. El texto original (español) es la clave; aquí están sus traducciones.

Uso:  from .i18n import _      ->   _("Descargar")   ->   "Download" si el idioma es inglés.
El idioma se fija una vez al iniciar (setup), antes de crear la interfaz; cambiarlo requiere reiniciar.
"""
from __future__ import annotations

import locale
import os

LANGUAGES = {"auto": "Automático (idioma de Windows)", "es": "Español", "en": "English"}
_current = "es"


def detect() -> str:
    """Español si Windows está en español; inglés en cualquier otro caso."""
    try:
        if os.name == "nt":
            import ctypes
            langid = ctypes.windll.kernel32.GetUserDefaultUILanguage()
            return "es" if (langid & 0x3FF) == 0x0A else "en"
        code = (locale.getlocale()[0] or "").lower()
        return "es" if code.startswith("es") else "en"
    except Exception:
        return "es"


def resolve(lang: str) -> str:
    """'auto' -> idioma de Windows; 'es'/'en' tal cual."""
    return lang if lang in ("es", "en") else detect()


def setup(lang: str = "auto") -> str:
    global _current
    _current = resolve(lang)
    return _current


def current() -> str:
    return _current


def _(text: str) -> str:
    if _current == "es":
        return text
    return EN.get(text, text)


# --------------------------------------------------------------------------- #
# Traducciones al inglés (generadas a partir de los textos marcados con _()).
# --------------------------------------------------------------------------- #
EN: dict[str, str] = {
    # --- Ventana principal ---
    "Descarga videos, audio o imágenes, en la calidad que quieras": "Download videos, audio or images, in the quality you want",
    "Historial": "History",
    "Ajustes": "Settings",
    "Pega un enlace (YouTube, Facebook, TikTok, X…) o escribe qué quieres buscar":
        "Paste a link (YouTube, Facebook, TikTok, X…) or type what you want to search for",
    "Pegar": "Paste",
    "Analizar": "Analyze",
    "Analizando…": "Analyzing…",
    "Analizando enlace…": "Analyzing link…",
    "Buscar": "Search",
    "Ningún enlace analizado": "No link analyzed yet",
    "Pega un enlace o escribe el nombre de un video para buscarlo.":
        "Paste a link or type the name of a video to search for it.",
    "Pega otro enlace o escribe el nombre de un video para buscarlo.":
        "Paste another link or type the name of a video to search for it.",
    "No se pudo analizar el enlace": "Couldn't analyze the link",
    "Elegir videos…": "Choose videos…",
    "Elegir videos ({n} de {total})…": "Choose videos ({n} of {total})…",
    "Editar título y artista…": "Edit title and artist…",
    "Título y artista ✓": "Title and artist ✓",
    "No se pudo obtener la lista de videos de este enlace.": "Couldn't get the list of videos from this link.",
    "Descargar como": "Download as",
    "Video": "Video",
    "Solo audio": "Audio only",
    "Imágenes": "Images",
    "Original del sitio": "As on the site",
    "original": "original",
    "1 imagen": "1 image",
    "{n} imágenes": "{n} images",
    "más de {n} imágenes": "more than {n} images",
    "se descargará la portada del video": "the video's thumbnail will be downloaded",
    "Formato": "Format",
    "Calidad": "Quality",
    "Mejor calidad": "Best quality",
    "Compatible con todo (hasta 1080p)": "Plays everywhere (up to 1080p)",
    "compatible": "compatible",
    "Sin pérdida": "Lossless",
    "Si el enlace es de una lista, descargarla completa": "If the link is a playlist, download all of it",
    "Subtítulos": "Subtitles",
    "Sin subtítulos": "No subtitles",
    "Español": "Spanish",
    "Inglés": "English",
    "Español e inglés": "Spanish and English",
    "Solo una parte:": "Only a part:",
    "desde": "from",
    "hasta": "to",
    "minutos:segundos, por ejemplo 1:20": "minutes:seconds, for example 1:20",
    "Revisa «Solo una parte»: escribe el inicio y el final como minutos:segundos "
    "(por ejemplo, desde 1:20 hasta 4:05).":
        "Check “Only a part”: type the start and end as minutes:seconds (for example, from 1:20 to 4:05).",
    "El video dura {time}; el inicio tiene que ser menor.": "The video is {time} long; the start must be earlier.",
    "«Solo una parte» funciona con un video a la vez, no con listas.":
        "“Only a part” works with one video at a time, not with playlists.",
    "Guardar en": "Save to",
    "Cambiar…": "Change…",
    "Abrir": "Open",
    "Elige la carpeta de descargas": "Choose the download folder",
    "Descargar": "Download",
    "Descargas": "Downloads",
    "Limpiar terminadas": "Clear finished",
    "Aún no hay descargas.": "No downloads yet.",
    "Duración {time}": "Duration {time}",
    "Lista de reproducción": "Playlist",
    "Lista de reproducción · {n} videos": "Playlist · {n} videos",
    "solo audio": "audio only",
    "hasta {quality}": "up to {quality}",
    "la mejor calidad disponible": "best available quality",
    "No hay videos marcados en la lista.": "No videos are selected in the playlist.",
    "Ya descargaste «{title}» el {date} ({kind}).": "You already downloaded “{title}” on {date} ({kind}).",
    "¿Quieres descargarlo de nuevo?": "Do you want to download it again?",
    "máx.": "max",
    "{n} videos": "{n} videos",
    "subtítulos": "subtitles",
    "Hay {n} descarga(s) en curso. ¿Cancelarlas y salir?": "{n} download(s) in progress. Cancel them and quit?",
    "No se pudo abrir:": "Couldn't open:",

    # --- Pie, actualizaciones, FFmpeg ---
    "FFmpeg NO encontrado (no se podrá convertir a MP3 ni unir audio y video)":
        "FFmpeg NOT found (can't convert to MP3 or merge audio and video)",
    "Deno no encontrado (pueden faltar formatos)": "Deno not found (some formats may be missing)",
    "Instalar FFmpeg": "Install FFmpeg",
    "Instalando FFmpeg…": "Installing FFmpeg…",
    "Se instalará FFmpeg con winget (Gyan.FFmpeg, unos 200 MB).":
        "FFmpeg will be installed with winget (Gyan.FFmpeg, about 200 MB).",
    "¿Continuar?": "Continue?",
    "FFmpeg quedó instalado.": "FFmpeg is installed.",
    "No se pudo instalar FFmpeg automáticamente.": "FFmpeg couldn't be installed automatically.",
    "Instálalo con: winget install Gyan.FFmpeg": "Install it with: winget install Gyan.FFmpeg",
    "Actualizar motores": "Update engines",
    "Buscando actualización…": "Checking for updates…",
    "Reiniciar para actualizar": "Restart to update",
    "Se descargaron versiones nuevas: {version}.": "New versions were downloaded: {version}.",
    "¿Reiniciar la app ahora para usarlo?": "Restart the app now to use it?",
    "Ya tienes las versiones más recientes de los motores ({version}).":
        "You already have the latest engine versions ({version}).",
    "No se pudieron actualizar los motores:": "Couldn't update the engines:",
    "Hay descargas en curso. Reinicia cuando terminen.": "Downloads are in progress. Restart when they finish.",
    "Nueva versión {version} disponible": "New version {version} available",
    "PyPI no tiene una versión compatible.": "PyPI has no compatible version.",
    "La descarga de {file} está dañada (SHA-256 no coincide).": "The download of {file} is corrupted (SHA-256 mismatch).",
    "La actualización descargada contiene un archivo sospechoso.": "The downloaded update contains a suspicious file.",
    "La actualización descargada no contiene yt-dlp.": "The downloaded update doesn't contain yt-dlp.",

    # --- Acerca de / bienvenida ---
    "Acerca de": "About",
    "Acerca de {app}": "About {app}",
    "Bienvenido a {app}": "Welcome to {app}",
    "Pega el enlace de un video o escribe lo que quieres buscar, elige si quieres el video o solo el audio, "
    "y presiona Descargar.":
        "Paste a video link or type what you want to search for, choose whether you want the video or just "
        "the audio, and press Download.",
    "Descarga solo contenido del que tengas los derechos o cuyo autor permita descargarlo. Descargar videos de "
    "YouTube puede ir contra sus condiciones de servicio; tú eres responsable del uso que le des.":
        "Only download content you own or that its author allows you to download. Downloading YouTube videos "
        "may violate its Terms of Service; you are responsible for how you use it.",
    "Creado por {author}": "Created by {author}",
    "Motores de descarga: yt-dlp {ytdlp} (videos) y gallery-dl {gdl} (imágenes)":
        "Download engines: yt-dlp {ytdlp} (videos) and gallery-dl {gdl} (images)",
    "Conversión: FFmpeg · Retos de YouTube: Deno · Interfaz: CustomTkinter":
        "Conversion: FFmpeg · YouTube challenges: Deno · Interface: CustomTkinter",
    "Software libre: el código de la app usa la licencia MIT y el programa completo se distribuye bajo la GPL. "
    "Los detalles están en THIRD_PARTY_NOTICES.md, junto al programa.":
        "Free software: the app's code uses the MIT license and the complete program is distributed under the "
        "GPL. Details are in THIRD_PARTY_NOTICES.md, next to the program.",
    "¿Abrir la página del proyecto?": "Open the project page?",

    # --- Filas de descarga ---
    "En cola…": "Queued…",
    "Conectando…": "Connecting…",
    "Procesando…": "Processing…",
    "Uniendo video y audio…": "Merging video and audio…",
    "Convirtiendo audio…": "Converting audio…",
    "Agregando portada…": "Adding cover art…",
    "Agregando datos…": "Adding metadata…",
    "Agregando subtítulos…": "Adding subtitles…",
    "Convirtiendo subtítulos…": "Converting subtitles…",
    "Guardando título y artista…": "Saving title and artist…",
    "El sitio rechazó la conexión, reintentando ({n}/{total})…": "The site refused the connection, retrying ({n}/{total})…",
    "Descargando video": "Downloading video",
    "Descargando audio": "Downloading audio",
    "Descargando imágenes": "Downloading images",
    "Buscando las imágenes…": "Looking for the images…",
    "El sitio pidió esperar un momento ({s} s)…": "The site asked to wait a moment ({s} s)…",
    "de {size}": "of {size}",
    "quedan {time}": "{time} left",
    "Completado": "Completed",
    "Completado · {n} archivos": "Completed · {n} files",
    "{n} con error": "{n} failed",
    "sin subtítulos (el sitio no los tiene en ese idioma o no los entregó)":
        "no subtitles (the site doesn't have them in that language or didn't provide them)",
    "Mostrar": "Show",
    "Abrir carpeta": "Open folder",
    "Error: {message}": "Error: {message}",
    "Reintentar": "Retry",
    "Copiar informe": "Copy report",
    "¡Copiado!": "Copied!",
    "Cancelar": "Cancel",
    "Cancelando…": "Cancelling…",
    "Cancelado": "Cancelled",
    "Quitar": "Remove",
    "Pausar": "Pause",
    "Pausando…": "Pausing…",
    "Pausado · lo descargado se conserva": "Paused · what's downloaded is kept",
    "Reanudar": "Resume",
    "La descarga falló.": "The download failed.",

    # --- Errores ---
    "El video es privado.": "The video is private.",
    "El video tiene restricción de edad (requiere iniciar sesión).": "The video is age-restricted (sign-in required).",
    "El video no está disponible.": "The video isn't available.",
    "El enlace no es válido.": "The link isn't valid.",
    "Este enlace no tiene video: puede ser una foto o un carrusel de imágenes (para bajarlas elige «Imágenes»). "
    "Si sí es un video, el sitio puede estar pidiendo iniciar sesión: en Ajustes elige el navegador donde tienes "
    "tu sesión abierta y vuelve a intentarlo.":
        "This link has no video: it may be a photo or an image carousel (to get them, choose “Images”). "
        "If it is a video, the site may require signing in: in Settings, choose the browser where you're signed "
        "in and try again.",
    "La publicación no existe o fue borrada.": "The post doesn't exist or was deleted.",
    "CarryIt no sabe sacar imágenes de este sitio.": "CarryIt can't get images from this site.",
    "No se encontraron imágenes en este enlace.": "No images were found at this link.",
    "Este video no tiene portada para descargar.": "This video has no thumbnail to download.",
    "No se pudo leer la sesión del navegador. Ciérralo por completo y reintenta, o elige otro navegador en "
    "Ajustes (Firefox es el más compatible).":
        "Couldn't read the browser session. Close the browser completely and retry, or choose another browser "
        "in Settings (Firefox is the most compatible).",
    "Este sitio pide iniciar sesión para ver este contenido. En Ajustes elige el navegador donde tienes tu "
    "sesión abierta y vuelve a intentarlo.":
        "This site requires signing in to see this content. In Settings, choose the browser where you're signed "
        "in and try again.",
    "No hay conexión con el sitio. Revisa tu internet.": "Can't reach the site. Check your internet connection.",
    "No se encontró FFmpeg; es necesario para unir video/audio y convertir a MP3.":
        "FFmpeg wasn't found; it's needed to merge video/audio and convert to MP3.",
    "El sitio rechazó la descarga (error 403) varias veces. Presiona Reintentar en unos minutos o usa "
    "«Actualizar motores».":
        "The site refused the download (error 403) several times. Press Retry in a few minutes or use "
        "“Update engines”.",
    "El sitio está limitando las descargas (demasiadas solicitudes). Espera unos minutos.":
        "The site is limiting downloads (too many requests). Wait a few minutes.",
    "La calidad o el formato elegido no está disponible para este video.":
        "The chosen quality or format isn't available for this video.",
    "El video es exclusivo para miembros del canal.": "The video is for channel members only.",
    "El video es un estreno o transmisión que aún no empieza.": "The video is a premiere or stream that hasn't started yet.",
    "El video está bloqueado en tu país o por derechos de autor.": "The video is blocked in your country or for copyright.",
    "Se perdió la conexión con el sitio. Revisa tu internet y presiona Reintentar.":
        "The connection to the site was lost. Check your internet and press Retry.",
    "No hay espacio suficiente en el disco.": "There isn't enough disk space.",
    "No hay permiso para guardar en la carpeta elegida.": "There's no permission to save in the chosen folder.",
    "Error de descarga:": "Download error:",

    # --- Elegir videos de una lista ---
    "Elegir videos": "Choose videos",
    "Buscar en la lista…": "Search the playlist…",
    "Todos": "All",
    "Ninguno": "None",
    "Seleccionados: {n} de {total}": "Selected: {n} of {total}",
    "Aceptar": "OK",

    # --- Búsqueda ---
    "¿Qué quieres buscar?": "What do you want to search for?",
    "Buscando…": "Searching…",
    "No se encontraron videos. Prueba con otras palabras.": "No videos found. Try other words.",
    "Elegir": "Choose",
    "No se pudo buscar:": "Couldn't search:",

    # --- Historial ---
    "Historial de descargas": "Download history",
    "Buscar en el historial…": "Search history…",
    "Borrar historial": "Clear history",
    "Cerrar": "Close",
    "1 descarga guardada": "1 saved download",
    "{n} descargas guardadas": "{n} saved downloads",
    "Aún no hay descargas en el historial.": "There are no downloads in the history yet.",
    "Nada coincide con la búsqueda.": "Nothing matches the search.",
    "el archivo ya no está en su carpeta": "the file is no longer in its folder",
    "Copiar enlace": "Copy link",
    "¿Borrar todo el historial?": "Clear the whole history?",
    "Los archivos descargados no se borran.": "Downloaded files aren't deleted.",

    # --- Título y artista ---
    "Título y artista": "Title and artist",
    "Así se verá en tu celular, el estéreo del carro o tu reproductor de música.":
        "This is how it will look on your phone, car stereo or music player.",
    "Título": "Title",
    "Artista": "Artist",
    "Usar los originales": "Use the originals",
    "Escribe un título.": "Type a title.",

    # --- Ajustes ---
    "Apariencia": "Appearance",
    "Tema": "Theme",
    "Oscuro": "Dark",
    "Claro": "Light",
    "Igual que Windows": "Same as Windows",
    "Idioma": "Language",
    "Automático (idioma de Windows)": "Automatic (Windows language)",
    "Descargas al mismo tiempo": "Simultaneous downloads",
    "Nombre de los archivos": "File names",
    "Título - Canal": "Title - Channel",
    "Canal - Título": "Channel - Title",
    "Guardar videos y audios en carpetas separadas («Videos» y «Audio»)":
        "Save videos and audio in separate folders (“Videos” and “Audio”)",
    "Velocidad máxima": "Maximum speed",
    "Sin límite": "No limit",
    "Guardar los subtítulos también como archivo .srt aparte": "Also save subtitles as a separate .srt file",
    "Sitios que piden iniciar sesión": "Sites that require signing in",
    "Para Instagram, Vimeo, Reddit y otros: usa la sesión que ya tienes abierta en tu navegador. Firefox es el "
    "más compatible.":
        "For Instagram, Vimeo, Reddit and others: use the session you already have open in your browser. "
        "Firefox is the most compatible.",
    "Navegador": "Browser",
    "No usar": "Don't use",
    "Comodidad": "Convenience",
    "Detectar enlaces copiados (YouTube, Facebook, TikTok…)": "Detect copied links (YouTube, Facebook, TikTok…)",
    "Avisar cuando termine una descarga (si la ventana no está al frente)":
        "Notify me when a download finishes (if the window isn't in front)",
    "Buscar actualizaciones automáticamente": "Check for updates automatically",
    "Ayuda": "Help",
    "Copiar informe de diagnóstico": "Copy diagnostic report",
    "Guardar": "Save",
    "Informe copiado.": "Report copied.",
    "Pégalo (Ctrl+V) en un mensaje para quien te ayuda o al reportar el problema.":
        "Paste it (Ctrl+V) in a message to whoever is helping you, or when reporting the problem.",
    "El idioma cambiará al reiniciar CarryIt.": "The language will change when CarryIt restarts.",
    "¿Reiniciar ahora?": "Restart now?",

    # --- Informe de diagnóstico ---
    "Informe de {app}": "{app} report",
    "Fecha": "Date",
    "instalado": "installed",
    "código fuente": "source code",
    "sí": "yes",
    "NO": "NO",
    "Enlace": "Link",
    "Descarga": "Download",
    "lista": "playlist",
    "Error": "Error",
    "Registro (últimas líneas)": "Log (last lines)",
    "(sin registro)": "(no log)",
    "Repórtalo en:": "Report it at:",
}
