"""32비트 Cybos 브리지 프로세스를 띄우고 감시하며 JSON-RPC로 호출한다."""
import asyncio
import json
import logging
import os
import subprocess
from pathlib import Path

from .config import ROOT

BRIDGE_PY = ROOT / "cybos_bridge" / "cybos_bridge.py"
NOWIN = subprocess.CREATE_NO_WINDOW
log = logging.getLogger("cybos")


class CybosBridge:
    def __init__(self, python_exe, port, on_event, on_status):
        self.python_exe, self.port = python_exe, port
        self.on_event, self.on_status = on_event, on_status
        self.proc = self.reader = self.writer = None
        self.pending, self.seq = {}, 0
        self.connected, self._stop = False, False

    def _spawn(self):
        (ROOT / "logs").mkdir(exist_ok=True)
        (ROOT / "run").mkdir(exist_ok=True)
        with open(ROOT / "logs" / "cybos_bridge.log", "ab") as logf:
            self.proc = subprocess.Popen(
                [self.python_exe, "-u", str(BRIDGE_PY), str(self.port), str(os.getpid())],
                cwd=str(ROOT), stdout=logf, stderr=subprocess.STDOUT, creationflags=NOWIN)
        (ROOT / "run" / "bridge.pid").write_text(str(self.proc.pid))
        log.info("bridge spawned pid=%s", self.proc.pid)

    def _kill(self):
        if self.proc and self.proc.poll() is None:
            subprocess.run(["taskkill", "/PID", str(self.proc.pid), "/T", "/F"],
                           capture_output=True, creationflags=NOWIN)
        self.proc = None

    async def run(self):
        while not self._stop:
            if not self.python_exe or not Path(self.python_exe).exists():
                await self.on_status(False, f"32비트 파이썬 없음: {self.python_exe}")
                await asyncio.sleep(10)
                continue
            try:
                if self.proc is None or self.proc.poll() is not None:
                    self._spawn()
                await self._connect()
                self.connected = True
                await self.on_status(True, "브리지 연결됨")
                await self._read_loop()
                msg = "브리지 연결 끊김"
            except asyncio.CancelledError:
                raise
            except Exception as e:
                msg = f"브리지 오류: {e}"
            self.connected = False
            for f in self.pending.values():
                if not f.done():
                    f.set_exception(RuntimeError(msg))
            self.pending.clear()
            if self.writer:
                self.writer.close()
                self.writer = None
            if not self._stop:
                await self.on_status(False, msg)
                await asyncio.sleep(3)

    async def _connect(self):
        last = None
        for _ in range(30):
            if self.proc and self.proc.poll() is not None:
                raise RuntimeError(f"브리지 프로세스 종료(code={self.proc.returncode}) - logs\\cybos_bridge.log 확인")
            try:
                self.reader, self.writer = await asyncio.open_connection(
                    "127.0.0.1", self.port, limit=8 * 1024 * 1024)
                return
            except OSError as e:
                last = e
                await asyncio.sleep(0.5)
        raise RuntimeError(f"브리지 접속 실패: {last}")

    async def _read_loop(self):
        while True:
            line = await self.reader.readline()
            if not line:
                return
            msg = json.loads(line)
            if "id" in msg:
                f = self.pending.get(msg["id"])
                if f and not f.done():
                    if msg.get("ok"):
                        f.set_result(msg.get("result"))
                    else:
                        f.set_exception(RuntimeError(msg.get("error")))
            elif "event" in msg:
                try:
                    await self.on_event(msg)
                except Exception:
                    log.exception("event handler")

    async def call(self, method, timeout=20, **params):
        if not self.connected or not self.writer:
            raise RuntimeError("Cybos 브리지 미연결")
        self.seq += 1
        rid = self.seq
        fut = asyncio.get_running_loop().create_future()
        self.pending[rid] = fut
        try:
            self.writer.write((json.dumps({"id": rid, "method": method, "params": params},
                                          ensure_ascii=False) + "\n").encode("utf-8"))
            await self.writer.drain()
            return await asyncio.wait_for(fut, timeout)
        finally:
            self.pending.pop(rid, None)

    async def restart(self):
        self._kill()
        if self.writer:
            self.writer.close()

    async def stop(self):
        self._stop = True
        self._kill()
        if self.writer:
            self.writer.close()
        (ROOT / "run" / "bridge.pid").unlink(missing_ok=True)
