from flask import Flask, render_template, request, jsonify, send_from_directory
from werkzeug.utils import secure_filename
from pathlib import Path
from datetime import datetime, timezone
import os, json, uuid, time, urllib.request, urllib.error
import hmac
import cv2
import numpy as np
import onnxruntime as ort

import sqlite3
import time
import threading

BASE = Path(__file__).resolve().parent
DATA_DIR = Path(os.environ.get('DATA_DIR', str(BASE))).expanduser()
DATA_DIR.mkdir(parents=True, exist_ok=True)
UPLOAD_DIR = DATA_DIR / 'uploads'
OUTPUT_DIR = DATA_DIR / 'outputs'
UPLOAD_DIR.mkdir(exist_ok=True)
OUTPUT_DIR.mkdir(exist_ok=True)
MODEL_DIR = BASE / 'models'
MODEL_DIR.mkdir(exist_ok=True)
MODEL_PATH = MODEL_DIR / 'yolov8n.onnx'
CONFIG_PATH = DATA_DIR / 'config.json'
EVENTS_PATH = DATA_DIR / 'events.jsonl'
ALLOWED = {'.mp4', '.avi', '.mov', '.mkv', '.webm', '.jpg', '.jpeg', '.png'}
app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 500 * 1024 * 1024
app.config['UPLOAD_FOLDER'] = str(UPLOAD_DIR)

DEFAULT_CONFIG = {
    'max_passengers': 40,
    'alert_at_limit': True,
    'authority_webhook_url': '',
    'authority_api_token': '',
    'iot_mode': 'mock',
    'iot_endpoint': '',
    'cctv_source': '',
    'bus_id': 'TN-TRANSMIT-DEMO-01'
}

def read_config():
    if CONFIG_PATH.exists():
        try:
            saved = json.loads(CONFIG_PATH.read_text(encoding='utf-8'))
            config = {**DEFAULT_CONFIG, **saved}
        except Exception:
            config = DEFAULT_CONFIG.copy()
    else:
        config = DEFAULT_CONFIG.copy()
    for key, env_var in (
        ('authority_webhook_url', 'AUTHORITY_WEBHOOK_URL'),
        ('authority_api_token', 'AUTHORITY_API_TOKEN')
    ):
        if os.environ.get(env_var):
            config[key] = os.environ[env_var].strip()
    return config

def log_event(event_type, message, level='info', details=None):
    event = {
        'id': str(uuid.uuid4())[:8],
        'timestamp': datetime.now(timezone.utc).astimezone().isoformat(timespec='seconds'),
        'type': event_type, 'message': message, 'level': level,
        'details': details or {}
    }
    with EVENTS_PATH.open('a', encoding='utf-8') as f:
        f.write(json.dumps(event, ensure_ascii=False) + '\n')
    return event

def write_events(rows):
    with EVENTS_PATH.open('w', encoding='utf-8') as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + '\n')

def get_events(limit=50):
    if not EVENTS_PATH.exists():
        return []
    rows = []
    for line in EVENTS_PATH.read_text(encoding='utf-8').splitlines()[-limit:]:
        try: rows.append(json.loads(line))
        except json.JSONDecodeError: continue
    return list(reversed(rows))

@app.get('/')
def index():
    return render_template('index.html', config=read_config(), events=get_events())

@app.get('/api/status')
def status():
    cfg = read_config()
    return jsonify({
        'ok': True, 'bus_id': cfg['bus_id'], 'max_passengers': cfg['max_passengers'],
        'cctv_configured': bool(cfg.get('cctv_source')),
        'authority_configured': bool(cfg.get('authority_webhook_url')),
        'iot_mode': cfg.get('iot_mode', 'mock'),
        'events': get_events(10)
    })

