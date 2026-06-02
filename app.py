import os
import json
import logging
import uuid
from pathlib import Path
from datetime import datetime

# Intel CPU optimization: set thread environment before any PyTorch/TTS imports
cpu_count = os.cpu_count() or 8
os.environ.setdefault("OMP_NUM_THREADS", str(cpu_count))
os.environ.setdefault("MKL_NUM_THREADS", str(cpu_count))
os.environ.setdefault("NUMEXPR_NUM_THREADS", str(cpu_count))

from flask import (
    Flask, request, jsonify, render_template,
    send_file, url_for, session
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
app.secret_key = os.urandom(24).hex()

BASE_DIR = Path(__file__).parent
UPLOAD_DIR = BASE_DIR / "uploads"
OUTPUT_DIR = BASE_DIR / "output"
VOICE_PROFILES_DIR = BASE_DIR / "voice_profiles"

for d in [UPLOAD_DIR, OUTPUT_DIR, VOICE_PROFILES_DIR, TTS_CACHE_DIR]:
    d.mkdir(exist_ok=True)

tts_engine = VoiceCloneEngine()


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
    if not data:
        return jsonify({"error": "No data provided"}), 400

    text = data.get("text", "").strip()
    voice_id = data.get("voice_id", session.get("last_voice_id"))
    language = data.get("language", "zh-cn")

    if not text:
        return jsonify({"error": "Text cannot be empty"}), 400

    if not voice_id:
        return jsonify({"error": "No voice sample found. Please upload a voice sample first."}), 400

    speaker_path = VOICE_PROFILES_DIR / f"{voice_id}.wav"
    if not speaker_path.exists():
        for ext in ('.mp3', '.flac', '.ogg'):
            candidate = VOICE_PROFILES_DIR / f"{voice_id}{ext}"
            if candidate.exists():
                speaker_path = candidate
                break
        else:
            return jsonify({"error": "Voice sample not found. Please upload again."}), 404

    try:
        output_filename = f"{uuid.uuid4().hex}.wav"
        output_path = str(OUTPUT_DIR / output_filename)

        result_path = tts_engine.clone_voice(
            text=text,
            speaker_audio_path=str(speaker_path),
            language=language,
            output_path=output_path
        )

        return jsonify({
            "success": True,
            "audio_url": url_for("download_audio", filename=output_filename),
            "filename": output_filename,
            "message": "Speech generated successfully"
        })

    except Exception as e:
        logger.error(f"Synthesis error: {e}", exc_info=True)
        return jsonify({"error": f"Synthesis failed: {str(e)}"}), 500


@app.route("/api/stream", methods=["POST"])
def synthesize_stream():
    data = request.get_json()
    if not data:
        return jsonify({"error": "No data provided"}), 400

    text = data.get("text", "").strip()
    voice_id = data.get("voice_id", session.get("last_voice_id"))
    language = data.get("language", "zh-cn")

    if not text:
        return jsonify({"error": "Text cannot be empty"}), 400

    if not voice_id:
        return jsonify({"error": "No voice sample found. Please upload a voice sample first."}), 400

    speaker_path = VOICE_PROFILES_DIR / f"{voice_id}.wav"
    if not speaker_path.exists():
        for ext in ('.mp3', '.flac', '.ogg'):
            candidate = VOICE_PROFILES_DIR / f"{voice_id}{ext}"
            if candidate.exists():
                speaker_path = candidate
                break
        else:
            return jsonify({"error": "Voice sample not found. Please upload again."}), 404

    try:
        audio_buffer, sample_rate = tts_engine.clone_voice_stream(
            text=text,
            speaker_audio_path=str(speaker_path),
            language=language
        )

        from flask import Response
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
        return jsonify({"error": f"Synthesis failed: {str(e)}"}), 500


@app.route("/api/delete-voice/<voice_id>", methods=["DELETE"])
def delete_voice(voice_id):
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
    for ext in ('.wav', '.mp3', '.flac', '.ogg'):
        path = VOICE_PROFILES_DIR / f"{voice_id}{ext}"
        if path.exists():
            return send_file(str(path), mimetype=f"audio/{ext[1:]}")
    return jsonify({"error": "Voice not found"}), 404


@app.route("/output/<filename>")
def download_audio(filename):
    path = OUTPUT_DIR / filename
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
    parser = argparse.ArgumentParser(description="TTS Voice Clone Tool")
    parser.add_argument("--host", default="0.0.0.0", help="Host to bind to")
    parser.add_argument("--port", type=int, default=8080, help="Port to bind to")
    parser.add_argument("--debug", action="store_true", help="Enable debug mode")
    args = parser.parse_args()

    logger.info(f"Starting TTS Voice Clone Tool on {args.host}:{args.port}")
    app.run(host=args.host, port=args.port, debug=args.debug)