from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

import serial
import threading
import subprocess
import time
import os
import signal
from pathlib import Path

app = FastAPI()

BASE_DIR = Path(__file__).resolve().parent
RTSP_SERVER_SCRIPT = BASE_DIR / "g_server.py"

ARDUINO_PORTS = {
    "light1": "/dev/ttyACM0",
    "light2": "/dev/ttyACM1",
}

BAUDRATE = 115200

USB_CAMERA_DEVICE = "/dev/video0"
CAPTURE_RESOLUTION = "3840x2160"
#CAPTURE_RESOLUTION = "1920x1080"
CAPTURE_DIR = Path("/tmp/pi_captures")
CAPTURE_DIR.mkdir(exist_ok=True)

serial_devices = {}
serial_lock = threading.Lock()
capture_lock = threading.Lock()

rtsp_process = None

light_state = {
    "light1": False,
    "light2": False,
}

class CommandRequest(BaseModel):
    target: str = "both"
    command: str

import requests
RTSP_CONTROL_URL = "http://127.0.0.1:9000"

def stop_rtsp_cleanly():
    try:
        r = requests.post(f"{RTSP_CONTROL_URL}/rtsp/stop", timeout=3)
        print("[RTSP-CONTROL] stop:", r.text)
    except Exception as e:
        print("[RTSP-CONTROL] stop failed:", e)

    time.sleep(0.8)


def start_rtsp_cleanly():
    try:
        r = requests.post(f"{RTSP_CONTROL_URL}/rtsp/start", timeout=3)
        print("[RTSP-CONTROL] start:", r.text)
    except Exception as e:
        print("[RTSP-CONTROL] start failed:", e)

    time.sleep(0.5)
    
def start_rtsp_server():
    global rtsp_process

    if rtsp_process is not None and rtsp_process.poll() is None:
        print("[RTSP] already running")
        return

    print("[RTSP] starting g_server.py")
    rtsp_process = subprocess.Popen(
        ["python3", str(RTSP_SERVER_SCRIPT)],
        cwd=str(BASE_DIR),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.STDOUT,
    )

    time.sleep(1.0)


#def stop_rtsp_server():
#    global rtsp_process

#    print("[RTSP] stopping g_server.py")

#    if rtsp_process is not None and rtsp_process.poll() is None:
#        rtsp_process.terminate()

#        try:
#            rtsp_process.wait(timeout=3)
#        except subprocess.TimeoutExpired:
#            rtsp_process.kill()
#            rtsp_process.wait(timeout=2)

    # 혹시 수동 실행된 g_server.py가 남아 있으면 정리
#    subprocess.run(
#        ["pkill", "-f", str(RTSP_SERVER_SCRIPT)],
#        stdout=subprocess.DEVNULL,
#        stderr=subprocess.DEVNULL,
#    )

#    rtsp_process = None
#    time.sleep(0.7)