@app.post('/api/settings')
def settings():
    data = request.get_json(silent=True) or {}
    cfg = read_config()
    try:
        limit = int(data.get('max_passengers', cfg['max_passengers']))
        if not 1 <= limit <= 1000:
            return jsonify(ok=False, error='Passenger limit must be between 1 and 1000.'), 400
    except (TypeError, ValueError):
        return jsonify(ok=False, error='Passenger limit must be a whole number.'), 400
    cfg['max_passengers'] = limit
    cfg['alert_at_limit'] = bool(data.get('alert_at_limit', True))
    cfg['bus_id'] = str(data.get('bus_id', cfg['bus_id']))[:80]
    # Keep secrets/endpoints server-side; update only when explicitly submitted.
    for key in ('authority_webhook_url', 'authority_api_token', 'iot_mode', 'iot_endpoint', 'cctv_source'):
        if key in data:
            cfg[key] = str(data[key]).strip()
    CONFIG_PATH.write_text(json.dumps(cfg, indent=2), encoding='utf-8')
    log_event('settings', f"Settings updated. Passenger limit: {limit}")
    return jsonify(ok=True, config={k:v for k,v in cfg.items() if 'token' not in k})

@app.post('/api/upload')
def upload():
    file = request.files.get('file')
    if not file or not file.filename:
        return jsonify(ok=False, error='Choose a video or image first.'), 400
    safe_name = secure_filename(file.filename)
    suffix = Path(safe_name).suffix.lower()
    if suffix not in ALLOWED:
        return jsonify(ok=False, error='Supported formats: MP4, AVI, MOV, MKV, WEBM, JPG, JPEG, PNG.'), 400
    unique_name = f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}_{safe_name}"
    target = UPLOAD_DIR / unique_name
    file.save(target)
    is_image = suffix in {'.jpg', '.jpeg', '.png'}
    event = log_event('upload', f"Uploaded {'image' if is_image else 'video'}: {safe_name}", details={'stored_as': unique_name})
    return jsonify(ok=True, filename=unique_name, original_name=safe_name,
                   media_type='image' if is_image else 'video',
                   message='File uploaded. Press Analyse media to run YOLO inference.', event=event), 201

def load_yolo_session():
    if not MODEL_PATH.exists():
        raise FileNotFoundError(f'Model not found: {MODEL_PATH}. Copy your yolov8n.onnx into the models folder.')
    return ort.InferenceSession(str(MODEL_PATH), providers=['CPUExecutionProvider'])

def detect_people(session, frame, conf_threshold=0.35):
    """YOLOv8 ONNX person detection for standard [1,84,N] or [1,N,84] exports."""
    input_meta = session.get_inputs()[0]
    shape = input_meta.shape
    size = 640
    if len(shape) == 4 and isinstance(shape[2], int) and isinstance(shape[3], int):
        h, w = int(shape[2]), int(shape[3])
        if h > 0 and w > 0: size = max(h, w)
    original_h, original_w = frame.shape[:2]
    resized = cv2.resize(frame, (size, size))
    blob = cv2.cvtColor(resized, cv2.COLOR_BGR2RGB).astype(np.float32) / 255.0
    blob = np.transpose(blob, (2, 0, 1))[None, ...]
    outputs = session.run(None, {input_meta.name: blob})
    pred = np.asarray(outputs[0])
    if pred.ndim == 3: pred = pred[0]
    if pred.shape[0] < pred.shape[1] and pred.shape[0] <= 256: pred = pred.T
    if pred.ndim != 2 or pred.shape[1] < 5:
        raise RuntimeError(f'Unsupported YOLO ONNX output shape: {outputs[0].shape}')
    boxes, scores = [], []
    for row in pred:
        # YOLOv8 COCO export: cx,cy,w,h followed by class scores; class 0 is person.
        score = float(row[4]) if len(row) == 5 else float(row[4])
        class_id = 0
        if len(row) > 5:
            class_id = int(np.argmax(row[4:]))
            score = float(row[4 + class_id])
        if class_id != 0 or score < conf_threshold: continue
        cx, cy, bw, bh = [float(v) for v in row[:4]]
        x1 = int((cx - bw/2) * original_w / size); y1 = int((cy - bh/2) * original_h / size)
        x2 = int((cx + bw/2) * original_w / size); y2 = int((cy + bh/2) * original_h / size)
        x1=max(0,min(original_w-1,x1)); x2=max(0,min(original_w-1,x2))
        y1=max(0,min(original_h-1,y1)); y2=max(0,min(original_h-1,y2))
        if x2>x1 and y2>y1: boxes.append([x1,y1,x2-x1,y2-y1]); scores.append(score)
    keep = cv2.dnn.NMSBoxes(boxes, scores, conf_threshold, 0.45)
    result=[]
    if len(keep):
        for idx in np.array(keep).reshape(-1):
            x,y,w,h=boxes[int(idx)]; result.append({'box':[int(x),int(y),int(x+w),int(y+h)],'confidence':round(scores[int(idx)],3)})
    return result

