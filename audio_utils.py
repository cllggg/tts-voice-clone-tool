import os
import uuid
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

ALLOWED_EXTENSIONS = {'.wav', '.mp3', '.flac', '.ogg', '.m4a', '.webm'}
MAX_FILE_SIZE = 50 * 1024 * 1024

def allowed_file(filename):
    ext = Path(filename).suffix.lower()
    return ext in ALLOWED_EXTENSIONS

def validate_audio_file(file_path):
    if not os.path.exists(file_path):
        return False, "File does not exist."

    file_size = os.path.getsize(file_path)
    if file_size == 0:
        return False, "File is empty."
    if file_size > MAX_FILE_SIZE:
        return False, f"File too large ({file_size / 1024 / 1024:.1f}MB). Max: {MAX_FILE_SIZE / 1024 / 1024}MB."

    ext = Path(file_path).suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        return False, f"Unsupported format: {ext}"

    return True, "OK"

def get_audio_duration(file_path):
    try:
        import soundfile as sf
        info = sf.info(file_path)
        duration = info.duration
        return duration
    except Exception:
        try:
            import subprocess
            result = subprocess.run(
                ['ffprobe', '-v', 'error', '-show_entries', 'format=duration',
                 '-of', 'default=noprint_wrappers=1:nokey=1', file_path],
                capture_output=True, text=True, timeout=10
            )
            if result.returncode == 0 and result.stdout.strip():
                return float(result.stdout.strip())
        except Exception:
            pass
    return None

def save_uploaded_file(uploaded_file, upload_dir):
    os.makedirs(upload_dir, exist_ok=True)

    ext = Path(uploaded_file.filename).suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        ext = '.wav'

    filename = f"{uuid.uuid4().hex}{ext}"
    file_path = os.path.join(upload_dir, filename)

    uploaded_file.save(file_path)
    return file_path

def convert_to_wav(input_path, output_dir=None):
    ext = Path(input_path).suffix.lower()

    if ext == '.wav':
        return input_path

    if output_dir is None:
        output_dir = os.path.dirname(input_path)

    os.makedirs(output_dir, exist_ok=True)
    stem = Path(input_path).stem
    output_path = os.path.join(output_dir, f"{stem}.wav")

    if os.path.exists(output_path):
        logger.info(f"Using existing converted file: {output_path}")
        return output_path

    try:
        from pydub import AudioSegment
        audio = AudioSegment.from_file(input_path)
        audio = audio.set_frame_rate(24000).set_channels(1)
        audio.export(output_path, format="wav")
        logger.info(f"Converted {input_path} to {output_path} using pydub")
        return output_path
    except Exception as e:
        logger.warning(f"pydub conversion failed: {e}")

    try:
        import soundfile as sf
        data, sr = sf.read(input_path)
        sf.write(output_path, data, sr)
        logger.info(f"Converted {input_path} to {output_path} using soundfile")
        return output_path
    except Exception as e:
        logger.warning(f"soundfile conversion failed: {e}")

    try:
        import subprocess
        result = subprocess.run(
            ['afconvert', input_path, output_path, '-f', 'WAVE', '-d', 'LEI16@24000'],
            capture_output=True, timeout=30
        )
        if result.returncode == 0:
            logger.info(f"Converted {input_path} to {output_path} using afconvert")
            return output_path
        else:
            logger.warning(f"afconvert failed: {result.stderr.decode()}")
    except FileNotFoundError:
        logger.warning("afconvert not available")
    except Exception as e:
        logger.warning(f"afconvert conversion failed: {e}")

    try:
        import subprocess
        import wave
        result = subprocess.run(
            ['ffmpeg', '-i', input_path, '-f', 's16le', '-acodec', 'pcm_s16le', '-ar', '24000', '-ac', '1', '-y', '-'],
            capture_output=True, timeout=30
        )
        if result.returncode == 0:
            raw_data = result.stdout
            with wave.open(output_path, 'wb') as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)
                wf.setframerate(24000)
                wf.writeframes(raw_data)
            logger.info(f"Converted {input_path} to {output_path} using ffmpeg raw")
            return output_path
        else:
            raise RuntimeError(f"ffmpeg failed: {result.stderr.decode()}")
    except FileNotFoundError:
        raise RuntimeError(
            "ffmpeg is required for audio conversion. Install it via: brew install ffmpeg"
        )

def cleanup_file(file_path):
    try:
        if os.path.exists(file_path):
            os.remove(file_path)
            logger.debug(f"Cleaned up: {file_path}")
    except Exception as e:
        logger.warning(f"Failed to cleanup {file_path}: {e}")