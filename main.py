"""Punto de entrada: python main.py  (o pythonw main.py para no mostrar consola).

Diagnóstico sin interfaz:  main.py --selftest URL CARPETA   (escribe CARPETA\\selftest.json)
"""
import logging
import os
import sys

# Con pythonw o el .exe no hay consola: evita errores de librerías que escriben en stdout/stderr.
if sys.stdout is None:
    sys.stdout = open(os.devnull, "w", encoding="utf-8")
if sys.stderr is None:
    sys.stderr = open(os.devnull, "w", encoding="utf-8")

_mutex = None
if os.name == "nt":
    try:
        import ctypes
        # Ícono propio en la barra de tareas en lugar del de Python.
        from carryit import APP_MUTEX, APP_USER_MODEL_ID
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_USER_MODEL_ID)
        # El instalador revisa este mutex para pedir que se cierre la app antes de actualizarla.
        _mutex = ctypes.windll.kernel32.CreateMutexW(None, False, APP_MUTEX)
    except Exception:
        pass

from carryit import i18n, updater  # noqa: E402
from carryit.settings import Settings, data_dir  # noqa: E402

# Idioma de la interfaz: el elegido en Ajustes (o el de Windows). «--lang en» lo fuerza (pruebas).
_lang = sys.argv[sys.argv.index("--lang") + 1] if "--lang" in sys.argv[:-1] else Settings.load().language
i18n.setup(_lang)

logging.basicConfig(
    filename=os.path.join(data_dir(), "app.log"),
    level=logging.WARNING,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    encoding="utf-8",
)

# Usa el yt-dlp actualizado (si hay uno más nuevo que el incluido). Si no carga, vuelve al incluido.
try:
    updater.activate()
    import yt_dlp  # noqa: F401
except Exception:
    logging.exception("El yt-dlp actualizado no cargó; se usa el incluido")
    updater.deactivate(remove=True)
    import yt_dlp  # noqa: F401


def selftest(url: str, out: str) -> bool:
    import json
    import threading
    from carryit import core

    results = {"yt_dlp": core.ytdlp_version(), "ffmpeg": core.find_ffmpeg(), "deno": core.find_deno()}

    # Motor de imágenes: los extractores de gallery-dl se cargan por nombre, así que hay que comprobar
    # que el empaquetado los haya incluido (sin internet).
    try:
        from carryit import images
        results["gallery_dl"] = images.version()
        sample = ("https://bsky.app/profile/bsky.app/post/3myx7vphq3s2j", "https://www.pinterest.com/pin/1234567/",
                  "https://imgur.com/gallery/abc123", "https://www.instagram.com/p/ABC123/")
        missing = [u for u in sample if not images.supported(u)]
        results["images_engine"] = "ok" if not missing else f"faltan extractores: {missing}"
    except Exception as exc:
        results["images_engine"] = f"error: {exc!r}"

    # Inicio de sesión en sitios: necesita el cliente WebSocket y sqlite3 empaquetados (Edge es opcional aquí).
    try:
        import sqlite3  # noqa: F401
        import websockets.sync.client  # noqa: F401
        from carryit import sessions
        results["login_browser"] = sessions.find_browser()
        results["sessions"] = "ok" if sessions.site_for_url("https://www.instagram.com/p/x/") == "instagram" \
            else "error: sitios"
    except Exception as exc:
        results["sessions"] = f"error: {exc!r}"

    # La interfaz se crea y se cierra sola (comprueba que temas, fuentes e íconos vengan incluidos).
    try:
        from carryit import gui
        gui.App._show_welcome = lambda self: None
        gui.close_splash()
        app = gui.App()
        app.after(1500, app.destroy)
        app.mainloop()
        results["gui"] = "ok"
    except Exception as exc:
        results["gui"] = f"error: {exc!r}"

    for name, opts in {
        "audio_mp3": core.DownloadOptions(url=url, output_dir=out, mode="audio"),
        "video_mp4": core.DownloadOptions(url=url, output_dir=out, mode="video", height=360),
        "image_jpg": core.DownloadOptions(url="https://commons.wikimedia.org/wiki/File:Cat_November_2010-1a.jpg",
                                          output_dir=out, mode="images"),
    }.items():
        done, last = threading.Event(), {}

        def on_event(ev, last=last, done=done):
            if ev["type"] in ("done", "error", "cancelled"):
                last.update(ev)
                done.set()

        if opts.mode == "images":
            from carryit import images
            images.ImageTask(opts, on_event).start()
        else:
            core.DownloadTask(opts, on_event).start()
        done.wait(600)
        results[name] = last
    ok = (results.get("gui") == "ok" and bool(results["ffmpeg"]) and results.get("images_engine") == "ok"
          and results.get("sessions") == "ok"
          and all(results[k].get("type") == "done" for k in ("audio_mp3", "video_mp4", "image_jpg")))
    results["ok"] = ok
    with open(os.path.join(out, "selftest.json"), "w", encoding="utf-8") as fh:
        json.dump(results, fh, indent=2, ensure_ascii=False)
    return ok


if __name__ == "__main__":
    if len(sys.argv) >= 4 and sys.argv[1] == "--selftest":
        sys.exit(0 if selftest(sys.argv[2], sys.argv[3]) else 1)
    else:
        from carryit.gui import run
        run()
