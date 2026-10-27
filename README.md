# Innovex

## TN Transmit Smart Crowd AI — starter website

A Flask dashboard prototype for the TN Transmit Smart Crowd AI project. It includes media upload and preview, configurable passenger threshold, bilingual browser speech test alerts, event history, and configuration placeholders for CCTV, authority webhooks, and IoT.

## Run on Windows PowerShell

1. Install Python 3.11 or 3.12 (recommended for the later OpenCV/YOLO integration).
2. Open PowerShell in this folder.
3. Create and activate a virtual environment:

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
```

If PowerShell blocks activation, run commands directly using `\.venv\Scripts\python.exe` or use Command Prompt activation `\.venv\Scripts\activate.bat`.

4. Install dependencies and run:

```powershell
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
$env:AUTHORITY_CALLBACK_TOKEN = "set-a-long-random-secret"
$env:FLASK_SECRET_KEY = "set-a-different-long-random-secret"
python app.py
```

5. In another PowerShell window, use the same callback token to provision a driver via `/api/authority/drivers`, then open `http://127.0.0.1:5000` and sign in. The account creation request is documented below.

## Deploy on Render

1. Push this project to a Git repository. Keep `models/yolov8n.onnx` in the repository; Render needs the model to analyze media.
2. In Render, choose **New > Blueprint** and select the repository containing `render.yaml`. Render will install `requirements.txt`, start Gunicorn, and check `/health`.
3. Configure the `AUTHORITY_CALLBACK_TOKEN` when Render prompts for it. The Blueprint generates a persistent `FLASK_SECRET_KEY` and enables secure session cookies.
4. When the deployment finishes, open the service URL. Driver accounts, updates, event history, uploads, analysis outputs and saved settings are stored under `DATA_DIR`; Render's free service uses ephemeral storage, so they can be lost on restart or redeploy.
5. To retain accounts and operational data, use a Render plan that supports a persistent disk and set `DATA_DIR` to its mount path (for example, `/var/data`).

The dashboard requires a driver login. The external transport authority provisions driver accounts through the authenticated API described below. Keep the authority callback token and session secret private. This is a prototype, not a certified passenger-safety system; do not connect it directly to door actuation.

## What is implemented

- Responsive dashboard UI.
- Upload and preview common video/image files.
- Save configuration for passenger limit, vehicle ID, CCTV source, and IoT mode/endpoint; set the authority webhook URL/token as Render environment variables.
- Local event log and API endpoints: `/api/status`, `/api/settings`, `/api/upload`, `/api/alert`, `/api/iot/test`, `/api/events`, `/api/authority/drivers`, `/api/authority/bus-allocation`, `/api/authority/allocations`, `/api/driver/updates`, `/health`.
- In-app transport authority notifications for bus allocated and not allocated decisions (polled while the dashboard is open).
- Authority-provisioned driver accounts, secure password hashes, driver login/logout, status updates shared with all logged-in drivers, and authority webhook delivery status.
- Browser-based English and Tamil announcement test buttons.
- IoT test is mock-only; it does not issue a door movement command.

## Not yet implemented — must be connected and tested

1. YOLO/OpenCV inference on uploaded media.
2. Person tracking with unique track IDs and calibrated entry/exit lines.
3. Reliable occupancy calculation (entry/exit counts alone need a known initial occupancy and reset/reconciliation logic).
4. Door-step obstruction sensor and hardware feedback.
5. Outbound delivery to the authority website requires its API contract. Set `AUTHORITY_WEBHOOK_URL` and (if needed) `AUTHORITY_API_TOKEN`; the endpoint must accept the documented driver-status JSON payload.
6. Real CCTV stream ingestion. Browser support varies; RTSP normally requires backend access and may need a stream bridge.
7. Real IoT protocol adapter. Obtain the device make/model, protocol, wiring/interface and documented API. Do not connect a relay or motor to an unverified endpoint.

## Safety notes

- This is a prototype, not a certified passenger-safety system.
- The independent physical door controller must prevent closing while an obstruction is present. AI/video should not be the sole door safety interlock.
- Fail safe on sensor uncertainty, controller/network failure, or loss of power; retain manual/emergency override.
- Do not expose this Flask development server publicly. Use authenticated production hosting, HTTPS, access controls, rate limiting, and secure secret storage before any external integration.
- Configure the passenger threshold according to the specific vehicle's approved capacity and applicable transport rules.
- Browser speech depends on installed voices, browser permissions and speaker hardware. For an actual bus PA, use an approved audio/controller interface.

