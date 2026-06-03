import os
import re
import json
import hashlib
import logging
import uuid
import shutil
from pathlib import Path
from datetime import datetime

# Intel CPU optimization: set thread environment before any PyTorch/TTS imports
cpu_count = os.cpu_count() or 8
os.environ.setdefault("OMP_NUM_THREADS", str(cpu_count))
os.environ.setdefault("MKL_NUM_THREADS", str(cpu_count))
os.environ.setdefault("NUMEXPR_NUM_THREADS", str(cpu_count))

from flask import (
    Flask, request, jsonify, render_template,
    send_file, url_for, session, Response
)

from tts_engine import VoiceCloneEngine
from audio_utils import (
    allowed_file, validate_audio_file, save_uploaded_file,
    convert_to_wav, get_audio_duration, cleanup_file
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Use project-local directory for TTS model cache to avoid permission issues
TTS_CACHE_DIR = Path(__file__).parent / ".tts_cache"
os.environ.setdefault("TTS_HOME", str(TTS_CACHE_DIR))

app = Flask(__name__)
app.config['TEMPLATES_AUTO_RELOAD'] = True
app.secret_key = os.urandom(24).hex()

BASE_DIR = Path(__file__).parent
UPLOAD_DIR = BASE_DIR / "uploads"
OUTPUT_DIR = BASE_DIR / "output"
VOICE_PROFILES_DIR = BASE_DIR / "voice_profiles"
CACHE_DIR = BASE_DIR / "cache"

for d in [UPLOAD_DIR, OUTPUT_DIR, VOICE_PROFILES_DIR, TTS_CACHE_DIR, CACHE_DIR]:
    d.mkdir(exist_ok=True)

tts_engine = VoiceCloneEngine()

# --- Cache Manager ---
MAX_CACHE_SIZE_MB = 500  # Maximum cache size in MB
CACHE_MAX_AGE_DAYS = 7   # Cache entries older than this are removed


def _get_cache_key(text, voice_id, language, speed):
    """Generate a deterministic cache key from synthesis parameters."""
    raw = f"{text}|{voice_id}|{language}|{speed}"
    return hashlib.md5(raw.encode()).hexdigest()


def _check_cache(cache_key):
    """Check if a cached result exists and is still valid."""
    cache_path = CACHE_DIR / f"{cache_key}.wav"
    if cache_path.exists():
        # Update access time for LRU-like eviction
        cache_path.touch()
        return str(cache_path)
    return None


def _save_cache(cache_key, wav_path):
    """Save a synthesis result to cache with eviction."""
    dest = CACHE_DIR / f"{cache_key}.wav"
    shutil.copy2(wav_path, str(dest))

    # Evict old entries if cache exceeds size limit
    _evict_cache_if_needed()


def _evict_cache_if_needed():
    """Remove oldest cache entries if total size exceeds limit."""
    cache_files = sorted(CACHE_DIR.glob("*.wav"), key=lambda f: f.stat().st_atime)
    total_size = sum(f.stat().st_size for f in cache_files) / (1024 * 1024)

    while total_size > MAX_CACHE_SIZE_MB and len(cache_files) > 1:
        oldest = cache_files.pop(0)
        size_mb = oldest.stat().st_size / (1024 * 1024)
        oldest.unlink(missing_ok=True)
        total_size -= size_mb

    # Also remove expired entries
    now = datetime.now().timestamp()
    for f in CACHE_DIR.glob("*.wav"):
        age_days = (now - f.stat().st_mtime) / 86400
        if age_days > CACHE_MAX_AGE_DAYS:
            f.unlink(missing_ok=True)


def _clean_old_cache():
    """Remove expired cache entries on startup."""
    now = datetime.now().timestamp()
    for f in CACHE_DIR.glob("*.wav"):
        age_days = (now - f.stat().st_mtime) / 86400
        if age_days > CACHE_MAX_AGE_DAYS:
            f.unlink(missing_ok=True)


# Clean old cache on startup
_clean_old_cache()


def _find_voice_path(voice_id):
    """Find voice file by ID, checking multiple extensions."""
    for ext in ('.wav', '.mp3', '.flac', '.ogg'):
        path = VOICE_PROFILES_DIR / f"{voice_id}{ext}"
        if path.exists():
            return path
    return None


def _sanitize_filename(name):
    """Remove path traversal characters and keep only safe filename chars."""
    return re.sub(r'[^\w\-]', '', name)


def _validate_synthesis_request(data):
    """Validate synthesis request parameters.
    
    Returns:
        (text, voice_id, language, speed, speaker_path) on success
        (None, None, None, None, error_response_tuple) on failure
    """
    if not data:
        return (None, None, None, None, (jsonify({"error": "请求数据为空"}), 400))

    text = data.get("text", "").strip()
    voice_id = data.get("voice_id", session.get("last_voice_id"))
    language = data.get("language", "zh-cn")
    speed = float(data.get("speed", 1.0))

    if not text:
        return (None, None, None, None, (jsonify({"error": "文字内容不能为空"}), 400))
    if len(text) > 5000:
        return (None, None, None, None, (jsonify({"error": f"文字长度不能超过 5000 字符（当前 {len(text)} 字符）"}), 400))
    if speed < 0.5 or speed > 2.0:
        return (None, None, None, None, (jsonify({"error": "语速必须在 0.5 到 2.0 之间"}), 400))

    valid_langs = [l["code"] for l in tts_engine.list_supported_languages()]
    if language not in valid_langs:
        return (None, None, None, None, (jsonify({"error": f"不支持的语言: {language}"}), 400))

    if not voice_id:
        return (None, None, None, None, (jsonify({"error": "请先上传语音样本"}), 400))

    speaker_path = _find_voice_path(voice_id)
    if not speaker_path:
        return (None, None, None, None, (jsonify({"error": "声纹样本未找到，请重新上传"}), 404))

    return (text, voice_id, language, speed, speaker_path)


@app.route("/")
def index():
    languages = tts_engine.list_supported_languages()
    return render_template("index.html", languages=languages)


@app.route("/api/voices", methods=["GET"])
def list_voices():
    voices = []
    if VOICE_PROFILES_DIR.exists():
        for f in VOICE_PROFILES_DIR.iterdir():
            if f.suffix.lower() in ('.wav', '.mp3', '.flac', '.ogg'):
                mtime = datetime.fromtimestamp(f.stat().st_mtime)
                voices.append({
                    "id": f.stem,
                    "name": f.stem,
                    "filename": f.name,
                    "path": str(f),
                    "created": mtime.isoformat(),
                    "created_str": mtime.strftime("%Y-%m-%d %H:%M"),
                    "size": f.stat().st_size
                })
    return jsonify({"voices": voices})


@app.route("/api/upload", methods=["POST"])
def upload_audio():
    if "audio" not in request.files:
        return jsonify({"error": "No audio file provided"}), 400

    file = request.files["audio"]
    if file.filename == "":
        return jsonify({"error": "No file selected"}), 400

    if not allowed_file(file.filename):
        return jsonify({"error": f"Unsupported file type. Allowed: {'.wav, .mp3, .flac, .ogg, .m4a'}"}), 400

    try:
        file_path = save_uploaded_file(file, str(UPLOAD_DIR))

        is_valid, msg = validate_audio_file(file_path)
        if not is_valid:
            cleanup_file(file_path)
            return jsonify({"error": msg}), 400

        wav_path = convert_to_wav(file_path, str(UPLOAD_DIR))
        if wav_path != file_path:
            cleanup_file(file_path)

        duration = get_audio_duration(wav_path)
        if duration is not None and duration < 1.0:
            cleanup_file(wav_path)
            return jsonify({"error": "Audio too short. Please provide at least 1 second of voice sample."}), 400

        voice_id = Path(wav_path).stem
        profile_path = VOICE_PROFILES_DIR / Path(wav_path).name
        os.rename(wav_path, str(profile_path))

        session["last_voice_id"] = voice_id

        return jsonify({
            "success": True,
            "voice_id": voice_id,
            "filename": Path(wav_path).name,
            "duration": round(duration, 1) if duration else None,
            "message": "Voice sample uploaded successfully"
        })

    except Exception as e:
        logger.error(f"Upload error: {e}", exc_info=True)
        return jsonify({"error": f"Upload failed: {str(e)}"}), 500


@app.route("/api/synthesize", methods=["POST"])
def synthesize():
    data = request.get_json()
    text, voice_id, language, speed, speaker_path = _validate_synthesis_request(data)
    if text is None:
        return speaker_path  # speaker_path is the error response tuple

    # --- Cache check ---
    cache_key = _get_cache_key(text, voice_id, language, speed)
    cached = _check_cache(cache_key)
    if cached:
        logger.info(f"Cache hit for key: {cache_key[:12]}...")
        output_filename = f"{cache_key}.wav"
        shutil.copy2(cached, str(OUTPUT_DIR / output_filename))
        return jsonify({
            "success": True,
            "audio_url": url_for("download_audio", filename=output_filename),
            "filename": output_filename,
            "message": "语音生成成功（缓存命中）",
            "cached": True
        })

    try:
        output_filename = f"{uuid.uuid4().hex}.wav"
        output_path = str(OUTPUT_DIR / output_filename)

        result_path = tts_engine.clone_voice(
            text=text,
            speaker_audio_path=str(speaker_path),
            language=language,
            output_path=output_path,
            speed=speed
        )

        # Save to cache for future requests
        _save_cache(cache_key, result_path)

        return jsonify({
            "success": True,
            "audio_url": url_for("download_audio", filename=output_filename),
            "filename": output_filename,
            "message": "语音生成成功",
            "cached": False
        })

    except Exception as e:
        logger.error(f"Synthesis error: {e}", exc_info=True)
        return jsonify({"error": f"合成失败: {str(e)}"}), 500


@app.route("/api/stream", methods=["POST"])
def synthesize_stream():
    data = request.get_json()
    text, _voice_id, language, speed, speaker_path = _validate_synthesis_request(data)
    if text is None:
        return speaker_path

    try:
        audio_buffer, sample_rate = tts_engine.clone_voice_stream(
            text=text,
            speaker_audio_path=str(speaker_path),
            language=language,
            speed=speed
        )

        return Response(
            audio_buffer.read(),
            mimetype="audio/wav",
            headers={
                "Content-Disposition": "inline",
                "X-Sample-Rate": str(sample_rate)
            }
        )

    except Exception as e:
        logger.error(f"Stream synthesis error: {e}", exc_info=True)
        return jsonify({"error": f"合成失败: {str(e)}"}), 500


@app.route("/api/stream-chunks", methods=["POST"])
def stream_chunks():
    """Stream synthesis: each sentence is sent as a separate WAV chunk as soon as it's ready.
    
    The response is a binary stream where each chunk is:
    [4 bytes: int32 big-endian chunk length] [WAV data]
    
    The frontend reads and plays each chunk immediately upon arrival.
    """
    data = request.get_json()
    text, _voice_id, language, speed, speaker_path = _validate_synthesis_request(data)
    if text is None:
        return speaker_path

    def generate():
        import struct
        try:
            for chunk_info in tts_engine.clone_voice_sentences(
                text=text,
                speaker_audio_path=str(speaker_path),
                language=language,
                speed=speed
            ):
                wav_data = chunk_info["audio"].read()
                # Prefix with 4-byte big-endian length
                yield struct.pack(">I", len(wav_data))
                yield wav_data
        except Exception as e:
            logger.error(f"Stream chunks error: {e}", exc_info=True)
            # Send error as a special chunk (length 0 signals error)
            error_msg = json.dumps({"error": str(e)}).encode()
            yield struct.pack(">I", len(error_msg) | 0x80000000)  # High bit set = error
            yield error_msg

    return Response(
        generate(),
        mimetype="application/octet-stream",
        headers={
            "X-Content-Type-Options": "nosniff",
            "Cache-Control": "no-cache",
        }
    )


@app.route("/api/delete-voice/<voice_id>", methods=["DELETE"])
def delete_voice(voice_id):
    voice_id = _sanitize_filename(voice_id)
    if not voice_id:
        return jsonify({"error": "无效的声纹 ID"}), 400
    deleted = False
    for ext in ('.wav', '.mp3', '.flac', '.ogg'):
        path = VOICE_PROFILES_DIR / f"{voice_id}{ext}"
        if path.exists():
            cleanup_file(str(path))
            deleted = True

    if deleted:
        return jsonify({"success": True, "message": "Voice deleted"})
    return jsonify({"error": "Voice not found"}), 404


@app.route("/api/voice-audio/<voice_id>")
def voice_audio(voice_id):
    voice_id = _sanitize_filename(voice_id)
    if not voice_id:
        return jsonify({"error": "无效的声纹 ID"}), 400
    for ext in ('.wav', '.mp3', '.flac', '.ogg'):
        path = VOICE_PROFILES_DIR / f"{voice_id}{ext}"
        if path.exists():
            return send_file(str(path), mimetype=f"audio/{ext[1:]}")
    return jsonify({"error": "Voice not found"}), 404


@app.route("/output/<filename>")
def download_audio(filename):
    safe_name = _sanitize_filename(filename)
    path = OUTPUT_DIR / safe_name
    if not path.exists():
        return jsonify({"error": "File not found"}), 404
    return send_file(str(path), mimetype="audio/wav")


@app.route("/api/clear-outputs", methods=["POST"])
def clear_outputs():
    for f in OUTPUT_DIR.iterdir():
        if f.is_file() and f.name != '.gitkeep':
            cleanup_file(str(f))
    return jsonify({"success": True, "message": "Output files cleared"})


@app.route("/api/status")
def status():
    return jsonify({
        "model_loaded": tts_engine.is_loaded(),
        "device": tts_engine.device,
        "voices_count": len([f for f in VOICE_PROFILES_DIR.iterdir() if f.suffix.lower() in ('.wav', '.mp3', '.flac', '.ogg')]),
        "outputs_count": len([f for f in OUTPUT_DIR.iterdir() if f.is_file() and f.name != '.gitkeep'])
    })


if __name__ == "__main__":
    import argparse
    import threading
    parser = argparse.ArgumentParser(description="TTS Voice Clone Tool")
    parser.add_argument("--host", default="0.0.0.0", help="Host to bind to")
    parser.add_argument("--port", type=int, default=8080, help="Port to bind to")
    parser.add_argument("--debug", action="store_true", help="Enable debug mode")
    parser.add_argument("--warmup", action="store_true", default=True,
                        help="Run model warm-up after startup (default: True)")
    parser.add_argument("--no-warmup", action="store_false", dest="warmup",
                        help="Skip model warm-up")
    args = parser.parse_args()

    logger.info(f"Starting TTS Voice Clone Tool on {args.host}:{args.port}")

    def warmup():
        """Run a short warm-up synthesis to trigger model graph compilation."""
        try:
            first_voice = next(VOICE_PROFILES_DIR.glob("*.wav"), None)
            if not first_voice:
                first_voice = next(VOICE_PROFILES_DIR.glob("*.mp3"), None)
            if first_voice and args.warmup:
                logger.info("Running model warm-up (this may take 10-30s)...")
                tts_engine.clone_voice(
                    text="这是一个预热测试。",
                    speaker_audio_path=str(first_voice),
                    language="zh-cn",
                    speed=1.0
                )
                logger.info("Model warm-up complete!")
        except Exception as e:
            logger.warning(f"Model warm-up skipped: {e}")

    threading.Thread(target=warmup, daemon=True).start()

    app.run(host=args.host, port=args.port, debug=args.debug)