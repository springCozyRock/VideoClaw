import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from memory.world.references.shots import extract_shot_ends


class ShotTests(unittest.TestCase):
    @unittest.skipUnless(
        shutil.which("ffmpeg"), "ffmpeg required for actual shot-end decoding"
    )
    def test_detected_shot_ends_are_actual_pre_cut_frames(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            video = root / "cuts.mp4"
            subprocess.run(
                [
                    "ffmpeg",
                    "-nostdin",
                    "-v",
                    "error",
                    "-f",
                    "lavfi",
                    "-i",
                    "color=red:s=64x64:r=10:d=1",
                    "-f",
                    "lavfi",
                    "-i",
                    "color=blue:s=64x64:r=10:d=1",
                    "-filter_complex",
                    "[0:v][1:v]concat=n=2:v=1:a=0",
                    "-c:v",
                    "mpeg4",
                    str(video),
                ],
                check=True,
            )
            result = extract_shot_ends(video, root / "frames")
            self.assertEqual(len(result["candidates"]), 2)
            self.assertAlmostEqual(result["candidates"][0]["frame_time"], 0.9, places=1)
            self.assertNotEqual(
                result["candidates"][0]["media"]["sha256"],
                result["candidates"][1]["media"]["sha256"],
            )
