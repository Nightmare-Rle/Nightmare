import ctypes

CF_UNICODETEXT = 13
GHND = 0x0042


def get_clipboard():
    try:
        u32 = ctypes.windll.user32
        k32 = ctypes.windll.kernel32
        u32.OpenClipboard.argtypes = [ctypes.c_void_p]
        u32.GetClipboardData.restype = ctypes.c_void_p
        k32.GlobalLock.restype = ctypes.c_void_p
        k32.GlobalUnlock.argtypes = [ctypes.c_void_p]
        k32.GlobalSize.argtypes = [ctypes.c_void_p]
        k32.GlobalSize.restype = ctypes.c_size_t
        if not u32.OpenClipboard(None):
            return ""
        try:
            if not u32.IsClipboardFormatAvailable(CF_UNICODETEXT):
                return ""
            handle = u32.GetClipboardData(CF_UNICODETEXT)
            if not handle:
                return ""
            length = k32.GlobalSize(handle)
            if length <= 0:
                return ""
            locked = k32.GlobalLock(handle)
            if not locked:
                return ""
            try:
                buffer = ctypes.create_unicode_buffer(length // 2)
                ctypes.memmove(buffer, locked, length)
                return buffer.value or ""
            finally:
                k32.GlobalUnlock(handle)
        finally:
            u32.CloseClipboard()
    except Exception:
        return ""


def set_clipboard(text):
    try:
        u32 = ctypes.windll.user32
        k32 = ctypes.windll.kernel32
        u32.OpenClipboard.argtypes = [ctypes.c_void_p]
        k32.GlobalAlloc.argtypes = [ctypes.c_uint, ctypes.c_size_t]
        k32.GlobalAlloc.restype = ctypes.c_void_p
        k32.GlobalLock.argtypes = [ctypes.c_void_p]
        k32.GlobalLock.restype = ctypes.c_void_p
        k32.GlobalUnlock.argtypes = [ctypes.c_void_p]
        u32.SetClipboardData.argtypes = [ctypes.c_uint, ctypes.c_void_p]
        u32.SetClipboardData.restype = ctypes.c_void_p
        k32.GlobalFree.argtypes = [ctypes.c_void_p]
        data = str(text or "")
        if not u32.OpenClipboard(None):
            return False
        try:
            u32.EmptyClipboard()
            size = (len(data) + 1) * 2
            handle = k32.GlobalAlloc(GHND, size)
            if not handle:
                return False
            try:
                locked = k32.GlobalLock(handle)
                if not locked:
                    return False
                ctypes.memmove(locked, data.encode("utf-16-le") + b"\x00\x00", size)
                k32.GlobalUnlock(handle)
                if not u32.SetClipboardData(CF_UNICODETEXT, handle):
                    return False
                handle = None
            finally:
                if handle:
                    k32.GlobalFree(handle)
        finally:
            u32.CloseClipboard()
        return True
    except Exception:
        return False