## Recommended integration sequence

1. Confirm the detector and tracker, then process saved video offline.
2. Calibrate entry/exit lines on sample clips; verify counts manually across several lighting and crowd conditions.
3. Add a doorway ROI and obstruction dwell-time logic, but use the physical safety sensor as the authoritative interlock.
4. Implement and test authority webhook delivery with retry, unique event IDs, acknowledgements and delivery status.
5. Implement the device-specific IoT adapter in a bench test, initially with a dummy load, and only after the controller's safety requirements are understood.
6. Add live CCTV after offline video processing is reliable.

## Real video/image inference (YOLO ONNX)

1. Install dependencies from `requirements.txt` in a supported Python environment.
2. Create the `models` folder beside `app.py` and copy your YOLOv8 ONNX model to `models/yolov8n.onnx`.
3. Start with `python app.py`, upload a video or image, click **Upload file**, then click **Analyse media**.
4. The dashboard reports peak people visible in a sampled frame and provides an annotated output. For CPU performance, video inference samples every third frame.

The ONNX parser expects a standard YOLOv8 COCO export with person as class 0 and input around 640x640. Some custom ONNX exports use different output layouts and will need a matching parser. The current peak-in-frame count is not a verified passenger-on-board count. Entry/exit tracking requires calibrated counting lines and a tracker; doorway obstruction detection requires a calibrated doorway region and validation. Those must not be represented as active until implemented and tested.

### Event history

Use the trash icon on a row to remove one event or **Clear all history** to remove all event logs. Clearing event history does not delete uploaded media or annotated outputs. The quick buttons now test audio with wording that explicitly says no hazard was detected; real crowd announcements are only triggered after analysis meets the configured threshold.

### Driver incident reports

The Webhook / API endpoint defaults to `https://transport-authority-dashboard.onrender.com/api/alerts`; this is the authority dashboard's POST-only alert API, not its homepage. On Render, set `AUTHORITY_WEBHOOK_URL` to this endpoint to override deployment-specific config. Add `AUTHORITY_API_TOKEN` only if the authority requires one. Driver accounts cannot change these settings. The webhook receives incident reports and driver status updates; delivery results are logged, and a driver status remains visible in the shared feed even if authority forwarding fails.

### Driver account and shared update API

The transport authority provisions driver accounts over HTTPS:

```http
POST https://<your-render-service>/api/authority/drivers
Authorization: Bearer <AUTHORITY_CALLBACK_TOKEN>
Content-Type: application/json
```

with JSON such as `{"username":"driver01","password":"<12+ character unique password>","display_name":"Driver One"}`. Passwords are stored as hashes; credentials are never returned by the API. Drivers sign in at the Render service root, then post updates using their authenticated dashboard session. Supported statuses are `on_the_way`, `at_stop`, `delayed`, `needs_assistance`, and `situation`; a location is required for `at_stop`. Updates are shared to every logged-in driver and forwarded to the configured authority webhook.

### Transport authority bus-allocation notifications

The dashboard requires driver login and polls a persistent, shared update feed every 8 seconds while open. Use the `AUTHORITY_CALLBACK_TOKEN` Render secret for both account provisioning and assignment callbacks.

To assign a bus, send:

```http
POST https://<your-render-service>/api/authority/bus-allocation
Authorization: Bearer <AUTHORITY_CALLBACK_TOKEN>
Content-Type: application/json
```

with JSON such as `{"status":"allocated","driver_username":"driver01","bus_id":"TN-TRANSMIT-01","route":"21G","message":"Assigned","allocation_id":"A-123"}`. Use `"status":"not_allocated"` for the no-assignment decision; `driver_username` can identify the driver affected. `bus_id`, `route`, `message`, and `allocation_id` are optional. An allocated driver must already have an account. The callback rejects invalid authentication, status values, and unknown driver accounts.

Drivers can post status/location/situation updates from the dashboard. Each update is persisted and visible to all logged-in drivers. The app forwards it to `AUTHORITY_WEBHOOK_URL` as JSON with `event_type: "driver_status_update"`; it records whether the authority accepted the request or delivery failed. Configure that endpoint to accept this event schema and bearer token before relying on authority receipt. The driver feed updates while each dashboard is open; it is not a push notification when the browser is closed. Use persistent Render storage or driver accounts and updates will be lost on restart.

### Safety note

This is a research prototype. Browser speech is not a reliable vehicle-wide PA system. Do not connect experimental AI outputs directly to bus door actuation; a certified physical safety interlock and the manufacturer's controller must remain authoritative.
