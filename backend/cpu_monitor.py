import threading
import psutil

_lock = threading.Lock()
_samples: list[float] = []
_timer: threading.Timer | None = None
_interval = 1.0  # seconds between samples


def _sample():
    global _timer
    with _lock:
        _samples.append(psutil.cpu_percent())
    _timer = threading.Timer(_interval, _sample)
    _timer.daemon = True
    _timer.start()


def start():
    global _timer, _samples
    with _lock:
        _samples = []
    if _timer is not None:
        _timer.cancel()
    _timer = threading.Timer(_interval, _sample)
    _timer.daemon = True
    _timer.start()


def stop() -> float | None:
    """Stop sampling and return the average CPU %, or None if no samples."""
    global _timer
    if _timer is not None:
        _timer.cancel()
        _timer = None
    with _lock:
        if not _samples:
            return None
        avg = sum(_samples) / len(_samples)
        _samples.clear()
    return round(avg, 2)
