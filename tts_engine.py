import os
import re
import tempfile
import logging
import warnings
from pathlib import Path

warnings.filterwarnings("ignore", category=FutureWarning)

logger = logging.getLogger(__name__)

class VoiceCloneEngine:
    def __init__(self, model_name="tts_models/multilingual/multi-dataset/xtts_v2", device=None):
        self.model_name = model_name
        self.device = device
        self._model = None
        self._speaker_encoder = None
        self._is_loaded = False

    @property
    def model(self):
        if self._model is None:
            self._load_model()
        return self._model

    def _load_model(self):
        try:
            from TTS.api import TTS
        except ImportError:
            raise ImportError(
                "Coqui TTS is not installed. Please run: pip install TTS"
            )

        import torch
        import torch.backends.mkldnn

        logger.info(f"Loading TTS model: {self.model_name}")

        if self.device is None:
            if torch.cuda.is_available():
                self.device = "cuda"
            else:
                self.device = "cpu"

        # CPU optimizations for Intel Mac
        if self.device == "cpu":
            core_count = os.cpu_count() or 8
            torch.set_num_threads(core_count)
            if torch.backends.mkldnn.is_available():
                try:
                    torch.backends.mkldnn.set_benchmark(True)
                    logger.info(f"Enabled MKLDNN benchmark on CPU ({core_count} threads)")
                except AttributeError:
                    logger.info("MKLDNN available but set_benchmark not supported in this PyTorch version")

        use_cuda = (self.device == "cuda")
        self._model = TTS(self.model_name, gpu=use_cuda)

        self._is_loaded = True
        logger.info(f"TTS model loaded successfully on {self.device}")

    def _preprocess_text(self, text, language="zh-cn"):
        text = text.strip()
        if not text:
            return text

        # Collapse multiple spaces into one (keep single spaces)
        text = re.sub(r' +', ' ', text)

        # Normalize newlines: treat multiple newlines as paragraph breaks
        text = re.sub(r'\n{3,}', '\n\n', text)

        # Ensure sentence-ending punctuation has trailing newline for paragraph separation
        # For very long blocks without paragraph breaks, insert natural splits
        if '\n\n' not in text and len(text) > 500:
            sentences = re.split(r'(?<=[。！？\.\!\?])\s*', text)
            lines = []
            chunk_len = 0
            for sent in sentences:
                sent = sent.strip()
                if not sent:
                    continue
                chunk_len += len(sent)
                lines.append(sent)
                if chunk_len > 400 and sent[-1] in ('。', '！', '？', '.', '!', '?'):
                    lines.append('')
                    chunk_len = 0
            text = '\n'.join(lines)

        # Normalize common formatting issues that confuse prosody
        replacements = [
            (r'\u2018|\u2019', "'"),    # smart single quotes -> straight
            (r'\u201c|\u201d', '"'),    # smart double quotes -> straight
            (r'\u2014+', '——'),         # em-dashes
            (r'\u2026+', '……'),         # ellipsis
        ]
        for pattern, repl in replacements:
            text = re.sub(pattern, repl, text)

        logger.debug(f"Text preprocessed ({language}): {len(text)} chars")
        return text

    def _validate_audio(self, audio_path):
        if not os.path.exists(audio_path):
            raise FileNotFoundError(f"Audio file not found: {audio_path}")

        ext = Path(audio_path).suffix.lower()
        if ext not in ('.wav', '.mp3', '.flac', '.ogg'):
            raise ValueError(f"Unsupported audio format: {ext}. Use WAV, MP3, FLAC, or OGG.")

    def clone_voice(self, text, speaker_audio_path, language="zh-cn", output_path=None):
        self._validate_audio(speaker_audio_path)

        if not text or not text.strip():
            raise ValueError("Text cannot be empty.")

        text = self._preprocess_text(text, language)

        if output_path is None:
            fd, output_path = tempfile.mkstemp(suffix=".wav")
            os.close(fd)

        output_path = str(output_path)
        if not output_path.lower().endswith('.wav'):
            output_path += '.wav'

        supported_langs = ["en", "zh-cn", "ja", "ko", "fr", "de", "it", "pt", "es", "ru", "nl", "tr", "ar", "hi"]
        if language not in supported_langs:
            logger.warning(f"Language '{language}' may not be supported. Supported: {supported_langs}")

        logger.info(f"Generating speech for text ({language}): {text[:50]}...")
        self.model.tts_to_file(
            text=text,
            file_path=output_path,
            speaker_wav=speaker_audio_path,
            language=language,
            split_sentences=True
        )

        return output_path

    def clone_voice_stream(self, text, speaker_audio_path, language="zh-cn"):
        self._validate_audio(speaker_audio_path)

        if not text or not text.strip():
            raise ValueError("Text cannot be empty.")

        text = self._preprocess_text(text, language)

        logger.info(f"Streaming speech for text ({language}): {text[:50]}...")
        wav = self.model.tts(
            text=text,
            speaker_wav=speaker_audio_path,
            language=language,
            split_sentences=True
        )

        import numpy as np
        import scipy.io.wavfile as wavfile
        import io

        sample_rate = 24000
        wav_np = np.array(wav, dtype=np.float32)
        wav_int16 = (wav_np * 32767).astype(np.int16)

        buffer = io.BytesIO()
        wavfile.write(buffer, sample_rate, wav_int16)
        buffer.seek(0)

        return buffer, sample_rate

    def list_supported_languages(self):
        return [
            {"code": "en", "name": "English"},
            {"code": "zh-cn", "name": "Chinese (Simplified)"},
            {"code": "ja", "name": "Japanese"},
            {"code": "ko", "name": "Korean"},
            {"code": "fr", "name": "French"},
            {"code": "de", "name": "German"},
            {"code": "it", "name": "Italian"},
            {"code": "pt", "name": "Portuguese"},
            {"code": "es", "name": "Spanish"},
            {"code": "ru", "name": "Russian"},
            {"code": "nl", "name": "Dutch"},
            {"code": "tr", "name": "Turkish"},
            {"code": "ar", "name": "Arabic"},
            {"code": "hi", "name": "Hindi"},
        ]

    def is_loaded(self):
        return self._is_loaded