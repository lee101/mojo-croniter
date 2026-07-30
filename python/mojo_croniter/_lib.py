from __future__ import annotations

import ctypes
import os

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
LIB = os.environ.get("MOJO_CRONITER_LIB") or os.path.join(
    ROOT, "dist", "libmojo-croniter.so"
)

I = ctypes.c_int64


class BuildError(RuntimeError):
    pass


_library: ctypes.CDLL | None = None


def lib() -> ctypes.CDLL:
    global _library
    if _library is None:
        if not os.path.exists(LIB):
            raise BuildError(f"compiled library not found at {LIB}; run `pixi run build`")
        _library = ctypes.CDLL(LIB)
        _library.mcron_next.argtypes = [I, I, I, I, I, I]
        _library.mcron_next.restype = I
        _library.mcron_prev.argtypes = [I, I, I, I, I, I]
        _library.mcron_prev.restype = I
        _library.mcron_fill.argtypes = [I, I, I, I, I, I, I, I, I, I]
        _library.mcron_fill.restype = I
    return _library
