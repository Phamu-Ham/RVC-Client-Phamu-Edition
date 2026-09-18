"""Small runtime helpers shared by the GUI and inference engine."""
from collections import OrderedDict
from functools import wraps
import inspect
import os


DEBUG_REALTIME = os.environ.get("RVC_DEBUG_REALTIME") == "1"


def debugt(message, *args):
    if DEBUG_REALTIME:
        print(message % args if args else message)


def cache_artwork(render):
    """Cache rendered PNG bytes; edits at the same path invalidate the entry."""
    entries = OrderedDict()
    signature = inspect.signature(render)
    total_bytes = 0
    limit = 8 * 1024 * 1024

    @wraps(render)
    def cached(*args, **kwargs):
        nonlocal total_bytes
        bound = signature.bind(*args, **kwargs)
        bound.apply_defaults()
        path = str(bound.arguments.get("image_path", "") or "").strip().strip('"')
        path = os.path.abspath(path) if path else ""
        bound.arguments["image_path"] = path
        try:
            stat = os.stat(path)
            revision = (stat.st_mtime_ns, stat.st_size)
        except OSError:
            revision = None
        key = (tuple(bound.arguments.items()), revision)
        if key in entries:
            entries.move_to_end(key)
            return entries[key]
        data = render(*bound.args, **bound.kwargs)
        if len(data) <= limit:
            while entries and (total_bytes + len(data) > limit or len(entries) >= 128):
                _, old = entries.popitem(last=False)
                total_bytes -= len(old)
            entries[key] = data
            total_bytes += len(data)
        return data

    def clear():
        nonlocal total_bytes
        entries.clear()
        total_bytes = 0

    cached.cache_clear = clear
    return cached
