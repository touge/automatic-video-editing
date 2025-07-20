# 🎬 自动化视频编辑工具 (API-First)

这是一个基于 Python 和 FastAPI 的、API 优先的自动化视频编辑工具。它能够将一个简单的想法（体现为文本或音频）高效地转换为一个由相关视频素材、背景音乐和精确字幕构成的成品视频。项目深度整合了大语言模型（LLM）进行智能语义分析，并遵循“快速失败”的设计哲学，以确保工作流的健壮性和可预测性。

## ✨ 核心特性

- **API 优先设计**: 所有功能都通过一套清晰的 RESTful API 暴露，易于集成、自动化和构建前端应用。
- **智能场景分析**:
    - **主场景分割**: 利用 LLM 将长篇的对话或脚本，智能地分割成具有逻辑连贯性的“主场景”（Main Scenes）。
    - **子场景生成**: 在每个主场景内部，再次利用 LLM 生成更细粒度的、带有精确时长和描述性关键词的“子场景”（Sub-scenes），它们是视频合成的基本单位。
- **精准素材匹配**:
    - 根据每个子场景的关键词，从多个在线视频源（Pexels, Pixabay, AI Search）进行搜索。
    - 内置强大的去重逻辑，确保视频素材的多样性。
    - 遵循“找到一个就足够”的原则，高效地下载最匹配的单个素材，避免不必要的资源浪费。
- **健壮的视频合成**:
    - 使用强大的 FFmpeg 作为后端。
    - 智能处理视频素材，根据子场景所需时长进行精确裁剪或使用“循环”、“静帧”等方式进行延长。
    - 支持硬件加速（NVIDIA NVENC, Intel QSV, Apple VideoToolbox）以提升处理速度。
    - 可选的字幕烧录功能。
- **“快速失败”设计哲学**: 在工作流的任何一个环节（如素材找不到、文件格式错误等），系统都会立即中止任务，并返回明确的错误信息，而不是尝试进行不可靠的修复。这使得问题能够被第一时间定位和解决。

## 🛠️ 技术栈

- **后端**: Python
- **API 框架**: FastAPI
- **视频处理**: FFmpeg
- **LLM 集成**: 可通过 `config.yaml` 配置，支持多种 LLM 服务（如 Ollama, OpenAI, SiliconFlow 等）。
- **主要 Python 库**: `ffmpeg-python`, `requests`, `tqdm`, `pyyaml`, `uvicorn`。

## 🚀 工作流程详解

项目的工作流程完全由 API 驱动，遵循一个清晰、分步骤的状态机模型。

