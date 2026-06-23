import gi
gi.require_version("Gst", "1.0")
gi.require_version("GstRtspServer", "1.0")

from gi.repository import Gst, GstRtspServer, GLib

from fastapi import FastAPI
import uvicorn
import threading
import time

Gst.init(None)

control_app = FastAPI()


class CameraStreamController:
    def __init__(self):
        self.media = None
        self.pipeline = None
        self.enabled = True
        self.lock = threading.Lock()

    def set_media(self, media):
        with self.lock:
            self.media = media
            self.pipeline = media.get_element()
            print("[RTSP] media registered")

    def clear_media(self):
        with self.lock:
            self.media = None
            self.pipeline = None
            print("[RTSP] media cleared")

    def stop_streaming(self):
        with self.lock:
            print("[RTSP] stop requested")
            self.enabled = False

            if self.pipeline is not None:
                self.pipeline.set_state(Gst.State.NULL)
                time.sleep(0.3)

            self.media = None
            self.pipeline = None

        return {"status": "stopped"}

    def start_streaming(self):
        with self.lock:
            print("[RTSP] start requested")
            self.enabled = True

        return {"status": "enabled"}

    def status(self):
        with self.lock:
            return {
                "enabled": self.enabled,
                "has_media": self.media is not None,
                "has_pipeline": self.pipeline is not None,
            }


controller = CameraStreamController()


class CameraMediaFactory(GstRtspServer.RTSPMediaFactory):
    def __init__(self, device="/dev/video0"):
        super().__init__()

        self.pipeline_str = (
            f"( v4l2src device={device} ! "
            "videoconvert ! "
            "video/x-raw,format=I420,width=640,height=480,framerate=30/1 ! "
            "x264enc tune=zerolatency bitrate=500 speed-preset=superfast key-int-max=30 ! "
            "h264parse config-interval=1 ! "
            "rtph264pay name=pay0 pt=96 config-interval=1 )"
        )

        self.set_launch(self.pipeline_str)
        self.set_shared(True)

    def do_configure(self, media):
        print("[RTSP] media configured")

        if not controller.enabled:
            print("[RTSP] streaming disabled")
            media.get_element().set_state(Gst.State.NULL)
            return

        controller.set_media(media)
        media.connect("unprepared", self.on_unprepared)

    def on_unprepared(self, media):
        print("[RTSP] media unprepared")
        controller.clear_media()


class MyRtspServer:
    def __init__(self):
        self.server = GstRtspServer.RTSPServer()
        self.server.set_address("100.92.189.49")
        self.server.set_service("8554")

        factory = CameraMediaFactory(device="/dev/video0")

        mounts = self.server.get_mount_points()
        mounts.add_factory("/live", factory)

        self.server.attach(None)

        print("[RTSP] server started: rtsp://100.92.189.49:8554/live")


@control_app.post("/rtsp/stop")
def rtsp_stop():
    return controller.stop_streaming()


@control_app.post("/rtsp/start")
def rtsp_start():
    return controller.start_streaming()


@control_app.get("/rtsp/status")
def rtsp_status():
    return controller.status()


def run_control_server():
    uvicorn.run(
        control_app,
        host="127.0.0.1",
        port=9000,
        log_level="warning",
    )


if __name__ == "__main__":
    rtsp_server = MyRtspServer()

    control_thread = threading.Thread(target=run_control_server, daemon=True)
    control_thread.start()

    loop = GLib.MainLoop()
    loop.run()
