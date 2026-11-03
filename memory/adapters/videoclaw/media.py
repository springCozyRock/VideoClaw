"""Native generation, collision-free reference uploads, frame extraction and sampling."""

import base64
import io
import json
import math
from pathlib import Path
import shutil
import subprocess
import uuid


class MediaIO:
    def __init__(self, agent, settings):
        self.agent, self.settings = agent, settings
        self.video_model = settings.get("video_first_frame_model") or settings.get(
            "video_model"
        )
        self.image_model = settings.get("image_it2i_model")
        self.text_image_model = settings.get("image_t2i_model")
        if not all((self.video_model, self.image_model, self.text_image_model)):
            raise ValueError(
                "Configure video_first_frame_model, image_it2i_model and image_t2i_model"
            )
        self._samples = {}

    def render_frame(self, segment, prompt, references, target):
        # DashScope uploads a batch under one object prefix; repeated end.png names
        # from distinct history directories can collide before model submission.
        from memory.assets.files import media

        target = Path(target)
        folder = target.parent / "upload_references" / target.stem
        folder.mkdir(parents=True, exist_ok=True)
        copies, manifest = [], []
        for index, source in enumerate(references):
            original = media(source)
            destination = folder / (
                str(index) + "-" + uuid.uuid4().hex + Path(source).suffix
            )
            shutil.copyfile(source, destination)
            duplicate = media(destination)
            if original["sha256"] != duplicate["sha256"]:
                raise ValueError("Upload copy changed reference bytes")
            copies.append(str(destination))
            manifest.append({"original": original, "upload_copy": duplicate})
        target.with_suffix(".references.json").write_text(
            json.dumps(manifest, indent=2)
        )
        return self._render_frame(segment, prompt, copies, target)

    def _render_frame(self, segment, prompt, references, target):
        from models.image_client import ImageClient

        self.agent._check_cancel()
        paths = ImageClient().generate_image(
            prompt=prompt,
            image_paths=references or None,
            model=self.image_model if references else self.text_image_model,
            save_dir=str(target.parent),
            session_id=self.settings["session_id"],
            video_ratio=self.settings.get("video_ratio", "16:9"),
            resolution="720P",
        )
        if not paths:
            raise RuntimeError("Image provider returned no candidate")
        if Path(paths[0]).resolve() != target.resolve():
            shutil.copyfile(paths[0], target)
        return str(target)

    def render_video(self, segment, prompt, begin, target):
        from models.video_client import VideoClient

        self.agent._check_cancel()
        if int(segment.duration) != segment.duration:
            raise ValueError("VideoClaw provider expects whole-second duration")
        VideoClient().generate_video(
            prompt=prompt,
            image_path=begin,
            save_path=str(target),
            model=self.video_model,
            duration=int(segment.duration),
            video_ratio=self.settings.get("video_ratio", "16:9"),
            resolution=self.settings.get("video_resolution", "720P"),
            prompt_extend=False,
            watermark=False,
        )
        probe = json.loads(
            subprocess.check_output(
                [
                    "ffprobe",
                    "-v",
                    "error",
                    "-show_format",
                    "-show_streams",
                    "-of",
                    "json",
                    str(target),
                ],
                text=True,
            )
        )
        if not any(s.get("codec_type") == "video" for s in probe["streams"]):
            raise ValueError("Generated artifact contains no video stream")
        if abs(float(probe["format"]["duration"]) - segment.duration) > 0.6:
            raise ValueError("Generated duration differs from planned duration")
        return str(target)

    def boundaries(self, video, directory):
        directory.mkdir(parents=True, exist_ok=True)
        begin, end = directory / "begin.png", directory / "end.png"
        subprocess.run(
            [
                "ffmpeg",
                "-nostdin",
                "-v",
                "error",
                "-y",
                "-i",
                video,
                "-frames:v",
                "1",
                str(begin),
            ],
            check=True,
        )
        # Decode the last second and continually overwrite, leaving the last decoded frame.
        subprocess.run(
            [
                "ffmpeg",
                "-nostdin",
                "-v",
                "error",
                "-y",
                "-sseof",
                "-1",
                "-i",
                video,
                "-an",
                "-update",
                "1",
                str(end),
            ],
            check=True,
        )
        return [str(begin), str(end)]

    def render_with_end(self, segment, prompt, begin, end, target):
        from models.video_client import VideoClient

        self.agent._check_cancel()
        if int(segment.duration) != segment.duration:
            raise ValueError("Require integer duration")
        VideoClient().generate_video(
            prompt=prompt,
            image_path=begin,
            last_image_path=end,
            save_path=str(target),
            model=self.video_model,
            duration=int(segment.duration),
            video_ratio=self.settings.get("video_ratio", "16:9"),
            resolution=self.settings.get("video_resolution", "720P"),
            prompt_extend=False,
            watermark=False,
        )
        probe = json.loads(
            subprocess.check_output(
                [
                    "ffprobe",
                    "-v",
                    "error",
                    "-show_format",
                    "-show_streams",
                    "-of",
                    "json",
                    str(target),
                ],
                text=True,
            )
        )
        if not any(s.get("codec_type") == "video" for s in probe["streams"]):
            raise ValueError("Output has no video stream")
        if abs(float(probe["format"]["duration"]) - segment.duration) > 0.6:
            raise ValueError("Unexpected video duration")
        return str(target)

    def _sample_video(self, path):
        key = str(Path(path).resolve())
        if key in self._samples:
            return self._samples[key]
        import cv2
        from PIL import Image

        cap = cv2.VideoCapture(key)
        try:
            fps, n = cap.get(cv2.CAP_PROP_FPS), int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
            if fps <= 0 or n <= 0:
                raise ValueError("Cannot decode video")
            duration, rate = n / fps, 4
            if duration > 60:
                raise ValueError("Per-segment observation limit is 60 seconds")
            frames, times = [], []
            for i in range(max(1, math.ceil(duration * rate))):
                index = min(n - 1, round(i * fps / rate))
                cap.set(cv2.CAP_PROP_POS_FRAMES, index)
                ok, bgr = cap.read()
                if not ok:
                    raise ValueError("Missing sampled frame")
                image = Image.fromarray(cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB))
                image.thumbnail((640, 640))
                buf = io.BytesIO()
                image.save(buf, format="JPEG", quality=85)
                frames.append(
                    "data:image/jpeg;base64,"
                    + base64.b64encode(buf.getvalue()).decode()
                )
                times.append(index / fps)
            result = (
                {"type": "video", "video": frames, "fps": rate},
                {
                    "path": key,
                    "duration": duration,
                    "frame_timestamps_seconds": times,
                    "sample_rate": rate,
                },
            )
            self._samples[key] = result
            return result
        finally:
            cap.release()
