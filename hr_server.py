"""Stream live heart rate from a Galaxy Fit 3 to an OBS browser-source overlay.

Connects (and bonds) to the band over BLE, subscribes to the standard Heart Rate
Measurement characteristic (0x2a37), and pushes every reading to WebSocket clients.
The same server hosts the overlay page, so OBS only needs one URL:

    http://127.0.0.1:8765/            overlay page
    ws://127.0.0.1:8765/ws            JSON stream

Usage:
    python hr_server.py                       # find the band by name ("Galaxy Fit3")
    python hr_server.py --address AA:BB:CC:DD:EE:FF
    python hr_server.py --demo                # fake heart rate, no band needed

Keep the phone's Bluetooth off: the band only advertises (and accepts us) while it
isn't connected to the phone.
"""

import argparse
import asyncio
import json
import logging
import math
import random
import struct
import time
from collections import deque
from pathlib import Path

from aiohttp import WSMsgType, web
from bleak import BleakClient, BleakScanner

HR_MEAS = "00002a37-0000-1000-8000-00805f9b34fb"
OVERLAY = Path(__file__).with_name("overlay.html")

log = logging.getLogger("bpm")


def parse_hr(data):
    """Heart Rate Measurement per the BLE HRS spec. Returns (bpm, contact or None)."""
    flags = data[0]
    bpm = struct.unpack_from("<H", data, 1)[0] if flags & 0x01 else data[1]
    contact = bool(flags & 0x02) if flags & 0x04 else None
    return bpm, contact


class Hub:
    """Keeps recent readings and fans them out to connected overlay pages."""

    def __init__(self, history_seconds):
        self.history_seconds = history_seconds
        self.history = deque()  # (unix ms, bpm)
        self.status = {"state": "starting", "device": None}
        self.clients = set()

    def snapshot(self):
        return {
            "type": "hello",
            "status": self.status,
            "history": [[t, bpm] for t, bpm in self.history],
        }

    async def set_status(self, state, device=None):
        self.status = {"state": state, "device": device}
        log.info("status: %s%s", state, f" ({device})" if device else "")
        await self.broadcast({"type": "status", **self.status})

    async def add_reading(self, bpm, contact):
        now = int(time.time() * 1000)
        self.history.append((now, bpm))
        while self.history and self.history[0][0] < now - self.history_seconds * 1000:
            self.history.popleft()
        await self.broadcast({"type": "hr", "t": now, "bpm": bpm, "contact": contact})

    async def broadcast(self, msg):
        payload = json.dumps(msg)
        for ws in list(self.clients):
            try:
                await ws.send_str(payload)
            except Exception:
                self.clients.discard(ws)


async def find_band(address):
    if address:
        return await BleakScanner.find_device_by_address(address, timeout=15.0)
    return await BleakScanner.find_device_by_filter(
        lambda d, adv: "fit3" in (d.name or adv.local_name or "").lower().replace(" ", ""),
        timeout=15.0,
    )


async def band_loop(hub, address, pair):
    loop = asyncio.get_running_loop()
    while True:
        await hub.set_status("searching")
        try:
            device = await find_band(address)
            if device is None:
                log.warning("band not found - is the phone's Bluetooth off and the band awake?")
                await asyncio.sleep(3)
                continue

            disconnected = asyncio.Event()

            def on_disconnect(_client):
                loop.call_soon_threadsafe(disconnected.set)

            def on_hr(_sender, data):
                bpm, contact = parse_hr(data)
                log.debug("HR %d bpm (raw %s)", bpm, data.hex())
                loop.create_task(hub.add_reading(bpm, contact))

            await hub.set_status("connecting", device.name)
            async with BleakClient(
                device, pair=pair, timeout=40.0, disconnected_callback=on_disconnect
            ) as client:
                await client.start_notify(HR_MEAS, on_hr)
                await hub.set_status("connected", device.name)
                await disconnected.wait()
            log.warning("band disconnected")
        except asyncio.CancelledError:
            raise
        except Exception as e:
            log.warning("BLE error: %s", e)
        await hub.set_status("disconnected")
        await asyncio.sleep(3)


async def demo_loop(hub):
    """Synthetic heart rate: slow drift plus noise, one reading per second."""
    await hub.set_status("connected", "Demo")
    t0 = time.time()
    while True:
        t = time.time() - t0
        bpm = 82 + 18 * math.sin(t / 25) + 6 * math.sin(t / 7) + random.uniform(-2, 2)
        await hub.add_reading(round(bpm), True)
        await asyncio.sleep(1)


async def overlay_page(_request):
    return web.FileResponse(OVERLAY, headers={"Cache-Control": "no-store"})


async def ws_handler(request):
    hub = request.app["hub"]
    ws = web.WebSocketResponse(heartbeat=20)
    await ws.prepare(request)
    await ws.send_str(json.dumps(hub.snapshot()))
    hub.clients.add(ws)
    try:
        async for msg in ws:
            if msg.type == WSMsgType.ERROR:
                break
    finally:
        hub.clients.discard(ws)
    return ws


async def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--address", help="band MAC address (default: scan for 'Galaxy Fit3')")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--history", type=int, default=600, help="seconds of history to keep")
    parser.add_argument("--no-pair", action="store_true", help="don't bond (HR needs bonding)")
    parser.add_argument("--demo", action="store_true", help="fake heart rate, no band needed")
    parser.add_argument("-v", "--verbose", action="store_true", help="log every reading")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(message)s",
        datefmt="%H:%M:%S",
    )
    logging.getLogger("aiohttp.access").setLevel(logging.WARNING)
    if not args.verbose:
        logging.getLogger("bleak").setLevel(logging.WARNING)

    hub = Hub(args.history)
    app = web.Application()
    app["hub"] = hub
    app.router.add_get("/", overlay_page)
    app.router.add_get("/ws", ws_handler)

    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, args.host, args.port).start()
    log.info("overlay: http://%s:%d/", args.host, args.port)

    try:
        if args.demo:
            await demo_loop(hub)
        else:
            await band_loop(hub, args.address, pair=not args.no_pair)
    finally:
        await runner.cleanup()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
