"""Tool: termux_device — Android device control via Termux:API.

Only registered when running on Android (Termux).
Provides 35 actions covering telephony, camera, audio, sensors, notifications,
system controls, and app management.
"""

from __future__ import annotations

import asyncio
import json
import shlex

from openlama.tools.registry import register_tool
from openlama.logger import get_logger

logger = get_logger("tool.termux")

_TIMEOUT = 15  # seconds per command


async def _run(cmd: str, timeout: int = _TIMEOUT) -> str:
    """Run a Termux API command and return stdout."""
    try:
        proc = await asyncio.create_subprocess_shell(
            cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        out = stdout.decode("utf-8", errors="replace").strip()
        err = stderr.decode("utf-8", errors="replace").strip()
        if proc.returncode != 0 and err:
            return f"Error: {err}"
        return out or "(no output)"
    except asyncio.TimeoutError:
        return f"Error: command timed out after {timeout}s"
    except Exception as e:
        return f"Error: {e}"


def _json_result(raw: str) -> str:
    """Try to pretty-format JSON output from Termux API."""
    try:
        data = json.loads(raw)
        return json.dumps(data, indent=2, ensure_ascii=False)
    except (json.JSONDecodeError, TypeError):
        return raw


async def _execute(args: dict) -> str:
    action = args.get("action", "")

    # ── Telephony ──
    if action == "call":
        number = args.get("phone_number", "")
        if not number:
            return "Error: phone_number is required"
        return await _run(f"termux-telephony-call {shlex.quote(number)}")

    if action == "sms_send":
        number = args.get("phone_number", "")
        message = args.get("message", "")
        if not number or not message:
            return "Error: phone_number and message are required"
        return await _run(f"termux-sms-send -n {shlex.quote(number)} {shlex.quote(message)}")

    if action == "sms_list":
        count = args.get("count", 10)
        raw = await _run(f"termux-sms-list -l {count} -t inbox")
        return _json_result(raw)

    if action == "call_log":
        count = args.get("count", 10)
        raw = await _run(f"termux-call-log -l {count}")
        return _json_result(raw)

    if action == "contacts":
        raw = await _run("termux-contact-list")
        return _json_result(raw)

    # ── Camera ──
    if action == "camera_photo":
        cam = args.get("camera_id", 0)
        path = args.get("file_path", "/data/data/com.termux/files/home/photo.jpg")
        await _run(f"termux-camera-photo -c {cam} {shlex.quote(path)}")
        return f"Photo saved to {path}"

    if action == "camera_info":
        raw = await _run("termux-camera-info")
        return _json_result(raw)

    # ── Audio / Media ──
    if action == "mic_record":
        path = args.get("file_path", "/data/data/com.termux/files/home/recording.m4a")
        duration = args.get("duration", 5)
        await _run(f"termux-microphone-record -f {shlex.quote(path)} -l {duration}", timeout=duration + 5)
        return f"Audio recorded to {path} ({duration}s)"

    if action == "media_play":
        path = args.get("file_path", "")
        if not path:
            return "Error: file_path is required"
        return await _run(f"termux-media-player play {shlex.quote(path)}")

    if action == "media_stop":
        return await _run("termux-media-player stop")

    if action == "tts_speak":
        text = args.get("text", "")
        if not text:
            return "Error: text is required"
        return await _run(f"termux-tts-speak {shlex.quote(text)}", timeout=30)

    if action == "tts_engines":
        raw = await _run("termux-tts-engines")
        return _json_result(raw)

    if action == "volume_get":
        raw = await _run("termux-volume")
        return _json_result(raw)

    if action == "volume_set":
        stream = args.get("volume_stream", "music")
        level = args.get("volume_level", 7)
        return await _run(f"termux-volume {shlex.quote(stream)} {level}")

    # ── Notifications / UI ──
    if action == "notification":
        title = args.get("title", "openlama")
        message = args.get("message", "")
        nid = args.get("notification_id", "openlama-notify")
        cmd = f"termux-notification --id {shlex.quote(nid)} --title {shlex.quote(title)}"
        if message:
            cmd += f" --content {shlex.quote(message)}"
        return await _run(cmd)

    if action == "notification_remove":
        nid = args.get("notification_id", "")
        if not nid:
            return "Error: notification_id is required"
        return await _run(f"termux-notification-remove {shlex.quote(nid)}")

    if action == "toast":
        message = args.get("message", "")
        if not message:
            return "Error: message is required"
        return await _run(f"termux-toast {shlex.quote(message)}")

    if action == "vibrate":
        duration = args.get("duration", 1000)
        return await _run(f"termux-vibrate -d {duration}")

    if action == "dialog":
        dtype = args.get("text", "text")
        raw = await _run(f"termux-dialog {shlex.quote(dtype)}", timeout=60)
        return _json_result(raw)

    # ── Sensors / Location ──
    if action == "location":
        raw = await _run("termux-location -p gps", timeout=30)
        return _json_result(raw)

    if action == "sensor_list":
        raw = await _run("termux-sensor -l")
        return _json_result(raw)

    if action == "sensor_read":
        name = args.get("sensor_name", "")
        count = args.get("count", 1)
        if not name:
            return "Error: sensor_name is required (use sensor_list first)"
        raw = await _run(f"termux-sensor -s {shlex.quote(name)} -n {count}")
        return _json_result(raw)

    if action == "battery":
        raw = await _run("termux-battery-status")
        return _json_result(raw)

    # ── System Controls ──
    if action == "brightness":
        level = args.get("brightness_level", 128)
        return await _run(f"termux-brightness {level}")

    if action == "torch":
        enabled = args.get("torch_enabled", True)
        return await _run(f"termux-torch {'on' if enabled else 'off'}")

    if action == "clipboard_get":
        return await _run("termux-clipboard-get")

    if action == "clipboard_set":
        text = args.get("text", "")
        if not text:
            return "Error: text is required"
        return await _run(f"termux-clipboard-set {shlex.quote(text)}")

    if action == "wallpaper":
        path = args.get("file_path", "")
        if not path:
            return "Error: file_path is required"
        return await _run(f"termux-wallpaper -f {shlex.quote(path)}")

    if action == "wifi_info":
        raw = await _run("termux-wifi-connectioninfo")
        return _json_result(raw)

    if action == "wifi_scan":
        raw = await _run("termux-wifi-scaninfo")
        return _json_result(raw)

    # ── File / Share ──
    if action == "share":
        path = args.get("file_path", "")
        if not path:
            return "Error: file_path is required"
        return await _run(f"termux-share {shlex.quote(path)}")

    if action == "download":
        url = args.get("url", "")
        if not url:
            return "Error: url is required"
        return await _run(f"termux-download {shlex.quote(url)}")

    # ── App Control ──
    if action == "app_launch":
        package = args.get("app_package", "")
        if not package:
            return "Error: app_package is required"
        return await _run(f"am start --user 0 -n {shlex.quote(package)}")

    if action == "app_list":
        return await _run("pm list packages -3")

    # ── Misc ──
    if action == "ir_transmit":
        text = args.get("text", "")
        if not text:
            return "Error: frequency and pattern required in text (e.g. '38000 100,50,100')"
        return await _run(f"termux-infrared-transmit {text}")

    if action == "fingerprint":
        raw = await _run("termux-fingerprint", timeout=30)
        return _json_result(raw)

    return f"Unknown action: {action}"


register_tool(
    name="termux_device",
    description=(
        "Control the Android device hardware and software. "
        "Actions: call, sms_send, sms_list, call_log, contacts, "
        "camera_photo, camera_info, mic_record, media_play, media_stop, "
        "tts_speak, tts_engines, volume_get, volume_set, "
        "notification, notification_remove, toast, vibrate, dialog, "
        "location, sensor_list, sensor_read, battery, "
        "brightness, torch, clipboard_get, clipboard_set, wallpaper, "
        "wifi_info, wifi_scan, share, download, "
        "app_launch, app_list, ir_transmit, fingerprint"
    ),
    parameters={
        "type": "object",
        "required": ["action"],
        "properties": {
            "action": {
                "type": "string",
                "description": "The device action to perform",
                "enum": [
                    "call", "sms_send", "sms_list", "call_log", "contacts",
                    "camera_photo", "camera_info",
                    "mic_record", "media_play", "media_stop",
                    "tts_speak", "tts_engines", "volume_get", "volume_set",
                    "notification", "notification_remove", "toast", "vibrate", "dialog",
                    "location", "sensor_list", "sensor_read", "battery",
                    "brightness", "torch", "clipboard_get", "clipboard_set", "wallpaper",
                    "wifi_info", "wifi_scan",
                    "share", "download",
                    "app_launch", "app_list",
                    "ir_transmit", "fingerprint",
                ],
            },
            "phone_number": {"type": "string", "description": "Phone number for call/sms actions"},
            "message": {"type": "string", "description": "Message text for sms_send, notification, toast"},
            "camera_id": {"type": "integer", "description": "Camera ID (0=rear, 1=front)"},
            "file_path": {"type": "string", "description": "File path for camera, mic, media, wallpaper, share"},
            "duration": {"type": "integer", "description": "Duration in seconds (mic_record) or ms (vibrate)"},
            "sensor_name": {"type": "string", "description": "Sensor name from sensor_list"},
            "text": {"type": "string", "description": "Text for tts_speak, clipboard_set, dialog type, ir pattern"},
            "title": {"type": "string", "description": "Title for notification"},
            "notification_id": {"type": "string", "description": "Notification ID"},
            "volume_stream": {"type": "string", "description": "Audio stream: music, ring, alarm, notification"},
            "volume_level": {"type": "integer", "description": "Volume level (0-15)"},
            "brightness_level": {"type": "integer", "description": "Screen brightness (0-255)"},
            "torch_enabled": {"type": "boolean", "description": "Torch on (true) or off (false)"},
            "app_package": {"type": "string", "description": "Android package/activity name"},
            "url": {"type": "string", "description": "URL for download action"},
            "count": {"type": "integer", "description": "Number of items for list/read actions"},
        },
    },
    execute=_execute,
)
