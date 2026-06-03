# 技术实现详解

本文档深入介绍声纹克隆 TTS 工具的核心技术原理，包括 Flask Web 服务架构、Coqui XTTS 模型使用、音频处理流程等。

---

## 目录

1. [Flask Web 服务工作原理](#flask-web-服务工作原理)
   - 1.1 Flask 框架概述
   - 1.2 路由与请求处理
   - 1.3 API 接口设计
   - 1.4 静态资源与模板渲染
   - 1.5 错误处理与日志
   - 1.6 合成结果缓存
   - 1.7 统一请求验证
   - 1.8 安全加固

2. [Coqui XTTS 使用与注意事项](#coqui-xtts-使用与注意事项)
   - 2.1 XTTS 模型架构
   - 2.2 声纹克隆原理
   - 2.3 多语言支持机制
   - 2.4 模型加载与缓存
   - 2.5 性能优化策略
   - 2.6 文本预处理与分句
   - 2.7 语速控制
   - 2.8 常见问题与解决方案
   - 2.9 模型预热

3. [音频处理技术原理](#音频处理技术原理)
   - 3.1 音频格式与编码
   - 3.2 格式转换流程
   - 3.3 音频验证与预处理
   - 3.4 采样率与声道处理
   - 3.5 流式音频输出
   - 3.6 流式逐句合成（Stream Chunks）

4. [前端实现细节](#前端实现细节)
   - 4.1 步骤引导系统
   - 4.2 流式逐句播放的进度指示器
   - 4.3 Toast 通知系统

---

## 1. Flask Web 服务工作原理

### 1.1 Flask 框架概述

Flask 是一个轻量级的 Python Web 框架，采用微框架设计理念，核心特点包括：

- **WSGI 兼容**：遵循 Web Server Gateway Interface 规范，可与多种 Web 服务器配合
- **路由装饰器**：通过 `@app.route` 装饰器定义 URL 与处理函数的映射
- **请求上下文**：自动管理请求相关的上下文信息（request、session 等）
- **模板引擎**：集成 Jinja2 模板引擎，支持动态 HTML 生成
- **扩展机制**：通过扩展包支持数据库、表单验证、CORS 等功能

### 1.2 路由与请求处理

Flask 的请求处理流程如下：

```
客户端请求 → Web Server → WSGI 服务器 → Flask 应用实例
                                          ↓
                              路由匹配（URL Rule）
                                          ↓
                              视图函数执行（View Function）
                                          ↓
                              返回响应（Response）
```

**核心代码示例**（`app.py`）：

```python
@app.route('/api/synthesize', methods=['POST'])
def synthesize():
    # 1. 获取请求数据
    data = request.get_json()
    
    # 2. 验证参数
    required_fields = ['text', 'voice_id', 'language']
    if not all(f in data for f in required_fields):
        return jsonify({"error": "缺少必要参数"}), 400
    
    # 3. 业务逻辑处理
    try:
        output_path = tts_engine.clone_voice(
            text=data['text'],
            speaker_audio_path=get_voice_path(data['voice_id']),
            language=data['language']
        )
        
        # 4. 构建响应
        audio_url = f"/output/{os.path.basename(output_path)}"
        return jsonify({
            "success": True,
            "audio_url": audio_url
        })
    
    except Exception as e:
        # 5. 错误处理
        return jsonify({"error": str(e)}), 500
```

### 1.3 API 接口设计

本项目设计了以下核心 API 接口：

| 接口 | HTTP 方法 | 功能描述 | 关键参数 |
|------|-----------|----------|----------|
| `/api/status` | GET | 服务状态检查 | 无 |
| `/api/voices` | GET | 获取声纹列表 | 无 |
| `/api/upload` | POST | 上传语音样本 | `audio` (文件) |
| `/api/synthesize` | POST | 合成语音（文件模式） | `text`, `voice_id`, `language`, `speed` |
| `/api/stream` | POST | 合成语音（流式模式） | `text`, `voice_id`, `language`, `speed` |
| `/api/stream-chunks` | POST | 流式逐句合成（二进制块流） | `text`, `voice_id`, `language`, `speed` |
| `/api/voice-audio/<voice_id>` | GET | 获取声纹音频 | `voice_id` |
| `/api/delete-voice/<voice_id>` | DELETE | 删除声纹 | `voice_id` |
| `/api/clear-outputs` | POST | 清空输出文件 | 无 |

**RESTful 设计原则**：
- 使用合适的 HTTP 方法：GET（查询）、POST（创建）、DELETE（删除）
- 统一错误响应格式：`{"error": "描述信息"}`
- 状态码规范：200（成功）、400（请求错误）、500（服务器错误）

### 1.4 静态资源与模板渲染

Flask 提供两种资源服务方式：

**1. 静态文件服务**
```python
# 自动映射 static 目录
# URL: /static/style.css → 文件: static/style.css
```

**2. 模板渲染**
```python
from flask import render_template

@app.route('/')
def index():
    return render_template('index.html')
```

Jinja2 模板特性：
- 变量替换：`{{ variable }}`
- 控制结构：`{% if %}`、`{% for %}`
- 模板继承：`{% extends 'base.html' %}`

### 1.5 错误处理与日志

**错误处理机制**：
```python
@app.errorhandler(404)
def not_found(error):
    return jsonify({"error": "资源未找到"}), 404

@app.errorhandler(Exception)
def handle_exception(error):
    logger.error(f"未处理异常: {error}", exc_info=True)
    return jsonify({"error": "服务器内部错误"}), 500
```

**日志配置**：
```python
import logging
from logging.handlers import RotatingFileHandler

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        RotatingFileHandler('app.log', maxBytes=1024*1024*10, backupCount=5),
        logging.StreamHandler()
    ]
)
```

---

### 1.6 合成结果缓存

为避免重复合成相同的文本内容，系统实现了基于 MD5 的缓存机制：

```python
def _get_cache_key(text, voice_id, language, speed):
    """基于文本、声纹、语言、语速生成唯一缓存键"""
    raw = f"{text}|{voice_id}|{language}|{speed}"
    return hashlib.md5(raw.encode()).hexdigest()
```

**缓存策略**：
- **存储**：WAV 文件保存到 `cache/` 目录，文件名为缓存键
- **命中检查**：每次合成前检查缓存文件是否存在，命中则直接返回
- **容量上限**：500MB（`MAX_CACHE_SIZE_MB`），超出时按文件访问时间（atime）排序，从最旧开始删除直到容量达标
- **过期清理**：7 天（`CACHE_MAX_AGE_DAYS`），启动时和新增缓存时检查并删除过期条目
- **适用场景**：相同文本重复生成（如调试、调整语速后重新生成）

**关键代码**（`app.py`）：

```python
def _evict_cache_if_needed():
    """在删除文件前保存文件大小，确保 total_size 正确递减。"""
    cache_files = sorted(CACHE_DIR.glob("*.wav"), key=lambda f: f.stat().st_atime)
    total_size = sum(f.stat().st_size for f in cache_files) / (1024 * 1024)

    while total_size > MAX_CACHE_SIZE_MB and len(cache_files) > 1:
        oldest = cache_files.pop(0)
        size_mb = oldest.stat().st_size / (1024 * 1024)
        oldest.unlink(missing_ok=True)
        total_size -= size_mb

def _clean_old_cache():
    """启动时清理超过 7 天未修改的缓存文件。"""
    now = datetime.now().timestamp()
    for f in CACHE_DIR.glob("*.wav"):
        age_days = (now - f.stat().st_mtime) / 86400
        if age_days > CACHE_MAX_AGE_DAYS:
            f.unlink(missing_ok=True)
```

---

### 1.7 统一请求验证

为避免三个合成接口（`/api/synthesize`、`/api/stream`、`/api/stream-chunks`）重复编写相同的参数校验逻辑，项目抽取了统一的验证函数：

```python
def _validate_synthesis_request(data):
    """统一验证合成请求参数。
    
    返回：
        (text, voice_id, language, speed, speaker_path) 成功时
        (None, None, None, None, error_response_tuple) 失败时
    """
    if not data:
        return (None, None, None, None, (jsonify({"error": "请求数据为空"}), 400))

    text = data.get("text", "").strip()
    voice_id = data.get("voice_id", session.get("last_voice_id"))
    language = data.get("language", "zh-cn")
    speed = float(data.get("speed", 1.0))

    # 文本长度校验（≤5000字符）
    if not text:
        return (None, None, None, None, (jsonify({"error": "文字内容不能为空"}), 400))
    if len(text) > 5000:
        return (None, None, None, None, (jsonify({"error": f"文字长度不能超过 5000 字符（当前 {len(text)} 字符）"}), 400))

    # 语速范围校验（0.5-2.0）
    if speed < 0.5 or speed > 2.0:
        return (None, None, None, None, (jsonify({"error": "语速必须在 0.5 到 2.0 之间"}), 400))

    # 语言有效性校验
    valid_langs = [l["code"] for l in tts_engine.list_supported_languages()]
    if language not in valid_langs:
        return (None, None, None, None, (jsonify({"error": f"不支持的语言: {language}"}), 400))

    # 声纹存在性校验
    if not voice_id:
        return (None, None, None, None, (jsonify({"error": "请先上传语音样本"}), 400))
    speaker_path = _find_voice_path(voice_id)
    if not speaker_path:
        return (None, None, None, None, (jsonify({"error": "声纹样本未找到，请重新上传"}), 404))

    return (text, voice_id, language, speed, speaker_path)
```

**设计要点**：
- 失败时所有返回值字段统一为 `None`，调用方检查 `text is None` 判断是否出错
- `voice_id` 支持从 `session` 中获取最近使用的声纹，减少用户重复选择
- 声纹路径通过 `_find_voice_path()` 自动检测多种扩展名（.wav/.mp3/.flac/.ogg）

**路由调用方式**：

```python
text, voice_id, language, speed, speaker_path = _validate_synthesis_request(data)
if text is None:
    return speaker_path  # speaker_path 是错误响应元组
# ... 继续合成逻辑
```

---

### 1.8 安全加固

为防止路径遍历攻击（Path Traversal），项目引入了文件名净化函数：

```python
def _sanitize_filename(name):
    """移除所有非安全字符，仅保留字母、数字、下划线、连字符。"""
    import re
    return re.sub(r'[^\w\-]', '', name)
```

**应用路由**：

| 路由 | 原始参数 | 安全处理 | 攻击示例 | 处理后 |
|------|----------|----------|----------|--------|
| `/api/voice-audio/<voice_id>` | `voice_id` | `_sanitize_filename(voice_id)` | `../etc/passwd` | `etcpasswd` |
| `/api/delete-voice/<voice_id>` | `voice_id` | `_sanitize_filename(voice_id)` | `../../secret` | `secret` |
| `/output/<filename>` | `filename` | `_sanitize_filename(filename)` | `../../../tmp/evil` | `tmpevil` |

**防御原理**：
- `re.sub(r'[^\w\-]', '', name)` 只保留字母数字下划线连字符
- 任何 `/`、`.`、`..` 等路径遍历字符都被完全剔除
- 空结果直接返回 400 错误

---

## 2. Coqui XTTS 使用与注意事项

### 2.1 XTTS 模型架构

XTTS v2 是一个基于 Transformer 的多语言端到端语音合成模型，架构如下：

```
┌─────────────────────────────────────────────────────────┐
│                    文本输入 (Text)                       │
│                      ↓                                  │
│            ┌───────────────────────┐                    │
│            │    文本编码器          │                    │
│            │  Text Encoder          │                    │
│            │  (Transformer Encoder) │                    │
│            └───────────┬───────────┘                    │
│                        ↓                                │
│            ┌───────────────────────┐                    │
│            │    声纹编码器          │                    │
│            │  Speaker Encoder       │                    │
│            │  (DINOv2-based)       │                    │
│            └───────────┬───────────┘                    │
│                        ↓                                │
│            ┌───────────────────────┐                    │
│            │    解码器              │                    │
│            │  Decoder               │                    │
│            │  (Transformer Decoder) │                    │
│            │  (Cross-Attention)    │                    │
│            └───────────┬───────────┘                    │
│                        ↓                                │
│            ┌───────────────────────┐                    │
│            │    声码器              │                    │
│            │  Vocoder               │                    │
│            │  (HiFi-GAN)            │                    │
│            └───────────┬───────────┘                    │
│                        ↓                                │
│                    音频输出 (WAV)                        │
└─────────────────────────────────────────────────────────┘
```

### 2.2 声纹克隆原理

XTTS 采用零样本声纹克隆技术，无需针对特定说话人进行微调：

**步骤 1：声纹嵌入提取**
```python
# 从参考音频中提取声纹特征
speaker_embedding = model.speaker_encoder.encode(speaker_wav)
# 输出: 512维向量，包含说话人的音色、语调、语速等特征
```

**步骤 2：文本编码**
```python
# 将文本转换为语义表示
text_embedding = model.text_encoder.encode(text)
```

**步骤 3：条件生成**
```python
# 以声纹嵌入为条件，生成目标语音
mel_spectrogram = model.decoder.generate(
    text_embedding,
    speaker_embedding=speaker_embedding
)
```

**步骤 4：波形合成**
```python
# 将频谱图转换为音频波形
audio_wav = model.vocoder.decode(mel_spectrogram)
```

### 2.3 多语言支持机制

XTTS 支持 14 种语言的语音合成，其多语言机制如下：

| 语言 | 代码 | 说明 |
|------|------|------|
| 简体中文 | `zh-cn` | 支持中文普通话 |
| 英语 | `en` | 美式/英式英语 |
| 日语 | `ja` | 标准日语 |
| 韩语 | `ko` | 标准韩语 |
| 法语 | `fr` | 标准法语 |
| 德语 | `de` | 标准德语 |
| 西班牙语 | `es` | 西班牙西班牙语 |
| 俄语 | `ru` | 标准俄语 |

**多语言实现原理**：
- 共享的文本编码器，但对不同语言使用特定的 tokenizer
- 语言标识嵌入（Language Embedding）作为解码器输入
- 解码器通过 cross-attention 学习语言特定的韵律模式

### 2.4 模型加载与缓存

**首次加载流程**：
```python
from TTS.api import TTS

# 模型名称
MODEL_NAME = "tts_models/multilingual/multi-dataset/xtts_v2"

# 初始化（首次自动下载约 2GB 模型）
tts = TTS(MODEL_NAME)

# 模型文件结构（缓存目录）
# .tts_cache/
#   ├── tts_models--multilingual--multi-dataset--xtts_v2/
#   │   ├── config.json
#   │   ├── model.pth
#   │   ├── speaker_encoder/
#   │   └── vocoder/
```

**缓存策略**：
- 使用 `TTS_HOME` 环境变量指定缓存目录
- 模型下载后持久化存储，后续启动无需重新下载
- 支持版本管理，不同版本模型独立缓存

### 2.5 性能优化策略

**CPU 优化**（Intel Mac）：
```python
import torch
import os

# 设置线程数为 CPU 核心数
cpu_count = os.cpu_count() or 8
torch.set_num_threads(cpu_count)

# 设置环境变量
os.environ["OMP_NUM_THREADS"] = str(cpu_count)
os.environ["MKL_NUM_THREADS"] = str(cpu_count)

# 启用 MKLDNN 优化（如果支持）
if torch.backends.mkldnn.is_available():
    try:
        torch.backends.mkldnn.set_benchmark(True)
    except AttributeError:
        pass
```

**内存优化**：
- 使用 `torch.inference_mode()` 减少内存占用
- 文本分块处理，避免一次性加载过长文本
- 及时释放不再使用的张量

**推理优化**：
- 启用 `split_sentences=True` 参数，逐句合成再拼接
- 对于长文本，自动分段处理（每段约 400 字符）
- **模型预热**：启动时后台线程执行短文本合成，触发 PyTorch 计算图编译，消除首次合成 10-30 秒的额外延迟

**代码质量优化**：
- **导入位置优化**：将 `numpy`、`librosa`、`scipy.io.wavfile`、`soundfile` 等库从局部作用域移至模块顶部，避免每次调用时的重复导入开销
- **移除冗余导入**：清理未使用的 `hashlib`、`pattern` 变量等，减少模块加载负担

### 2.6 文本预处理与分句

为了提升合成语音的自然度（抑扬顿挫和标点停顿），引擎实现了智能文本预处理和分句逻辑：

**预处理流程**：
```python
def _preprocess_text(self, text, language="zh-cn"):
    # 1. 规范化标点符号
    text = text.replace('\u201c', '"').replace('\u201d', '"')  # 智能引号
    text = text.replace('\u2018', "'").replace('\u2019', "'")
    text = text.replace('\u2014\u2014', '\u2014')  # 双破折号归一
    text = text.replace('\u2026\u2026', '\u2026')   # 双省略号归一

    # 2. 合并多余空格
    text = re.sub(r' {2,}', ' ', text)
    
    return text.strip()
```

**分句逻辑**（`_split_sentences`）：

对于中文/日文/韩文，按 `。！？；` 分割；对于英文等拉丁语系，按句尾标点 + 空格 + 大写字母分割。分句后每句单独合成，避免模型在处理长文本时丢失韵律信息。

```python
def _split_sentences(self, text, language="zh-cn"):
    if language in ("zh-cn", "ja", "ko"):
        # 中文：按句号、问号、感叹号、分号分割
        parts = re.split(r'(?<=[。！？；])', line)
    else:
        # 英文：按 . ! ? 后跟空格+大写字母分割
        parts = re.split(r'(?<=[\.\!\?])\s+', line)
```

分句后每句传入模型时设置 `split_sentences=False`，避免模型重复分句。

### 2.7 语速控制

使用 `librosa.effects.time_stretch` 实现变速不变调，应用于合成后的原始波形：

```python
def _apply_speed(self, wav_np, speed):
    """对波形进行时域拉伸/压缩，speed=1.0 不变"""
    if speed == 1.0:
        return wav_np
    return librosa.effects.time_stretch(y=wav_np, rate=speed)
```

**技术原理**：
- **WSOLA 算法**（Waveform Similarity Overlap-Add）：librosa 的 time_stretch 基于 WSOLA，通过重叠-相加技术改变播放速度而不影响基频
- **音调保持**：不同于简单的重采样（会改变音调），WSOLA 在时域操作，保持基频和音色不变
- **范围限制**：0.5x - 2.0x，超出范围时前端直接拦截并返回错误提示

**应用时机**：在模型合成出 float32 波形数组后，立即应用变速，再转为 int16 WAV 格式。这使得语速调节完全在内存中完成，无需重新合成。

### 2.8 常见问题与解决方案

| 问题 | 错误信息 | 原因 | 解决方案 |
|------|----------|------|----------|
| 模型下载失败 | `Permission denied` | 系统目录权限不足 | 设置 `TTS_HOME` 到项目目录 |
| 导入错误 | `cannot import name 'BeamSearchScorer'` | transformers 版本不兼容 | 锁定版本 `transformers>=4.46,<4.49` |
| MPS 错误 | `aten::_fft_r2c not implemented for MPS` | MPS 不支持某些算子 | 回退到 CPU 或设置环境变量 |
| 合成速度慢 | - | 模型推理开销大 | 使用流式预览，文本分段处理 |
| 语音不自然 | 标点停顿不明显 | 文本格式问题 | 使用 `_preprocess_text()` 预处理 |
| 警告信息 | `The attention mask is not set...` | XTTS 模型的已知行为 | 可安全忽略，不影响合成质量 |

---

### 2.9 模型预热

**问题**：XTTS v2 模型在首次合成时，PyTorch 需要编译计算图（graph compilation），导致首次请求额外耗时 10-30 秒。

**解决方案**：启动时后台线程自动执行一次预热合成，触发计算图编译。

```python
def warmup():
    """执行短文本预热合成，触发模型计算图编译。"""
    first_voice = next(VOICE_PROFILES_DIR.glob("*.wav"), None)
    if first_voice and args.warmup:
        logger.info("Running model warm-up (this may take 10-30s)...")
        tts_engine.clone_voice(
            text="这是一个预热测试。",
            speaker_audio_path=str(first_voice),
            language="zh-cn",
            speed=1.0
        )
        logger.info("Model warm-up complete!")

threading.Thread(target=warmup, daemon=True).start()
```

**设计要点**：
- **后台线程**：不阻塞 Flask 主进程，预热期间服务器仍可接受请求
- **daemon=True**：主进程退出时线程自动终止
- **命令行控制**：`--no-warmup` 参数可跳过预热
- **首选声纹**：使用已有声纹预热，避免模型重新加载
- **错误容忍**：预热失败记录警告但不影响服务运行

**生效效果**：
- 预热前首次合成：30-60 秒（含模型加载 + 图编译）
- 预热后首次合成：10-30 秒（仅模型推理）
- 预热后第二次合成：与首次相当（图已缓存）

---

## 3. 音频处理技术原理

### 3.1 音频格式与编码

**常见音频格式**：

| 格式 | 扩展名 | 编码方式 | 特点 |
|------|--------|----------|------|
| WAV | `.wav` | PCM | 无损，未压缩，文件大 |
| MP3 | `.mp3` | MPEG-1 Layer 3 | 有损压缩，文件小，音质好 |
| FLAC | `.flac` | FLAC | 无损压缩，文件中等 |
| OGG | `.ogg` | Vorbis | 开源，有损压缩 |
| M4A | `.m4a` | AAC | Apple 格式，高效压缩 |

**音频参数**：
- **采样率（Sample Rate）**：每秒采样次数，常用 24kHz、44.1kHz、48kHz
- **位深度（Bit Depth）**：每个采样点的比特数，常用 16-bit
- **声道数（Channels）**：单声道（Mono）、立体声（Stereo）

### 3.2 格式转换流程

本项目支持多种格式到 WAV 的转换，采用多层 fallback 策略：

```
输入文件 → 格式检测 → pydub → soundfile → afconvert → ffmpeg → 输出 WAV
              ↓              ↓          ↓           ↓          ↓
            扩展名        优先使用    如果失败    如果失败    最终备选
                        (简单快捷)  (纯Python)  (macOS专属)  (跨平台)
```

**转换代码示例**（`audio_utils.py`）：

```python
def convert_to_wav(input_path, output_path):
    """
    将音频文件转换为 WAV 格式（24kHz, 单声道, 16-bit）
    """
    # 方法1: 使用 pydub（最简单）
    try:
        from pydub import AudioSegment
        audio = AudioSegment.from_file(input_path)
        audio = audio.set_frame_rate(24000).set_channels(1).set_sample_width(2)
        audio.export(output_path, format='wav')
        return True
    except Exception as e:
        logger.debug(f"pydub failed: {e}")
    
    # 方法2: 使用 soundfile
    try:
        import soundfile as sf
        data, sr = sf.read(input_path)
        # 转换为单声道
        if len(data.shape) > 1:
            data = data.mean(axis=1)
        # 重采样到 24kHz
        if sr != 24000:
            from scipy.signal import resample
            data = resample(data, int(len(data) * 24000 / sr))
        sf.write(output_path, data, 24000, subtype='PCM_16')
        return True
    except Exception as e:
        logger.debug(f"soundfile failed: {e}")
    
    # 方法3: 使用 afconvert（macOS）
    try:
        subprocess.run([
            'afconvert',
            '-d', 'LEI16@24000',  # 16-bit PCM, 24kHz
            '-c', '1',              # 单声道
            input_path,
            output_path
        ], check=True)
        return True
    except Exception as e:
        logger.debug(f"afconvert failed: {e}")
    
    # 方法4: 使用 ffmpeg（最终备选）
    try:
        subprocess.run([
            'ffmpeg',
            '-i', input_path,
            '-ar', '24000',        # 采样率
            '-ac', '1',             # 声道数
            '-sample_fmt', 's16',   # 位深度
            '-y',                   # 覆盖输出
            output_path
        ], check=True, capture_output=True)
        return True
    except Exception as e:
        logger.error(f"All conversion methods failed: {e}")
        return False
```

### 3.3 音频验证与预处理

**验证步骤**：
1. **格式检查**：验证文件扩展名是否在允许列表中
2. **文件大小检查**：限制最大文件大小（如 50MB）
3. **时长检查**：确保音频时长在合理范围（如 1-60 秒）
4. **完整性检查**：验证文件不是损坏的

**预处理步骤**：
1. **格式转换**：统一转换为 WAV 格式
2. **采样率统一**：转换为 24kHz（XTTS 模型要求）
3. **声道处理**：转换为单声道
4. **位深度统一**：转换为 16-bit

### 3.4 采样率与声道处理

**采样率转换原理**：
- 使用线性插值或 sinc 插值进行重采样
- 避免混叠（Aliasing）：转换前应用低通滤波器

**声道合并**：
```python
# 立体声转单声道（取平均值）
if len(audio_data.shape) > 1 and audio_data.shape[1] == 2:
    mono_data = (audio_data[:, 0] + audio_data[:, 1]) / 2
```

### 3.5 流式音频输出

**流式合成原理**：

```python
@app.route('/api/stream', methods=['POST'])
def stream_audio():
    data = request.get_json()
    
    # 使用流式方法生成音频
    wav = tts_engine.clone_voice_stream(
        text=data['text'],
        speaker_audio_path=get_voice_path(data['voice_id']),
        language=data['language']
    )
    
    # 将 numpy 数组转换为 WAV 字节流
    buffer = io.BytesIO()
    sf.write(buffer, wav, 24000, format='WAV', subtype='PCM_16')
    buffer.seek(0)
    
    # 返回流式响应
    return Response(
        buffer.read(),
        mimetype='audio/wav',
        headers={
            'Content-Disposition': 'inline; filename="stream.wav"'
        }
    )
```

**流式响应特点**：
- 实时生成，边生成边传输
- 减少用户等待时间（首字节延迟低）
- 适合长文本合成场景

### 3.6 流式逐句合成（Stream Chunks）

流式逐句合成是一种更细粒度的流式方案，将文本按句子分割后逐句合成，每句生成后立即传输给前端播放：

**后端实现**（`/api/stream-chunks`）：

```python
def generate():
    import struct
    for chunk_info in tts_engine.clone_voice_sentences(
        text=text,
        speaker_audio_path=str(speaker_path),
        language=language,
        speed=speed
    ):
        wav_data = chunk_info["audio"].read()
        # 4字节大端长度前缀
        yield struct.pack(">I", len(wav_data))
        yield wav_data
```

**传输协议**：
```
[4字节 大端长度] [WAV 数据] [4字节 大端长度] [WAV 数据] ...
```
- 每个 WAV 块前附 4 字节大端无符号整数表示长度
- 错误时长度高位（0x80000000）置 1，后续为 JSON 错误信息

**前端消费流程**（JavaScript）：
1. 通过 `fetch()` 获取响应流 `ReadableStream`
2. 用 `getReader()` 逐块读取二进制数据
3. 解析 4 字节长度前缀，提取完整 WAV 块
4. 每个 WAV 块转换为 `Blob` + `ObjectURL`，通过 `new Audio(url)` 播放

**核心优势**：
- **首句延迟低**：约 5-15 秒即可听到第一句，远低于整体合成的 30-60 秒
- **进度感知**：用户能实时感知合成进度
- **内存友好**：逐句处理，无需在内存中缓存完整音频

---

## 4. 前端实现细节

### 4.1 步骤引导系统

操作界面分为三个步骤，通过 CSS 进度条和视觉反馈引导用户：
1. **上传声纹**：支持文件拖放或选择，上传后自动加载声纹列表
2. **选择声纹与配置**：声纹可预览试听，支持语言选择和语速调节
3. **合成与播放**：点击合成后生成完整音频，支持流式逐句播放

步骤状态通过 `updateSteps()` 函数管理，自动激活/完成对应步骤。

### 4.2 流式逐句播放的进度指示器

流式逐句播放时，每合成并播放一句，进度指示器实时更新：

```javascript
// 前端进度更新逻辑
elements.streamProgressText.textContent = `正在播放第 ${chunksReceived} 句...`;

// 播放完成时
elements.streamProgress.className = 'stream-progress done';
elements.streamProgressText.textContent = `播放完成（共 ${chunksReceived} 句）`;
```

**CSS 设计**：
```css
.stream-progress {
    display: flex;
    align-items: center;
    gap: 0.5rem;
    padding: 0.5rem 0.75rem;
    background: rgba(108, 92, 231, 0.08);
    border: 1px solid rgba(108, 92, 231, 0.2);
    border-radius: 4px;
    margin-top: 0.75rem;
    font-size: 0.82rem;
}
.stream-progress.done {
    background: rgba(0, 214, 143, 0.08);
    border-color: rgba(0, 214, 143, 0.2);
    color: #00d68f;
}
```

**用户体验优化**：
- 播放中：紫色主题，播放图标跳动脉冲动画
- 播放完成：绿色主题，图标切换为对勾 ✓
- 替代了之前 Toast 通知刷屏的问题

### 4.3 Toast 通知系统

Toast 通知通过 CSS 动画实现，分为三种类型：
- **info**：蓝色，普通信息提示
- **success**：绿色，操作成功提示
- **error**：红色，错误提示

```javascript
function showToast(message, type = 'info') {
    const toast = document.createElement('div');
    toast.className = `toast toast-${type}`;
    toast.textContent = message;
    document.getElementById('toastContainer').appendChild(toast);
    setTimeout(() => toast.remove(), 3000);
}
```

---

## 附录：技术栈汇总

| 分类 | 技术 | 版本要求 | 用途 |
|------|------|----------|------|
| 框架 | Flask | >=3.0 | Web 服务 |
| 模型 | Coqui TTS | ==0.21.3 | 语音合成核心 |
| 深度学习 | PyTorch | >=2.0 | 模型推理 |
| 音频处理 | pydub | >=0.25 | 格式转换 |
| 音频处理 | soundfile | >=0.12 | 读写音频 |
| 音频处理 | scipy | >=1.10 | 重采样 + WAV 写入 |
| 音频处理 | librosa | >=0.10 | 语速控制（time_stretch） |
| 文本处理 | numpy | >=1.22 | 数值计算 |
| 文本处理 | spacy | <3.8 | 文本处理（XTTS 依赖） |
| 前端 | HTML/CSS/JS | - | 用户界面 |
| 文件管理 | pathlib | - | 路径处理 |
| 日志 | logging | - | 日志记录 |