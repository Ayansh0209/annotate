"""Generate original synthetic media. No annotations or scores are seeded."""
import hashlib
import math
import sqlite3
import struct
import subprocess
import shutil
import sys
import wave
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.db import connect, initialize


def audio(path, variant, seconds=8):
    rate = 22050
    with wave.open(str(path), 'wb') as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(rate)
        samples = []
        for i in range(rate * seconds):
            t = i / rate
            if variant == 0:
                phase = t % 2
                value = math.sin(2 * math.pi * 440 * t) * 0.3 if phase < .5 else 0
            else:
                phase = t % 4
                value = (math.sin(2 * math.pi * 261.63 * t) + math.sin(2 * math.pi * 329.63 * t) + math.sin(2 * math.pi * 392 * t)) * .12 * max(0, 1 - phase / 2) if phase < 2 else 0
            samples.append(struct.pack('<h', int(value * 32767)))
        out.writeframes(b''.join(samples))


def video(path, variant, seconds=8):
    from PIL import Image, ImageDraw
    width, height, fps = 640, 360, 24
    frames = []
    for i in range(seconds * fps):
        t = i / fps
        frame = Image.new('RGB', (width, height), '#cbd6bd' if variant == 0 else '#e4dac4')
        draw = ImageDraw.Draw(frame)
        if variant == 0:
            draw.ellipse((465, 36, 540, 111), fill='#f5e7b1')
            draw.ellipse((-90, 210, 490, 600), fill='#92ae87')
            draw.ellipse((230, 230, 800, 600), fill='#5e8969')
            x = 55 + (t / seconds) * 490
            y = 250 - abs(math.sin(t * 2)) * 95
            draw.ellipse((x - 20, y - 20, x + 20, y + 20), fill='#d4905d', outline='#be7950', width=2)
        else:
            draw.rectangle((0, 270, width, height), fill='#b4bea2')
            for j, color in enumerate(['#6e947a', '#bf8b64', '#8d97ac']):
                x = 110 + j * 150
                y = 220 - min(max(t - j * 1.6, 0), 1) * 55
                draw.rounded_rectangle((x, y, x + 90, y + 70), 8, fill=color)
        draw.text((23, 20), 'ANNOTATEQA / ORIGINAL PRACTICE MEDIA', fill='#465e46')
        draw.text((23, 330), f'{t:04.1f}s     Synthetic scene. Not study evidence.', fill='#314d3b')
        frames.append(frame)
    try:
        import imageio_ffmpeg
        command = [imageio_ffmpeg.get_ffmpeg_exe(), '-y', '-f', 'rawvideo', '-vcodec', 'rawvideo', '-s', f'{width}x{height}', '-pix_fmt', 'rgb24', '-r', str(fps), '-i', '-', '-an', '-vcodec', 'libx264', '-pix_fmt', 'yuv420p', '-movflags', '+faststart', str(path)]
        process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        for frame in frames:
            process.stdin.write(frame.tobytes())
        process.stdin.close()
        diagnostic = process.stderr.read()
        if process.wait() != 0:
            raise RuntimeError(diagnostic.decode(errors='replace')[-500:])
    except ImportError:
        # Optional local fallback when OpenCV is preinstalled. VP8 is browser compatible.
        import cv2
        import numpy as np
        path = path.with_suffix('.webm')
        out = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*'VP80'), fps, (width, height))
        if not out.isOpened():
            raise RuntimeError('No video encoder available. Install imageio-ffmpeg.')
        for frame in frames:
            out.write(cv2.cvtColor(np.array(frame), cv2.COLOR_RGB2BGR))
        out.release()
    return path


def main():
    folder = ROOT / 'data' / 'media'
    folder.mkdir(parents=True, exist_ok=True)
    database = ROOT / 'data' / 'annotateqa.sqlite3'
    initialize(database)
    specs = [('practice-video-01', 'A moving shape', 'video', 0),
             ('practice-video-02', 'Three objects in motion', 'video', 1),
             ('practice-audio-01', 'A repeating sound', 'audio', 0),
             ('practice-audio-02', 'Notes and silence', 'audio', 1)]
    with closing(connect(database)) as db, db:
        for cid, title, kind, variant in specs:
            if db.execute('SELECT 1 FROM clips WHERE id=?', (cid,)).fetchone():
                continue
            if db.execute("SELECT locked_at FROM studies WHERE id='practice'").fetchone()[0]:
                raise RuntimeError('Practice dataset is locked; seeding would invalidate its snapshot.')
            path = folder / (cid + ('.mp4' if kind == 'video' else '.wav'))
            bundled = next((ROOT / 'demo').glob(cid + '.*'), None) if (ROOT / 'demo').exists() else None
            if bundled:
                path = folder / bundled.name
                shutil.copyfile(bundled, path)
            elif kind == 'video':
                path = video(path, variant)
            else:
                audio(path, variant)
            mime = 'video/webm' if path.suffix == '.webm' else ('video/mp4' if kind == 'video' else 'audio/wav')
            db.execute('INSERT INTO clips VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',
                       (cid, 'practice', title, kind, 'Original work', 'CC0 1.0 (synthetic)', 'AnnotateQA procedural media generator', 8, path.name, mime, hashlib.sha256(path.read_bytes()).hexdigest(), datetime.now(timezone.utc).isoformat()))
            print(f'Created practice clip: {title}')
    print('Practice media ready. No annotations, captions or scores were created.')


if __name__ == '__main__':
    main()
