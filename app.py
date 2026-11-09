import ctypes
from ctypes import wintypes
import logging
import os
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
import webview

# Configure file logging for pythonw.exe diagnostic capture
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LOG_FILE = os.path.join(BASE_DIR, "words.log")
logging.basicConfig(
    filename=LOG_FILE,
    filemode="w",
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)

APP_ID = "com.words.assistant"
UI_HTML = os.path.join(BASE_DIR, "ui", "index.html")
ENGINE_SCRIPT = os.path.join(BASE_DIR, "engine", "server.mjs")
ICON_ICO = os.path.join(BASE_DIR, "Assets", "Icons", "words_icon.ico")
ENGINE_HEALTH_URL = "http://127.0.0.1:8787/health"
ENGINE_SHUTDOWN_URL = "http://127.0.0.1:8787/shutdown"

# Win32 DLL bindings
user32 = ctypes.windll.user32
shell32 = ctypes.windll.shell32
kernel32 = ctypes.windll.kernel32
ole32 = ctypes.windll.ole32

# Set Process AppUserModelID with exact types
if hasattr(shell32, 'SetCurrentProcessExplicitAppUserModelID'):
    shell32.SetCurrentProcessExplicitAppUserModelID.argtypes = [wintypes.LPCWSTR]
    shell32.SetCurrentProcessExplicitAppUserModelID.restype = wintypes.HRESULT
    try:
        hr = shell32.SetCurrentProcessExplicitAppUserModelID(APP_ID)
        if hr != 0:
            logging.warning("SetCurrentProcessExplicitAppUserModelID failed with hr=0x%08X", hr)
    except Exception as e:
        logging.warning("SetCurrentProcessExplicitAppUserModelID exception: %s", e)

# Win32 Constants
WM_SETICON = 0x0080
ICON_SMALL = 0
ICON_BIG = 1
IMAGE_ICON = 1
LR_LOADFROMFILE = 0x00000010
GCLP_HICON = -14
GCLP_HICONSM = -34
IS_64BIT = ctypes.sizeof(ctypes.c_void_p) == 8

# Setup type signatures for Win32 APIs (64-bit and 32-bit safe)
try:
    user32.LoadImageW.argtypes = [wintypes.HINSTANCE, wintypes.LPCWSTR, wintypes.UINT, ctypes.c_int, ctypes.c_int, wintypes.UINT]
    user32.LoadImageW.restype = wintypes.HANDLE

    user32.SendMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    user32.SendMessageW.restype = wintypes.LPARAM

    if hasattr(kernel32, "GetConsoleWindow"):
        kernel32.GetConsoleWindow.argtypes = []
        kernel32.GetConsoleWindow.restype = wintypes.HWND

    if IS_64BIT:
        SetClassLong = getattr(user32, 'SetClassLongPtrW', None)
        if SetClassLong:
            SetClassLong.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_ssize_t]
            SetClassLong.restype = ctypes.c_ssize_t
    else:
        SetClassLong = getattr(user32, 'SetClassLongW', None)
        if SetClassLong:
            SetClassLong.argtypes = [wintypes.HWND, ctypes.c_int, wintypes.LONG]
            SetClassLong.restype = wintypes.DWORD
except Exception as e:
    logging.warning("Win32 signature initialization notice: %s", e)

# Win32 COM & PropertyStore definitions
class GUID(ctypes.Structure):
    _fields_ = [
        ('Data1', ctypes.c_ulong),
        ('Data2', ctypes.c_ushort),
        ('Data3', ctypes.c_ushort),
        ('Data4', ctypes.c_ubyte * 8)
    ]

class PROPERTYKEY(ctypes.Structure):
    _fields_ = [
        ('fmtid', GUID),
        ('pid', ctypes.c_ulong)
    ]

class PROPVARIANT(ctypes.Structure):
    _fields_ = [
        ('vt', wintypes.USHORT),
        ('wReserved1', wintypes.USHORT),
        ('wReserved2', wintypes.USHORT),
        ('wReserved3', wintypes.USHORT),
        ('pwszVal', wintypes.LPWSTR),
        ('padding', ctypes.c_size_t)
    ]

