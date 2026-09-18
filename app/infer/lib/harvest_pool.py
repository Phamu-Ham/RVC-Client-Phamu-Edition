"""On-demand Harvest workers. Importing this module creates no processes."""
import atexit
import multiprocessing


def _harvest_chunk(audio):
    import numpy as np
    import pyworld

    return pyworld.harvest(
        audio.astype(np.double), fs=16000, f0_ceil=1100, f0_floor=50,
        frame_period=10,
    )[0]


class HarvestPool:
    def __init__(self):
        self._pool = None
        self._count = 0
        atexit.register(self.close)

    def ensure(self, count):
        count = max(1, int(count))
        if count <= 1:
            return
        if self._pool is not None and self._count == count:
            return
        self.close()
        self._pool = multiprocessing.get_context("spawn").Pool(count)
        self._count = count

    def compute(self, audio, count):
        """Keep the original chunk overlap, merge boundaries and frame count."""
        import numpy as np

        count = int(count)
        self.ensure(count)
        length = len(audio)
        part_length = 160 * ((length // 160 - 1) // count + 1)
        parts = (length // 160 - 1) // (part_length // 160) + 1
        chunks = []
        for index in range(parts):
            tail = part_length * (index + 1) + 320
            head = 0 if index == 0 else part_length * index - 320
            chunks.append(audio[head:tail])
        # A worker failure must surface instead of leaving the audio callback
        # waiting indefinitely for the old Manager-dict completion message.
        try:
            outputs = self._pool.map_async(_harvest_chunk, chunks).get(timeout=30)
        except Exception:
            self.close()
            raise
        result = np.zeros(length // 160 + 1, dtype=np.float64)
        for index, f0 in enumerate(outputs):
            if index == 0:
                f0 = f0[:-3]
            elif index != parts - 1:
                f0 = f0[2:-3]
            else:
                f0 = f0[2:]
            head = part_length * index // 160
            result[head:head + len(f0)] = f0
        return result

    def close(self):
        pool, self._pool = self._pool, None
        self._count = 0
        if pool is not None:
            # Called only after the stream stops, or on failure/exit. Terminate
            # also guarantees cleanup if a native Harvest call is stuck.
            pool.terminate()
            pool.join()