def process_frame(session, frame):
    detections=detect_people(session, frame)
    annotated=frame.copy()
    for det in detections:
        x1,y1,x2,y2=det['box']
        cv2.rectangle(annotated,(x1,y1),(x2,y2),(65,105,239),2)
        cv2.putText(annotated,f"Person {det['confidence']:.2f}",(x1,max(20,y1-8)),cv2.FONT_HERSHEY_SIMPLEX,.55,(65,105,239),2)
    cv2.putText(annotated,f'People detected: {len(detections)}',(15,30),cv2.FONT_HERSHEY_SIMPLEX,.8,(0,180,120),2)
    return detections, annotated

@app.post('/api/analyze')
def analyze_media():
    data=request.get_json(silent=True) or {}
    filename=Path(str(data.get('filename',''))).name
    media=UPLOAD_DIR / filename
    if not filename or not media.exists(): return jsonify(ok=False,error='Upload the media first.'),400
    try: session=load_yolo_session()
    except Exception as exc: return jsonify(ok=False,error=str(exc)),400
    is_image=media.suffix.lower() in {'.jpg','.jpeg','.png'}
    cfg=read_config(); started=time.time()
    if is_image:
        frame=cv2.imread(str(media))
        if frame is None: return jsonify(ok=False,error='OpenCV could not read this image.'),400
        detections,annotated=process_frame(session,frame)
        output_name=f'annotated_{media.stem}.jpg'; cv2.imwrite(str(OUTPUT_DIR/output_name),annotated)
        peak=len(detections); frame_count=1; duration=0
    else:
        cap=cv2.VideoCapture(str(media))
        if not cap.isOpened(): return jsonify(ok=False,error='OpenCV could not open this video. Check its codec/format.'),400
        fps=cap.get(cv2.CAP_PROP_FPS) or 25
        width=int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)); height=int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        duration=(cap.get(cv2.CAP_PROP_FRAME_COUNT)/fps) if fps else 0
        output_name=f'annotated_{media.stem}.mp4'
        writer=cv2.VideoWriter(str(OUTPUT_DIR/output_name),cv2.VideoWriter_fourcc(*'mp4v'),max(1,min(fps,25)),(width,height))
        peak=0; frame_count=0; frame_index=0; sampled_detections=0
        # Process every 3rd frame for a practical CPU prototype; output still covers the clip.
        while True:
            ok,frame=cap.read()
            if not ok: break
            if frame_index % 3 == 0:
                dets,annotated=process_frame(session,frame); peak=max(peak,len(dets)); sampled_detections += len(dets); frame_count += 1
                last_annotated=annotated
            else:
                annotated=last_annotated if 'last_annotated' in locals() and last_annotated.shape==frame.shape else frame
            writer.write(annotated); frame_index+=1
        cap.release(); writer.release()
        if frame_count == 0: return jsonify(ok=False,error='No readable video frames found.'),400
    elapsed=round(time.time()-started,2)
    limit=int(cfg.get('max_passengers',40)); overcrowded=peak >= limit
    result={'filename':filename,'output_url':f'/outputs/{output_name}','media_type':'image' if is_image else 'video',
            'frames_analyzed':frame_count,'peak_people_detected_in_frame':peak,'configured_limit':limit,
            'crowd_status':'LIMIT REACHED' if overcrowded else 'NO LIMIT ALERT',
            'duration_seconds':round(duration,2),'processing_seconds':elapsed,
            'note':'Peak people visible in one frame is not verified onboard occupancy. Entry/exit counts require calibrated tracking zones.'}
    log_event('analysis_complete',f"Media analysis complete: peak {peak} people visible in one frame; {frame_count} sampled frames.",'warning' if overcrowded else 'info',result)
    if overcrowded and cfg.get('alert_at_limit',True):
        log_event('overcrowding_detected',f'Crowd threshold reached: {peak} people detected in one frame (configured limit {limit}).','warning',result)
    return jsonify(ok=True,result=result,alert_triggered=bool(overcrowded and cfg.get('alert_at_limit',True)))