PKEY_AppUserModel_ID = PROPERTYKEY(
    GUID(0x9F4C2855, 0x9F79, 0x4B39, (ctypes.c_ubyte * 8)(0xA8, 0xD0, 0xE1, 0xD4, 0x2D, 0xE1, 0xD5, 0xF3)),
    5
)
PKEY_AppUserModel_RelaunchIconResource = PROPERTYKEY(
    GUID(0x9F4C2855, 0x9F79, 0x4B39, (ctypes.c_ubyte * 8)(0xA8, 0xD0, 0xE1, 0xD4, 0x2D, 0xE1, 0xD5, 0xF3)),
    3
)
IID_IPropertyStore = GUID(
    0x886D8EEB, 0x8CF2, 0x4446,
    (ctypes.c_ubyte * 8)(0x8D, 0x02, 0xCD, 0xBA, 0x1D, 0xBD, 0xCF, 0x99)
)

class IPropertyStoreVtbl(ctypes.Structure):
    pass
class IPropertyStore(ctypes.Structure):
    _fields_ = [('lpVtbl', ctypes.POINTER(IPropertyStoreVtbl))]
IPropertyStoreVtbl._fields_ = [
    ('QueryInterface', ctypes.c_void_p),
    ('AddRef', ctypes.c_void_p),
    ('Release', ctypes.WINFUNCTYPE(ctypes.c_ulong, ctypes.c_void_p)),
    ('GetCount', ctypes.c_void_p),
    ('GetAt', ctypes.c_void_p),
    ('GetValue', ctypes.c_void_p),
    ('SetValue', ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p, ctypes.POINTER(PROPERTYKEY), ctypes.POINTER(PROPVARIANT))),
    ('Commit', ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p)),
]

SHGetPropertyStoreForWindow = getattr(shell32, 'SHGetPropertyStoreForWindow', None)
if SHGetPropertyStoreForWindow:
    SHGetPropertyStoreForWindow.argtypes = [
        wintypes.HWND,
        ctypes.POINTER(GUID),
        ctypes.POINTER(ctypes.POINTER(IPropertyStore))
    ]
    SHGetPropertyStoreForWindow.restype = wintypes.HRESULT

# Windows Job Object for bulletproof child process cleanup
JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x2000
JOBOBJECT_EXTENDED_LIMIT_INFORMATION = 9

class IO_COUNTERS(ctypes.Structure):
    _fields_ = [
        ('ReadOperationCount', ctypes.c_ulonglong),
        ('WriteOperationCount', ctypes.c_ulonglong),
        ('OtherOperationCount', ctypes.c_ulonglong),
        ('ReadTransferCount', ctypes.c_ulonglong),
        ('WriteTransferCount', ctypes.c_ulonglong),
        ('OtherTransferCount', ctypes.c_ulonglong),
    ]

class JOBOBJECT_BASIC_LIMIT_INFORMATION(ctypes.Structure):
    _fields_ = [
        ('PerProcessUserTimeLimit', ctypes.c_int64),
        ('PerJobUserTimeLimit', ctypes.c_int64),
        ('LimitFlags', wintypes.DWORD),
        ('MinimumWorkingSetSize', ctypes.c_size_t),
        ('MaximumWorkingSetSize', ctypes.c_size_t),
        ('ActiveProcessLimit', wintypes.DWORD),
        ('Affinity', ctypes.c_size_t),
        ('PriorityClass', wintypes.DWORD),
        ('SchedulingClass', wintypes.DWORD),
    ]

class JOBOBJECT_EXTENDED_LIMIT_INFORMATION_STRUCT(ctypes.Structure):
    _fields_ = [
        ('BasicLimitInformation', JOBOBJECT_BASIC_LIMIT_INFORMATION),
        ('IoCounters', IO_COUNTERS),
        ('ProcessMemoryLimit', ctypes.c_size_t),
        ('JobMemoryLimit', ctypes.c_size_t),
        ('PeakProcessMemoryLimit', ctypes.c_size_t),
        ('PeakJobMemoryLimit', ctypes.c_size_t),
    ]

job_handle = None

