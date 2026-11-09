import atexit
import ctypes
from ctypes import wintypes
import os
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.request
import webview

# Pre-set AppUserModelID so Windows shell groups and identifies Words
APP_ID = "com.words.assistant"
try:
    if hasattr(ctypes.windll.shell32, "SetCurrentProcessExplicitAppUserModelID"):
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID.argtypes = [wintypes.LPCWSTR]
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID.restype = wintypes.HRESULT
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_ID)
except Exception as e:
    print(f"[Init] AppUserModelID notice: {e}")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
UI_HTML = os.path.join(BASE_DIR, "ui", "index.html")
ENGINE_SCRIPT = os.path.join(BASE_DIR, "engine", "server.mjs")
ICON_ICO = os.path.join(BASE_DIR, "Assets", "Icons", "words_icon.ico")

# Pre-configure pywebview winforms icon state BEFORE creating window
try:
    import webview.platforms.winforms as winforms_platform
    winforms_platform._state['icon'] = ICON_ICO
except Exception:
    winforms_platform = None

webview._state['icon'] = ICON_ICO

user32 = ctypes.windll.user32
shell32 = ctypes.windll.shell32
kernel32 = ctypes.windll.kernel32

WM_SETICON = 0x0080
ICON_SMALL = 0
ICON_BIG = 1
IMAGE_ICON = 1
LR_LOADFROMFILE = 0x00000010
GCLP_HICON = -14
GCLP_HICONSM = -34

# Setup safe 64-bit/32-bit Win32 function signatures
try:
    user32.LoadImageW.argtypes = [
        wintypes.HINSTANCE, wintypes.LPCWSTR, wintypes.UINT,
        ctypes.c_int, ctypes.c_int, wintypes.UINT
    ]
    user32.LoadImageW.restype = wintypes.HANDLE

    user32.SendMessageW.argtypes = [
        wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM
    ]
    user32.SendMessageW.restype = wintypes.LRESULT

    if hasattr(kernel32, "GetConsoleWindow"):
        kernel32.GetConsoleWindow.restype = wintypes.HWND
except Exception as e:
    print(f"[Win32] Signature initialization notice: {e}")

# Windows Property Store definitions for Taskbar AppID and Relaunch Icon
class PROPERTYKEY(ctypes.Structure):
    _fields_ = [
        ('fmtid_Data1', ctypes.c_ulong),
        ('fmtid_Data2', ctypes.c_ushort),
        ('fmtid_Data3', ctypes.c_ushort),
        ('fmtid_Data4', ctypes.c_ubyte * 8),
        ('pid', ctypes.c_ulong)
    ]

class PROPVARIANT(ctypes.Structure):
    _fields_ = [
        ('vt', wintypes.USHORT),
        ('wReserved1', wintypes.USHORT),
        ('wReserved2', wintypes.USHORT),
        ('wReserved3', wintypes.USHORT),
        ('pwszVal', wintypes.LPWSTR),
        ('padding', ctypes.c_ulonglong)
    ]

PKEY_AppUserModel_ID = PROPERTYKEY(
    0x9F4C2855, 0x9F79, 0x4B39,
    (ctypes.c_ubyte * 8)(0xA8, 0xD0, 0xE1, 0xD4, 0x2D, 0xE1, 0xD5, 0xF3),
    5
)
PKEY_AppUserModel_RelaunchIconResource = PROPERTYKEY(
    0x9F4C2855, 0x9F79, 0x4B39,
    (ctypes.c_ubyte * 8)(0xA8, 0xD0, 0xE1, 0xD4, 0x2D, 0xE1, 0xD5, 0xF3),
    3
)
IID_IPropertyStore = PROPERTYKEY(
    0x886D8EEB, 0x8CF2, 0x4446,
    (ctypes.c_ubyte * 8)(0x8D, 0x02, 0xCD, 0xBA, 0x1D, 0xBD, 0xCF, 0x99),
    0
)

class IPropertyStoreVtbl(ctypes.Structure):
    _fields_ = [
        ('QueryInterface', ctypes.c_void_p),
        ('AddRef', ctypes.c_void_p),
        ('Release', ctypes.WINFUNCTYPE(ctypes.c_ulong, ctypes.c_void_p)),
        ('GetCount', ctypes.c_void_p),
        ('GetAt', ctypes.c_void_p),
        ('GetValue', ctypes.c_void_p),
        ('SetValue', ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p, ctypes.POINTER(PROPERTYKEY), ctypes.POINTER(PROPVARIANT))),
        ('Commit', ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p)),
    ]

class IPropertyStore(ctypes.Structure):
    _fields_ = [('lpVtbl', ctypes.POINTER(IPropertyStoreVtbl))]

SHGetPropertyStoreForWindow = getattr(shell32, 'SHGetPropertyStoreForWindow', None)
if SHGetPropertyStoreForWindow:
    SHGetPropertyStoreForWindow.argtypes = [
        wintypes.HWND,
        ctypes.POINTER(PROPERTYKEY),
        ctypes.POINTER(ctypes.POINTER(IPropertyStore))
    ]
    SHGetPropertyStoreForWindow.restype = ctypes.c_long

engine_process = None
main_window = None
_cleaned_up = False


