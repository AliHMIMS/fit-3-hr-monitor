# fit-3-hr-monitor

Show your live heart rate from a **Samsung Galaxy Fit 3** on stream. It works as an OBS overlay
or in any other tool that can display a web page.

A small Python server connects to the band over Bluetooth Low Energy and reads the standard
Heart Rate service. It sends every reading over a WebSocket to a web page that shows your
current BPM and a scrolling graph.

```
Galaxy Fit 3 ──BLE──▶ hr_server.py ──WebSocket──▶ overlay page ──▶ OBS Browser source
```

- No phone, app or Samsung account needed while it runs
- Transparent overlay with a beating heart, the BPM and a line graph
- Reconnects on its own if the band drops
- Keeps recent history, so reloading the overlay doesn't clear the graph

## Requirements

- **Windows 10/11** with Bluetooth (built-in or a USB dongle). It's only tested on Windows. The
  BLE library ([bleak](https://github.com/hbldh/bleak)) also supports macOS and Linux, but
  bonding works differently there.
- **Python 3.10+** from [python.org](https://www.python.org/downloads/). During install, tick
  "Add python.exe to PATH".
- A **Galaxy Fit 3**.
- **OBS Studio**, or anything that can show a web page.

## Setup

### 1. Download the project

```powershell
git clone https://github.com/AliHMIMS/fit-3-hr-monitor.git
cd fit-3-hr-monitor
```

(Or use **Code → Download ZIP** on GitHub and extract it.)

### 2. Install the dependencies

```powershell
py -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
```

### 3. Free the band from your phone

The band only accepts one Bluetooth connection. While it's connected to your phone, the PC
can't see it.

- Turn **Bluetooth off on your phone**, or move the phone out of range.
- Make sure **Bluetooth is on in Windows** (Settings → Bluetooth & devices).
- Tap the band to wake its screen.

### 4. Start the server

```powershell
.venv\Scripts\python hr_server.py
```

The server searches for a device named "Galaxy Fit3" and connects. On the first connection it
bonds with the band; you don't need to pair it in Windows settings. You should see something
like:

```
17:20:05 overlay: http://127.0.0.1:8765/
17:20:05 status: searching
17:20:06 status: connecting (Galaxy Fit3 (XXXX))
17:20:07 status: connected (Galaxy Fit3 (XXXX))
```

Leave this window open while you stream.

### 5. Start measuring on the band

**Open the Heart Rate screen on the band.** The band only sends readings (about one per second)
while it's actively measuring. When it's idle it stays connected but sends nothing, and the
overlay shows `--`.

### 6. Check the overlay

Open <http://127.0.0.1:8765/> in your browser. You should see the heart, your BPM and the graph.

### 7. Add it to OBS

1. In **Sources**, click **+** → **Browser**.
2. Set **URL** to `http://127.0.0.1:8765/`.
3. Set **Width** to `560` and **Height** to `120`.
4. Click **OK**, then move and scale the source as you like.

The page background is transparent, so only the card shows on top of your scene.

## Customising the overlay

Add options to the URL, for example `http://127.0.0.1:8765/?window=300&color=36c5f0&card=0`.

| Option | Default | What it does |
|---|---|---|
| `window` | `120` | Seconds of history shown in the graph |
| `color` | `ff4d5e` | Colour of the heart and line (6-digit hex, no `#`) |
| `graph` | `1` | `0` shows the number only |
| `card` | `1` | `0` removes the dark background card |

To change fonts, sizes or layout, edit `overlay.html`. Use the server's demo mode (below) to see
your changes without the band.

## Server options

```powershell
.venv\Scripts\python hr_server.py --help
```

| Option | Default | What it does |
|---|---|---|
| `--address AA:BB:CC:DD:EE:FF` | — | Connect to this band instead of searching by name. Useful if there's more than one band nearby. |
| `--port` | `8765` | Port for the overlay page and the WebSocket |
| `--host` | `127.0.0.1` | Use `0.0.0.0` to reach the overlay from another PC on your network |
| `--history` | `600` | Seconds of history kept for overlays that (re)connect |
| `--demo` | — | Fake heart rate, no band needed. Useful for styling the overlay. |
| `-v` | — | Log every reading |

## Troubleshooting

**`band not found`**
The band is probably still connected to your phone. Turn the phone's Bluetooth off, wake the
band, and wait: the server keeps retrying.

**Connected, but the overlay shows `--`**
The band isn't measuring. Open the Heart Rate screen on the band. Run with `-v` to see readings
arrive in the console.

**`The operation was canceled by the user` or other BLE errors right after a restart**
Windows sometimes keeps the old connection alive for a few seconds. The server retries
automatically. If it keeps failing, turn Windows Bluetooth off and on.

**Readings stop after a while**
The band may stop measuring when its screen times out. Open the Heart Rate screen again. A
longer screen timeout on the band can help.

## Using the data elsewhere

Anything can connect to `ws://127.0.0.1:8765/ws` and receive JSON messages:

```jsonc
// once, when you connect
{"type": "hello", "status": {"state": "connected", "device": "Galaxy Fit3 (XXXX)"}, "history": [[1792084699617, 82], ...]}

// one per reading (t = unix time in ms)
{"type": "hr", "t": 1792084703636, "bpm": 86, "contact": true}

// when the connection state changes
{"type": "status", "state": "searching | connecting | connected | disconnected", "device": "Galaxy Fit3 (XXXX)"}
```

## Disclaimer

This is an unofficial project and isn't affiliated with or endorsed by Samsung. Galaxy and
Galaxy Fit are trademarks of Samsung Electronics. Heart-rate readings are for display only and
aren't medical data.