@app.get('/outputs/<path:filename>')
def output_file(filename):
    return send_from_directory(OUTPUT_DIR, filename, as_attachment=False)

@app.delete('/api/events/<event_id>')
def delete_event(event_id):
    rows=[]
    deleted = False
    if EVENTS_PATH.exists():
        for line in EVENTS_PATH.read_text(encoding='utf-8').splitlines():
            try:
                item=json.loads(line)
                if item.get('id') == event_id:
                    deleted = True
                else:
                    rows.append(item)
            except json.JSONDecodeError: continue
    if not deleted:
        return jsonify(ok=False, error='Event not found.'), 404
    write_events(rows)
    return jsonify(ok=True,deleted=True)

@app.delete('/api/events')
def clear_events():
    write_events([])
    return jsonify(ok=True,message='Event history cleared.')

@app.get('/uploads/<path:filename>')
def uploaded_file(filename):
    return send_from_directory(UPLOAD_DIR, filename, as_attachment=False)

@app.post('/api/alert')
def alert():
    data = request.get_json(silent=True) or {}
    kind = str(data.get('type', 'manual'))[:40]
    message = str(data.get('message', 'Manual test alert'))[:500]
    level = str(data.get('level', 'warning'))[:20]
    event = log_event(kind, message, level, data.get('details', {}))
    # This logs the event locally. A real authority webhook is added only after its
    # exact API contract/authentication is provided and tested.
    return jsonify(ok=True, event=event, authority_forwarded=False,
                   note='Saved locally. Configure and implement your authority website API before claiming delivery.'), 201

@app.post('/api/iot/test')
def iot_test():
    cfg = read_config()
    # Safe by default: no live relay/door command is sent from this demo.
    event = log_event('iot_test', 'IoT integration test requested; no physical door command sent.', 'info',
                      {'mode': cfg.get('iot_mode', 'mock')})
    return jsonify(ok=True, mode=cfg.get('iot_mode', 'mock'), event=event,
                   message='Mock test only. No door actuator was operated. Use the device maker’s documented interface and an independent safety controller for real hardware.')

@app.get('/api/events')
def events():
    return jsonify(events=get_events(100))

@app.post('/api/authority/bus-allocation')
def authority_bus_allocation():
    callback_token = os.environ.get('AUTHORITY_CALLBACK_TOKEN', '').strip()
    if not callback_token:
        return jsonify(ok=False, error='Authority callback is not configured.'), 503

    provided_token = request.headers.get('Authorization', '')
    if not hmac.compare_digest(provided_token, f'Bearer {callback_token}'):
        return jsonify(ok=False, error='Unauthorized authority callback.'), 401

    payload = request.get_json(silent=True)
    if not isinstance(payload, dict) or payload.get('status') not in ('allocated', 'not_allocated'):
        return jsonify(
            ok=False,
            error="Provide status as either 'allocated' or 'not_allocated'."
        ), 400

    allocated = payload['status'] == 'allocated'
    config = read_config()
    bus_id = str(payload.get('bus_id') or config['bus_id']).strip()[:80]
    route = str(payload.get('route') or '').strip()[:100]
    message = str(payload.get('message') or '').strip()[:500]
    outcome = 'Bus allocated' if allocated else 'Bus not allocated'
    summary = f'{outcome}: {bus_id}'
    if route:
        summary += f' · Route {route}'
    if message:
        summary += f' · {message}'

    event = log_event(
        'authority_bus_allocated' if allocated else 'authority_bus_not_allocated',
        summary,
        'info' if allocated else 'warning',
        {
            'bus_id': bus_id,
            'route': route,
            'status': payload['status'],
            'allocation_id': str(payload.get('allocation_id') or '')[:100]
        }
    )
    return jsonify(ok=True, event_id=event['id'], status=payload['status']), 201

@app.get('/api/authority/allocations')
def authority_allocations():
    allocation_events = [
        event for event in get_events(500)
        if event.get('type') in ('authority_bus_allocated', 'authority_bus_not_allocated')
    ]
    return jsonify(events=allocation_events[:50])

@app.get('/health')
def health():
    return jsonify(status='ok', service='TN Transmit Smart Crowd AI starter')


# ---------- DRIVER ALERT HISTORY DATABASE ----------

DB_PATH = DATA_DIR / "tn_transmit.db"


