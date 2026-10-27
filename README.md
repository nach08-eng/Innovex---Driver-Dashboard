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
python app.py
```

5. Open `http://127.0.0.1:5000` in your browser.

## Deploy on Render

1. Push this project to a Git repository. Keep `models/yolov8n.onnx` in the repository; Render needs the model to analyze media.
2. In Render, choose **New > Blueprint** and select the repository containing `render.yaml`. Render will install `requirements.txt`, start Gunicorn, and check `/health`.
3. When the deployment finishes, open the service URL. The free service uses ephemeral storage: uploaded media, analysis outputs, event history, and saved settings can be lost when the service restarts or redeploys.
4. To retain that data, attach a Render persistent disk and set the service environment variable `DATA_DIR` to its mount path (for example, `/var/data`). Persistent disks are not available on Render's free web-service plan.

The app is publicly reachable when deployed. It is a prototype without user authentication; use test data only and do not enter real API tokens or sensitive operational data. Do not use it as a certified passenger-safety system or connect it directly to door actuation.

## What is implemented

- Responsive dashboard UI.
- Upload and preview common video/image files.
- Save configuration for passenger limit, vehicle ID, CCTV source, IoT mode/endpoint, and authority endpoint.
- Local event log and API endpoints: `/api/status`, `/api/settings`, `/api/upload`, `/api/alert`, `/api/iot/test`, `/api/events`, `/api/authority/bus-allocation`, `/api/authority/allocations`, `/health`.
- In-app transport authority notifications for bus allocated and not allocated decisions (polled while the dashboard is open).
- Browser-based English and Tamil announcement test buttons.
- IoT test is mock-only; it does not issue a door movement command.

## Not yet implemented — must be connected and tested

1. YOLO/OpenCV inference on uploaded media.
2. Person tracking with unique track IDs and calibrated entry/exit lines.
3. Reliable occupancy calculation (entry/exit counts alone need a known initial occupancy and reset/reconciliation logic).
4. Door-step obstruction sensor and hardware feedback.
5. Outbound delivery to the authority website still needs its API contract. Inbound bus-allocation notifications are ready for authority webhook integration; configure `AUTHORITY_CALLBACK_TOKEN` and have the authority POST allocation decisions to `/api/authority/bus-allocation`.
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

Configure the authority's report API in **Connected systems** using its webhook/API endpoint and optional bearer token, then submit reports from **Driver incident report**. The report is sent to this app's server first, which forwards it to the configured endpoint and logs delivery results. On Render, set `AUTHORITY_WEBHOOK_URL` and (if required) `AUTHORITY_API_TOKEN` as service environment variables to keep the endpoint and token available across deploys. The authority endpoint must accept a JSON `POST` containing the report fields; test its expected payload and authentication with the authority before relying on delivery. A report that cannot be forwarded is saved locally and explicitly marked as not delivered.

### Transport authority bus-allocation notifications

The dashboard checks for allocation updates every 10 seconds while it is open and shows the latest decision, whether the bus was allocated or not. To connect the transport authority, set a strong `AUTHORITY_CALLBACK_TOKEN` environment variable on Render and configure the authority's server to send:

```http
POST https://<your-render-service>/api/authority/bus-allocation
Authorization: Bearer <AUTHORITY_CALLBACK_TOKEN>
Content-Type: application/json
```

with JSON such as `{"status":"allocated","bus_id":"TN-TRANSMIT-01","route":"21G","message":"Assigned","allocation_id":"A-123"}`. Use `"status":"not_allocated"` for a denial/no-bus decision. `bus_id`, `route`, `message`, and `allocation_id` are optional; when omitted, the configured bus ID is used. The callback rejects missing/invalid authentication and invalid status values. The authority must send a callback for both outcomes. This dashboard notification is not delivered if the website is closed, and Render's free service may lose event history after restart unless persistent storage is configured.

### Safety note

This is a research prototype. Browser speech is not a reliable vehicle-wide PA system. Do not connect experimental AI outputs directly to bus door actuation; a certified physical safety interlock and the manufacturer's controller must remain authoritative.
