from __future__ import annotations

import io
import os
import time
from datetime import datetime

import qrcode
from flask import Flask, jsonify, request, send_file


app = Flask(__name__)
SESSION_ID = f"local-{int(time.time())}"


@app.get("/health")
def health():
    return jsonify(
        {
            "ok": True,
            "service": "wa-bridge-local",
            "session": SESSION_ID,
            "auth_required": False,
            "status": "ready",
            "ts": datetime.utcnow().isoformat() + "Z",
        }
    )


@app.get("/status")
def status():
    return jsonify(
        {
            "ok": True,
            "instance_id": SESSION_ID,
            "connected": True,
            "status": "paired",
        }
    )


@app.get("/qr")
def qr():
    payload = f"wa-local-bridge-session:{SESSION_ID}"
    image = qrcode.make(payload)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    buffer.seek(0)
    return send_file(buffer, mimetype="image/png")


@app.post("/send-message")
def send_message():
    data = request.get_json(silent=True) or {}
    phone = str(data.get("phone", "")).strip()
    text = str(data.get("text", "")).strip()
    if not phone or not text:
        return jsonify({"ok": False, "error": "phone and text are required"}), 400

    return jsonify(
        {
            "ok": True,
            "message_id": f"mock-{int(time.time() * 1000)}",
            "phone": phone,
            "text": text,
            "status": "queued",
        }
    )


if __name__ == "__main__":
    port = int(os.getenv("BRIDGE_PORT", "3000"))
    app.run(host="0.0.0.0", port=port)
