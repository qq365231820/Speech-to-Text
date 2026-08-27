"""Small Win32 bridge: no clipboard access and no resident native framework."""
import base64
import ctypes as c
from ctypes import wintypes as w

user = c.WinDLL("user32", use_last_error=True)
kernel = c.WinDLL("kernel32", use_last_error=True)
crypt = c.WinDLL("crypt32", use_last_error=True)
user.GetForegroundWindow.restype = w.HWND
user.GetWindowThreadProcessId.argtypes = [w.HWND, c.POINTER(w.DWORD)]
user.GetWindowThreadProcessId.restype = w.DWORD
user.GetAsyncKeyState.argtypes = [c.c_int]
user.GetAsyncKeyState.restype = c.c_short

class Blob(c.Structure):
    _fields_ = [("size", w.DWORD), ("data", c.POINTER(c.c_ubyte))]

kernel.LocalFree.argtypes = [c.c_void_p]
kernel.LocalFree.restype = c.c_void_p
crypt.CryptProtectData.argtypes = [c.POINTER(Blob), w.LPCWSTR, c.POINTER(Blob), c.c_void_p, c.c_void_p, w.DWORD, c.POINTER(Blob)]
crypt.CryptUnprotectData.argtypes = [c.POINTER(Blob), c.c_void_p, c.POINTER(Blob), c.c_void_p, c.c_void_p, w.DWORD, c.POINTER(Blob)]

def _dpapi(data, decrypt=False):
    buf = (c.c_ubyte * len(data)).from_buffer_copy(data)
    src, dst = Blob(len(data), buf), Blob()
    func = crypt.CryptUnprotectData if decrypt else crypt.CryptProtectData
    if not func(c.byref(src), None, None, None, None, 1, c.byref(dst)):
        raise OSError("Windows 密钥保护失败，配置只能由原 Windows 用户解密")
    try:
        return c.string_at(dst.data, dst.size)
    finally:
        kernel.LocalFree(dst.data)

def protect(value):
    return "dpapi:" + base64.b64encode(_dpapi(value.encode())).decode()

def unprotect(value):
    if not value.startswith("dpapi:"):
        raise ValueError("拒绝读取未加密密钥")
    return _dpapi(base64.b64decode(value[6:]), True).decode()

class GUIInfo(c.Structure):
    _fields_ = [("cbSize", w.DWORD), ("flags", w.DWORD), ("hwndActive", w.HWND),
                ("hwndFocus", w.HWND), ("hwndCapture", w.HWND), ("hwndMenuOwner", w.HWND),
                ("hwndMoveSize", w.HWND), ("hwndCaret", w.HWND), ("rcCaret", w.RECT)]

user.GetGUIThreadInfo.argtypes = [w.DWORD, c.POINTER(GUIInfo)]

def focus():
    hwnd = user.GetForegroundWindow()
    info = GUIInfo(cbSize=c.sizeof(GUIInfo))
    thread = user.GetWindowThreadProcessId(hwnd, None)
    user.GetGUIThreadInfo(thread, c.byref(info))
    return (hwnd, info.hwndFocus)

def modifiers_down():
    return any(user.GetAsyncKeyState(vk) & 0x8000 for vk in (0x10, 0x11, 0x12, 0x5b, 0x5c))

class KeyboardInput(c.Structure):
    _fields_ = [("vk", w.WORD), ("scan", w.WORD), ("flags", w.DWORD), ("time", w.DWORD), ("extra", c.c_size_t)]
class MouseInput(c.Structure):
    _fields_ = [("dx", w.LONG), ("dy", w.LONG), ("data", w.DWORD), ("flags", w.DWORD), ("time", w.DWORD), ("extra", c.c_size_t)]
class InputUnion(c.Union):
    _fields_ = [("ki", KeyboardInput), ("mi", MouseInput)]
class Input(c.Structure):
    _fields_ = [("type", w.DWORD), ("u", InputUnion)]
user.SendInput.argtypes = [w.UINT, c.POINTER(Input), c.c_int]
user.SendInput.restype = w.UINT

def type_text(text, target):
    if focus() != target:
        raise RuntimeError("输入焦点已改变，文字已保留，请使用托盘中的“取回未输入文字”")
    if modifiers_down():
        raise RuntimeError("请松开 Ctrl / Alt / Shift / Win 后再输入")
    encoded = text.encode("utf-16-le")
    # Small batches limit impact if the user switches windows during insertion.
    for start in range(0, len(encoded), 128):
        if focus() != target:
            raise RuntimeError("输入中焦点改变，可能已输入部分文字；请检查并取回结果")
        chunk = encoded[start:start+128]
        events = []
        for i in range(0, len(chunk), 2):
            unit = int.from_bytes(chunk[i:i+2], "little")
            events.extend([Input(1, InputUnion(ki=KeyboardInput(0, unit, 4, 0, 0))),
                           Input(1, InputUnion(ki=KeyboardInput(0, unit, 6, 0, 0)))])
        array = (Input * len(events))(*events)
        if user.SendInput(len(events), array, c.sizeof(Input)) != len(events):
            raise RuntimeError("Windows 拒绝输入（目标可能以管理员权限运行），结果已保留")

def no_activate(hwnd):
    get = user.GetWindowLongW
    get.argtypes = [w.HWND, c.c_int]
    get.restype = w.LONG
    put = user.SetWindowLongW
    put.argtypes = [w.HWND, c.c_int, w.LONG]
    put(hwnd, -20, get(hwnd, -20) | 0x08000000 | 0x00000080)

def single_instance():
    kernel.CreateMutexW.argtypes = [c.c_void_p, w.BOOL, w.LPCWSTR]
    kernel.CreateMutexW.restype = w.HANDLE
    handle = kernel.CreateMutexW(None, False, "Local\\LuoyangVoiceInput")
    if not handle:
        raise OSError("无法创建程序互斥锁")
    return handle, c.get_last_error() != 183