![工作流程图](https://dummyimage.com/1200x250/d3d3d3/000000.png&text=API-Driven+Workflow)

1.  **创建任务 (`POST /tasks`)**: 客户端发起请求，创建一个新的工作任务。服务器会返回一个唯一的 `task_id`，后续所有操作都将围绕这个 ID 进行。
2.  **上传文件 (`POST /tasks/{task_id}/upload`)**: 客户端将初始的音频文件（如 `.mp3`, `.wav`）上传到指定的任务中。
3.  **音频处理与转录 (`POST /tasks/{task_id}/audio`)**: 客户端请求服务器处理上传的音频。服务器会执行语音转录，生成带时间戳的字幕文件 (`.srt`)。
4.  **场景分析 (`POST /tasks/{task_id}/analysis`)**: 这是项目的核心魔法。客户端请求进行场景分析。服务器会：
    a.  读取字幕文件。
    b.  调用 LLM，将字幕分割成多个逻辑连贯的**主场景**。
    c.  对每个主场景，再次调用 LLM，生成更细粒度的**子场景**列表，并为每个子场景附上描述性关键词和建议时长。
    d.  将这个包含层级结构的数据，保存为 `final_scenes.json`。
5.  **（可选）人工审核**: 此时，用户可以通过 API 下载 `final_scenes.json`，检查或修改其中的文本、关键词和时长，然后再重新上传。
6.  **视频合成 (`POST /tasks/{task_id}/compose`)**: 客户端发起最终的合成请求。服务器会：
    a.  读取 `final_scenes.json`。
    b.  为每一个**子场景**，调用 `AssetManager` 查找并下载一个最合适的视频素材。
    c.  如果任何一个子场景找不到素材，任务会立即失败并中止。
    d.  调用 `VideoComposer`，使用 FFmpeg 将所有下载的素材、背景音乐和字幕精确地拼接、裁剪、延长，最终生成 `final_video.mp4`。
7.  **状态查询 (`GET /tasks/{task_id}/status`)**: 在整个流程中，客户端可以随时轮询此端点，以获取任务的当前状态（如 `pending`, `running`, `success`, `failed`）和详细的进度信息。

## ⚙️ 如何使用

### 1. 环境准备

- **安装 FFmpeg**: 确保您的系统中已安装 FFmpeg，并已将其添加到系统环境变量中。
- **安装 Python 依赖**:
  ```bash
  pip install -r requirements.txt
  ```
- **准备配置文件**:
    - 将 `config.yaml.template` 复制为 `config.yaml`。
    - 打开 `config.yaml` 并根据您的需求进行配置。**这是至关重要的一步**。

### 2. 配置 `config.yaml`

```yaml
# LLM 提供商配置 (选择一个或多个)
llm:
  default_provider: ollama # or openai, siliconflow
  providers:
    ollama:
      api_base: "http://localhost:11434/v1"
      model: "qwen2:7b-instruct"
    openai:
      api_key: "YOUR_OPENAI_API_KEY"
      api_base: "https://api.openai.com/v1"
      model: "gpt-4-turbo"
    # ... 其他提供商

# 素材搜索提供商配置
asset_search:
  # 每次 API 请求的间隔时间，防止被封禁
  request_delay_seconds: 3
  # 每次向 API 请求的候选素材数量
  online_search_count: 10
  providers:
    # AI 搜索 (如果可用)
    ai_search:
      api_key: "YOUR_AI_SEARCH_API_KEY"
      api_url: "https://your-ai-search-provider.com/api"
    # Pexels
    pexels:
      api_key: "YOUR_PEXELS_API_KEY"
    # Pixabay
    pixabay:
      api_key: "YOUR_PIXABAY_API_KEY"

# 视频合成默认参数
composition_settings:
  default_video_size: [1080, 1920] # 宽, 高 (例如竖屏)
  default_fps: 30

# API 服务安全配置
security:
  api_token: "YOUR_SECRET_TOKEN" # 用于保护你的 API
```

### 3. 启动 API 服务

```bash
# 推荐使用 uvicorn 启动
uvicorn src.api.main:app --host 0.0.0.0 --port 9001
```
启动后，您可以访问 `http://localhost:9001/docs` 查看交互式的 Swagger UI 和完整的 API 文档。

### 4. 通过 API 执行一个完整任务 (Curl 示例)

假设你的 `api_token` 是 `my-secret-token`。

**1. 创建任务**
```bash
TASK_ID=$(curl -s -X POST http://localhost:9001/tasks \
-H "Authorization: Bearer my-secret-token" \
| jq -r '.task_id')

echo "新任务创建成功: $TASK_ID"
```

**2. 上传音频文件**
```bash
curl -X POST "http://localhost:9001/tasks/$TASK_ID/upload" \
-H "Authorization: Bearer my-secret-token" \
-F "file=@/path/to/your/audio.mp3"
```

**3. 启动音频处理**
```bash
curl -X POST "http://localhost:9001/tasks/$TASK_ID/audio" \
-H "Authorization: Bearer my-secret-token"
```
*轮询 `GET /tasks/$TASK_ID/status` 直到音频处理完成。*

**4. 启动场景分析**
```bash
curl -X POST "http://localhost:9001/tasks/$TASK_ID/analysis" \
-H "Authorization: Bearer my-secret-token"
```
*轮询 `GET /tasks/$TASK_ID/status` 直到场景分析完成。此时 `final_scenes.json` 已生成。*

**5. 启动视频合成**
```bash
curl -X POST "http://localhost:9001/tasks/$TASK_ID/compose" \
-H "Authorization: Bearer my-secret-token" \
-H "Content-Type: application/json" \
-d '{"embed_subtitles": true}'
```

**6. 监控最终状态**
持续轮询 `GET http://localhost:9001/tasks/$TASK_ID/status`。当状态变为 `success` 时，响应中会包含最终视频的 URL。如果状态变为 `failed`，响应中会包含详细的错误信息。

## 目录结构

```
.
├── src/                # 项目核心逻辑
│   ├── api/            # FastAPI 相关代码 (路由, 安全, 入口)
│   ├── core/           # 核心组件 (场景分割, 素材管理, 视频合成)
│   ├── logic/          # 业务逻辑 (连接 API 和 Core)
│   └── providers/      # 对接外部服务的提供者 (LLM, 素材搜索, TTS)
├── storage/            # 存储任务数据和输出文件
│   └── tasks/          # 每个子目录代表一个任务
├── config.yaml         # 配置文件 (需从 .template 创建)
├── requirements.txt    # Python 依赖列表
└── README.md           # 本文档