def stop_rtsp_server():
    global rtsp_process

    print("[RTSP] stopping g_server.py")

    if rtsp_process is not None and rtsp_process.poll() is None:
        rtsp_process.terminate()

        try:
            rtsp_process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            rtsp_process.kill()
            rtsp_process.wait(timeout=2)

    subprocess.run(
        ["pkill", "-9", "-f", str(RTSP_SERVER_SCRIPT)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    rtsp_process = None

    if not wait_until_camera_free(USB_CAMERA_DEVICE, timeout=5.0):
        raise RuntimeError(f"{USB_CAMERA_DEVICE} is still busy after stopping RTSP")
        
        
def wait_until_camera_free(device="/dev/video0", timeout=5.0):
    start = time.time()

    while time.time() - start < timeout:
        result = subprocess.run(
            ["fuser", device],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )

        # fuser 출력이 없으면 아무 프로세스도 device를 안 쓰는 상태
        if result.stdout.strip() == "":
            print(f"[CAMERA] {device} is free")
            return True

        print(f"[CAMERA] waiting for release: {result.stdout.strip()}")
        time.sleep(0.3)

    return False

@app.on_event("startup")
def startup():
    for name, port in ARDUINO_PORTS.items():
        try:
            ser = serial.Serial(port, BAUDRATE, timeout=1)
            time.sleep(2)
            serial_devices[name] = ser
            print(f"[OK] {name} connected at {port}")
        except Exception as e:
            print(f"[ERROR] {name} open failed: {e}")

    # command server가 RTSP 서버도 같이 관리
    start_rtsp_server()


@app.on_event("shutdown")
def shutdown():
    stop_rtsp_server()

    for ser in serial_devices.values():
        try:
            ser.close()
        except Exception:
            pass


def get_targets(target: str):
    if target == "both":
        return list(ARDUINO_PORTS.keys())

    if target in ARDUINO_PORTS:
        return [target]

    raise HTTPException(status_code=400, detail=f"Invalid target: {target}")


def send_arduino_command(target: str, command: str):
    targets = get_targets(target)
    results = {}

    with serial_lock:
        for name in targets:
            ser = serial_devices.get(name)

            if ser is None or not ser.is_open:
                results[name] = "not connected"
                continue

            try:
                if command.strip() == "LED_ON":
                    msg = "from machine import Pin; Pin(5, Pin.OUT).value(1)\r\n"
                elif command.strip() == "STOP":
                    msg = "from machine import Pin; Pin(5, Pin.OUT).value(0)\r\n"
                else:
                    msg = command.strip() + "\r\n"

                ser.write(msg.encode("utf-8"))
                ser.flush()

                response = ser.readline().decode("utf-8", errors="ignore").strip()
                results[name] = response or "sent"

            except Exception as e:
                results[name] = f"error: {e}"

    return results


def set_light_state(target: str, is_on: bool):
    for name in get_targets(target):
        light_state[name] = is_on


def are_all_target_lights_on(target: str):
    return all(light_state.get(name, False) for name in get_targets(target))


def capture_4k_usb_camera():
    timestamp = int(time.time() * 1000)
    image_path = CAPTURE_DIR / f"capture_{timestamp}.jpg"

    cmd = [
        "fswebcam",
        "-d", USB_CAMERA_DEVICE,
        "-r", CAPTURE_RESOLUTION,
        "--no-banner",
        "--fps", "5",
        "--jpeg", "95",
        str(image_path),
    ]

    subprocess.run(cmd, check=True, timeout=15)

    if not image_path.exists():
        raise RuntimeError("image capture failed")

    return image_path


@app.get("/health")
def health():
    return {
        "status": "ok",
        "connected_arduinos": list(serial_devices.keys()),
        "light_state": light_state,
        "rtsp_running": rtsp_process is not None and rtsp_process.poll() is None,
    }


@app.post("/command")
def command(req: CommandRequest):
    target = req.target.strip()
    cmd = req.command.upper().strip()

    print(f"Received {target}: {cmd}")

    if cmd == "LED_ON":
        result = send_arduino_command(target, "LED_ON")
        set_light_state(target, True)

        return {
            "command": "LED_ON",
            "target": target,
            "result": result,
            "light_state": light_state,
        }

    if cmd == "STOP":
        result = send_arduino_command(target, "STOP")
        set_light_state(target, False)

        return {
            "command": "STOP",
            "target": target,
            "result": result,
            "light_state": light_state,
        }

    if cmd == "START":
        with capture_lock:
            light_was_already_on = are_all_target_lights_on(target)

            try:
                if not light_was_already_on:
                    on_result = send_arduino_command(target, "LED_ON")
                    set_light_state(target, True)
                    time.sleep(1.5)
                else:
                    on_result = "lights already on"

                # 핵심: RTSP가 /dev/video0을 잡고 있으므로 먼저 종료
                #stop_rtsp_server()
                stop_rtsp_cleanly()
                image_path = capture_4k_usb_camera()
                #time.sleep(1.0)
                # 촬영 후 RTSP 재시작
                #start_rtsp_server()
                start_rtsp_cleanly()

                off_result = send_arduino_command(target, "STOP")
                set_light_state(target, False)

                return FileResponse(
                    path=image_path,
                    media_type="image/jpeg",
                    filename=image_path.name,
                    headers={
                        "X-Command": "START",
                        "X-Target": target,
                        "X-Light-Was-Already-On": str(light_was_already_on),
                        "X-Light-On-Result": str(on_result),
                        "X-Light-Off-Result": str(off_result),
                    },
                )

            except Exception as e:
                try:
                    start_rtsp_server()
                    send_arduino_command(target, "STOP")
                    set_light_state(target, False)
                except Exception:
                    pass

                raise HTTPException(status_code=500, detail=str(e))

    raise HTTPException(status_code=400, detail=f"Unknown command: {cmd}")
