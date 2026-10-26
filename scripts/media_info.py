"""Length of an audio/video file in seconds: ffprobe when it is installed, else parsed from `ffmpeg -i` (the Mac app
ships ffmpeg only)."""
import re, shutil, subprocess  # nosec B404 - argument lists only


def duration(path) -> float:
    if shutil.which('ffprobe'):
        out = subprocess.run(['ffprobe', '-v', 'error', '-show_entries', 'format=duration', '-of', 'csv=p=0', str(path)],  # nosec B603 B607
                             capture_output=True, text=True, timeout=60).stdout.strip()
        try: return float(out)
        except ValueError: pass
    err = subprocess.run(['ffmpeg', '-hide_banner', '-i', str(path)], capture_output=True, text=True, timeout=60).stderr  # nosec B603 B607
    m = re.search(r'Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)', err)
    if not m: raise ValueError(f'cannot read the length of {path}')
    return int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3))