def setup_job_object():
    """Creates a Windows Job Object that automatically terminates child processes if the parent exits."""
    global job_handle
    try:
        kernel32.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
        kernel32.CreateJobObjectW.restype = wintypes.HANDLE
        job_handle = kernel32.CreateJobObjectW(None, None)
        if not job_handle:
            return
        info = JOBOBJECT_EXTENDED_LIMIT_INFORMATION_STRUCT()
        info.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        kernel32.SetInformationJobObject(
            job_handle,
            JOBOBJECT_EXTENDED_LIMIT_INFORMATION,
            ctypes.byref(info),
            ctypes.sizeof(info)
        )
    except Exception as e:
        logging.warning("Could not setup Job Object: %s", e)

engine_process = None
main_window = None

def set_taskbar_properties(hwnd, app_id, icon_path):
    """Sets AppUserModelID and RelaunchIconResource on the window for the Windows Taskbar."""
    if not SHGetPropertyStoreForWindow or not hwnd:
        return

    ole32.CoInitialize(None)
    store = None
    try:
        store = ctypes.POINTER(IPropertyStore)()
        hr = SHGetPropertyStoreForWindow(hwnd, ctypes.byref(IID_IPropertyStore), ctypes.byref(store))
        if hr == 0 and store:
            vtbl = store.contents.lpVtbl.contents
            pv_id = PROPVARIANT(vt=31, pwszVal=app_id)
            vtbl.SetValue(store, ctypes.byref(PKEY_AppUserModel_ID), ctypes.byref(pv_id))

            icon_res = f"{icon_path},0"
            pv_icon = PROPVARIANT(vt=31, pwszVal=icon_res)
            vtbl.SetValue(store, ctypes.byref(PKEY_AppUserModel_RelaunchIconResource), ctypes.byref(pv_icon))
            vtbl.Commit(store)
    except Exception as e:
        logging.error("PropertyStore error: %s", e)
    finally:
        if store:
            try:
                store.contents.lpVtbl.contents.Release(store)
            except Exception:
                pass
        ole32.CoUninitialize()

def apply_win32_icons(hwnd):
    """Applies large and small icons to the window handle and window class."""
    if not os.path.exists(ICON_ICO) or not hwnd:
        return
    try:
        hicon = user32.LoadImageW(None, ICON_ICO, IMAGE_ICON, 0, 0, LR_LOADFROMFILE)
        if hicon:
            user32.SendMessageW(hwnd, WM_SETICON, ICON_BIG, hicon)
            user32.SendMessageW(hwnd, WM_SETICON, ICON_SMALL, hicon)
            if SetClassLong:
                SetClassLong(hwnd, GCLP_HICON, hicon)
                SetClassLong(hwnd, GCLP_HICONSM, hicon)

        console_hwnd = kernel32.GetConsoleWindow() if hasattr(kernel32, "GetConsoleWindow") else None
        if console_hwnd and hicon:
            user32.SendMessageW(console_hwnd, WM_SETICON, ICON_BIG, hicon)
            user32.SendMessageW(console_hwnd, WM_SETICON, ICON_SMALL, hicon)
    except Exception as e:
        logging.error("Win32 icon error: %s", e)