def set_taskbar_properties(hwnd, app_id, icon_path):
    """Sets AppUserModelID and RelaunchIconResource directly onto the window for the Windows Taskbar."""
    if not SHGetPropertyStoreForWindow or not hwnd:
        return
    try:
        store = ctypes.POINTER(IPropertyStore)()
        hr = SHGetPropertyStoreForWindow(hwnd, ctypes.byref(IID_IPropertyStore), ctypes.byref(store))
        if hr == 0 and store:
            vtbl = store.contents.lpVtbl.contents
            # Set AppUserModelID
            pv_id = PROPVARIANT(vt=31, pwszVal=app_id)
            vtbl.SetValue(store, ctypes.byref(PKEY_AppUserModel_ID), ctypes.byref(pv_id))
            # Set RelaunchIconResource
            pv_icon = PROPVARIANT(vt=31, pwszVal=f"{icon_path},0")
            vtbl.SetValue(store, ctypes.byref(PKEY_AppUserModel_RelaunchIconResource), ctypes.byref(pv_icon))
            vtbl.Commit(store)
            vtbl.Release(store)
    except Exception as e:
        print("[Taskbar] PropertyStore notice:", e)


def apply_win32_icons(hwnd):
    """Applies large and small icons to window handle and window class."""
    if not os.path.exists(ICON_ICO) or not hwnd:
        return
    try:
        hicon = user32.LoadImageW(None, ICON_ICO, IMAGE_ICON, 0, 0, LR_LOADFROMFILE)
        if hicon:
            user32.SendMessageW(hwnd, WM_SETICON, ICON_BIG, hicon)
            user32.SendMessageW(hwnd, WM_SETICON, ICON_SMALL, hicon)

            # SetClassLongPtr for x64 / SetClassLong for x86
            try:
                set_class_long_ptr = getattr(user32, 'SetClassLongPtrW', None)
                if set_class_long_ptr:
                    set_class_long_ptr.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_void_p]
                    set_class_long_ptr.restype = ctypes.c_void_p
                    set_class_long_ptr(hwnd, GCLP_HICON, hicon)
                    set_class_long_ptr(hwnd, GCLP_HICONSM, hicon)
                else:
                    user32.SetClassLongW(hwnd, GCLP_HICON, hicon)
                    user32.SetClassLongW(hwnd, GCLP_HICONSM, hicon)
            except Exception:
                pass

        if hasattr(kernel32, "GetConsoleWindow"):
            console_hwnd = kernel32.GetConsoleWindow()
            if console_hwnd and hicon:
                user32.SendMessageW(console_hwnd, WM_SETICON, ICON_BIG, hicon)
                user32.SendMessageW(console_hwnd, WM_SETICON, ICON_SMALL, hicon)
    except Exception as e:
        print("[Icon] Win32 icon notice:", e)


def is_engine_healthy():
    """Checks if the local engine is responsive on port 8787."""
    try:
        req = urllib.request.Request("http://127.0.0.1:8787/health", headers={"User-Agent": "Words-Desktop"})
        with urllib.request.urlopen(req, timeout=1.0) as resp:
            return resp.status == 200
    except Exception:
        return False


def ensure_engine_running():
    """Checks if the local engine service is running on 127.0.0.1:8787; if not, launches it."""
    if is_engine_healthy():
        print("[Launcher] Engine is already running and responsive.")
        return

    global engine_process
    print("[Launcher] Starting engine service in background...")
    try:
        engine_process = subprocess.Popen(
            ["node", ENGINE_SCRIPT],
            cwd=os.path.join(BASE_DIR, "engine"),
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
        )

        # Wait up to 5 seconds for engine to become healthy
        start_wait = time.time()
        while time.time() - start_wait < 5.0:
            if is_engine_healthy():
                print("[Launcher] Engine service started successfully.")
                return
            time.sleep(0.3)
    except Exception as e:
        print(f"[Launcher] Error starting engine process: {e}")


def cleanup_engine():
    """Gracefully shuts down the background engine service and terminates process trees."""
    global _cleaned_up, engine_process
    if _cleaned_up:
        return
    _cleaned_up = True

    print("[App] Shutting down Words background services...")
    # 1. Attempt graceful HTTP shutdown
    try:
        req = urllib.request.Request("http://127.0.0.1:8787/shutdown", data=b'{}', headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=1.5):
            pass
    except Exception:
        pass

    # 2. Terminate spawned engine process tree if still active
    if engine_process:
        try:
            if engine_process.poll() is None:
                if os.name == 'nt':
                    subprocess.run(
                        f"taskkill /pid {engine_process.pid} /t /f",
                        shell=True,
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL
                    )
                else:
                    engine_process.terminate()
        except Exception:
            pass
        engine_process = None


atexit.register(cleanup_engine)


def handle_signal(sig, frame):
    cleanup_engine()
    sys.exit(0)


signal.signal(signal.SIGINT, handle_signal)
signal.signal(signal.SIGTERM, handle_signal)


class JsApi:
    def __init__(self, window_ref):
        self._window = window_ref


def on_app_ready():
    """Called immediately once the webview UI is ready."""
    time.sleep(0.3)
    if main_window and hasattr(main_window, 'native') and main_window.native:
        try:
            hwnd = None
            if hasattr(main_window.native, 'Handle'):
                hwnd = main_window.native.Handle.ToInt64()
            elif isinstance(main_window.native, int):
                hwnd = main_window.native

            if hwnd:
                set_taskbar_properties(hwnd, APP_ID, ICON_ICO)
                apply_win32_icons(hwnd)
        except Exception as e:
            print("[Icon] Notice applying icons on ready:", e)


def on_closing():
    """Triggered when the window is closing."""
    cleanup_engine()


def main():
    global main_window
    ensure_engine_running()

    api = JsApi(None)
    main_window = webview.create_window(
        title="Words",
        url=f"file:///{UI_HTML.replace('\\', '/')}",
        js_api=api,
        width=880,
        height=540,
        resizable=True,
        on_top=False,
        background_color='#0f1115'
    )
    api._window = main_window
    main_window.events.closing += on_closing

    print("[App] Words is ready. Use the app directly.")
    webview.start(on_app_ready, icon=ICON_ICO, gui='edgechromium', debug=False)


if __name__ == "__main__":
    try:
        main()
    finally:
        cleanup_engine()