def init_alert_logs():
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS alert_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                vehicle_id TEXT,
                route TEXT,
                event_type TEXT,
                severity TEXT,
                location TEXT,
                message TEXT,
                result TEXT NOT NULL,
                error TEXT
            )
        """)


def save_alert_log(payload, result, error=None):
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.execute("""
            INSERT INTO alert_logs (
                timestamp, vehicle_id, route, event_type,
                severity, location, message, result, error
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            datetime.now().astimezone().isoformat(timespec="seconds"),
            str(payload.get("vehicle_id", ""))[:100],
            str(payload.get("route", ""))[:100],
            str(payload.get("event_type", ""))[:100],
            str(payload.get("severity", ""))[:30],
            str(payload.get("stop_name", ""))[:200],
            str(payload.get("message", ""))[:2000],
            result,
            str(error)[:1000] if error else None
        ))
        return cursor.lastrowid


# ---------- DRIVER REPORT API ----------

@app.post('/api/driver-report')
def driver_report():
    payload = request.get_json(silent=True) or {}

    required = ['vehicle_id', 'route', 'event_type']
    missing = [key for key in required if not str(payload.get(key, '')).strip()]

    if missing:
        return jsonify(
            ok=False,
            error='Missing required fields: ' + ', '.join(missing)
        ), 400

    # Save the incoming report locally, even if authority delivery fails.
    cfg = read_config()
    webhook_url = str(cfg.get('authority_webhook_url', '')).strip()
    token = str(cfg.get('authority_api_token', '')).strip()

    if not webhook_url:
        error = (
            'Authority webhook URL is not configured. '
            'The report was saved locally but was NOT delivered to the authority.'
        )
        alert_id = save_alert_log(payload, 'NOT_SENT', error)
        log_event(
            'driver_report_not_sent',
            error,
            'warning',
            {'alert_id': alert_id, 'vehicle_id': payload.get('vehicle_id')}
        )
        return jsonify(
            ok=False,
            saved_locally=True,
            alert_id=alert_id,
            error=error
        ), 503

    # Attempt delivery to the configured authority endpoint.
    try:
        body = json.dumps(payload).encode('utf-8')
        headers = {'Content-Type': 'application/json'}

        if token:
            headers['Authorization'] = f'Bearer {token}'

        req = urllib.request.Request(
            webhook_url,
            data=body,
            headers=headers,
            method='POST'
        )

        with urllib.request.urlopen(req, timeout=10) as response:
            status_code = response.status
            response_body = response.read(1000).decode(
                'utf-8', errors='replace'
            )

        if not 200 <= status_code < 300:
            raise RuntimeError(
                f'Authority returned HTTP {status_code}: {response_body}'
            )

        alert_id = save_alert_log(payload, 'DELIVERED', None)
        log_event(
            'driver_report_delivered',
            'Authority endpoint accepted the report.',
            'info',
            {'alert_id': alert_id, 'vehicle_id': payload.get('vehicle_id')}
        )

        return jsonify(
            ok=True,
            alert_id=alert_id,
            message='Authority endpoint accepted the report.'
        ), 200

    except Exception as exc:
        error = f'{type(exc).__name__}: {str(exc)}'
        alert_id = save_alert_log(payload, 'FAILED', error)
        log_event(
            'driver_report_failed',
            'Driver report could not be delivered to the authority.',
            'warning',
            {'alert_id': alert_id, 'error': error}
        )

        return jsonify(
            ok=False,
            saved_locally=True,
            alert_id=alert_id,
            error='Report saved locally, but authority delivery failed: ' + error
        ), 502


# ---------- VIEW SAVED ALERT LOGS ----------

@app.get('/api/alert-logs')
def alert_logs():
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute("""
            SELECT * FROM alert_logs
            ORDER BY id DESC
            LIMIT 200
        """).fetchall()

    return jsonify(ok=True, logs=[dict(row) for row in rows])


# Initialize the database BEFORE starting Flask.
init_alert_logs()


if __name__ == '__main__':
    host = os.environ.get('HOST', '127.0.0.1')
    port = int(os.environ.get('PORT', '5000'))
    print(f'TN Transmit Smart Crowd AI starter: http://{host}:{port}')
    app.run(
        host=host,
        port=port,
        debug=os.environ.get('FLASK_DEBUG') == '1'
    )