def is_engine_healthy(timeout=1.5):
    """Returns True if the engine health check returns HTTP 200."""
    try:
        req = urllib.request.Request(ENGINE_HEALTH_URL, headers={"User-Agent": "Words-Desktop"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status == 200
    except Exception:
        return False

def ensure_engine_running():
    """Checks if the local engine service is running on 127.0.0.1:8787; if not, launches it and awaits readiness."""
    global engine_process
    if is_engine_healthy(timeout=1.5):
        logging.info("Engine service is already running on port 8787.")
        return

    node_bin = shutil.which("node")
    if not node_bin:
        msg = "Node.js was not found in PATH.\nPlease install Node.js (v18+) to run the Words engine."
        logging.critical(msg)
        user32.MessageBoxW(None, msg, "Words - Missing Prerequisite", 0x00000010)
        sys.exit(1)

    if not os.path.exists(ENGINE_SCRIPT):
        msg = f"Engine script missing at {ENGINE_SCRIPT}"
        logging.critical(msg)
        user32.MessageBoxW(None, msg, "Words - Missing Engine", 0x00000010)
        sys.exit(1)

    logging.info("Launching engine service via Node.js: %s", ENGINE_SCRIPT)
    setup_job_object()

    engine_process = subprocess.Popen(
        [node_bin, ENGINE_SCRIPT],
        cwd=os.path.join(BASE_DIR, "engine"),
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
    )

    if job_handle and engine_process:
        try:
            kernel32.AssignProcessToJobObject(job_handle, engine_process._handle)
        except Exception as e:
            logging.warning("Could not assign process to Job Object: %s", e)

    # Await engine readiness before showing UI (max 10 seconds)
    start_time = time.time()
    while time.time() - start_time < 10.0:
        if engine_process.poll() is not None:
            logging.error("Engine process terminated unexpectedly with code %s", engine_process.returncode)
            break
        if is_engine_healthy(timeout=0.6):
            logging.info("Engine service ready in %.2fs", time.time() - start_time)
            return
        time.sleep(0.3)

    logging.warning("Engine took longer than 10s to respond; webview will proceed.")

def shutdown_engine():
    """Gracefully shuts down the background engine service and any spawned LLM processes."""
    global engine_process
    logging.info("Initiating engine shutdown...")

    # 1. Trigger graceful HTTP shutdown endpoint
    try:
        req = urllib.request.Request(ENGINE_SHUTDOWN_URL, data=b"{}", headers={'Content-Type': 'application/json'}, method='POST')
        with urllib.request.urlopen(req, timeout=2.0) as resp:
            pass
    except Exception:
        pass

    # 2. Await process exit if launched by this instance
    if engine_process:
        try:
            engine_process.wait(timeout=2.0)
        except subprocess.TimeoutExpired:
            logging.warning("Engine did not exit gracefully; terminating process tree...")
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(engine_process.pid)], capture_output=True)
        engine_process = None

class JsApi:
    def __init__(self, window_ref):
        self._window = window_ref

def on_app_ready():
    """Wait for native window handle to become available, then apply taskbar AppUserModelID and icons."""
    max_wait = 5.0
    start = time.time()
    hwnd = 0
    while time.time() - start < max_wait:
        if main_window and hasattr(main_window, 'native') and main_window.native:
            try:
                if hasattr(main_window.native, 'Handle'):
                    hwnd = int(main_window.native.Handle.ToInt64())
                elif isinstance(main_window.native, int):
                    hwnd = main_window.native
                if hwnd:
                    break
            except Exception:
                pass
        time.sleep(0.1)

    if hwnd:
        set_taskbar_properties(hwnd, APP_ID, ICON_ICO)
        apply_win32_icons(hwnd)
    else:
        logging.warning("Native HWND not acquired within timeout.")

def enforce_single_instance():
    """Ensures only a single instance of the Words UI is running."""
    mutex_name = "Local\\WordsAppSingleInstanceMutex"
    kernel32.CreateMutexW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]
    kernel32.CreateMutexW.restype = wintypes.HANDLE
    kernel32.GetLastError.argtypes = []
    kernel32.GetLastError.restype = wintypes.DWORD

    mutex = kernel32.CreateMutexW(None, wintypes.BOOL(True), mutex_name)
    if kernel32.GetLastError() == 183:  # ERROR_ALREADY_EXISTS
        user32.FindWindowW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR]
        user32.FindWindowW.restype = wintypes.HWND
        existing_hwnd = user32.FindWindowW(None, "Words")
        if existing_hwnd:
            user32.SetForegroundWindow.argtypes = [wintypes.HWND]
            user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
            user32.ShowWindow(existing_hwnd, 9)  # SW_RESTORE
            user32.SetForegroundWindow(existing_hwnd)
        sys.exit(0)
    return mutex

def main():
    global main_window
    _mutex = enforce_single_instance()
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

    logging.info("Starting pywebview event loop.")
    webview.start(on_app_ready, icon=ICON_ICO, gui='edgechromium', debug=False)

if __name__ == "__main__":
    try:
        main()
    finally:
        shutdown_engine()
