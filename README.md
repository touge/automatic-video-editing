# 自动化视频编辑工具

这是一个基于 Python 的自动化视频编辑工具，旨在将字幕（SRT 文件）和配音（音频文件）快速转换为一个由相关视频素材拼接而成的成品视频。项目利用大语言模型（LLM）进行语义分析，自动化处理繁琐的素材搜集和剪辑工作。

## 核心功能

- **智能场景分割**: 利用 LLM (通过 Ollama) 分析字幕内容，自动将文本分割成具有逻辑关联的场景。
- **关键词自动生成**: 为每个场景提取核心关键词，用于后续的素材搜索。
- **自动化素材搜集**: 根据关键词从多个素材源（如 Pexels, Pixabay，以及本地文件）搜索和下载高质量的视频片段。
- **灵活的视频合成**:
    - 支持自定义视频分辨率、帧率。
    - 智能切分长场景，匹配多个短镜头，增加视觉丰富性。
    - 优先使用硬件加速（NVIDIA NVENC, Intel QSV, Apple VideoToolbox）来提升视频处理速度。
    - 健壮的 `ffmpeg` 调用，包含多种失败回退机制。
- **字幕烧录**: 可选择自动生成字幕或使用外部 SRT 文件烧录到最终视频中。
- **两阶段工作流**:
    1.  **分析阶段**: 生成 `scenes.json` 文件，允许用户在合成前审查和修改场景与关键词。
    2.  **合成阶段**: 根据确认的场景数据和音频文件，全自动完成素材下载和视频合成。
- **API 服务**: 提供一套完整的 FastAPI 接口，可用于程序化调用、集成或构建前端应用。

## 技术栈

- **后端**: Python
- **API 框架**: FastAPI
- **视频处理**: FFmpeg
- **LLM 服务**: Ollama (支持本地运行各种大语言模型)
- **主要 Python 库**: `ffmpeg-python`, `requests`, `tqdm`, `pyyaml`

## 工作流程

项目的工作流程分为两个主要阶段：

**阶段一：分析与场景生成**
![阶段一流程图](https://dummyimage.com/800x200/d3d3d3/000000.png&text=Workflow+Phase+1)

1.  **输入**: 提供一个 `.srt` 字幕文件。
2.  **处理**:
    -   运行 `analysis.py` 脚本。
    -   脚本解析 SRT 文件，并调用 Ollama LLM 进行语义分析。
    -   LLM 将字幕分割成场景，并为每个场景生成关键词。
3.  **输出**: 在 `storage/tasks/{task_id}/` 目录下生成一个 `scenes.json` 文件。
4.  **人工审核**: 用户可以打开 `scenes.json` 文件，检查、修改或优化场景文本和关键词，以确保后续素材的准确性。

**阶段二：素材搜集与视频合成**
![阶段二流程图](https://dummyimage.com/800x200/d3d3d3/000000.png&text=Workflow+Phase+2)

1.  **输入**:
    -   阶段一生成的 `task_id`。
    -   一个音频文件 (如 `.mp3`, `.wav`)。
2.  **处理**:
    -   运行 `composition.py` 脚本。
    -   脚本读取 `scenes.json` 文件。
    -   根据关键词，`AssetManager` 从配置的源下载视频素材。
    -   `VideoComposer` 将所有素材片段进行裁剪、标准化，然后与音频拼接，并根据需要烧录字幕。
3.  **输出**: 在 `storage/tasks/{task_id}/` 目录下生成最终的视频文件 `final_video.mp4`。

## 如何使用

### 1. 环境准备

- **安装 FFmpeg**: 确保您的系统中已安装 FFmpeg，并已将其添加到系统环境变量中。
- **安装 Python 依赖**:
  ```bash
  pip install -r requirements.txt
  ```
- **设置 Ollama**:
  -   请参考 [Ollama 官网](https://ollama.com/) 的说明安装并运行 Ollama 服务。
  -   拉取一个你希望使用的模型，例如 `qwen2:7b-instruct`：
    ```bash
    ollama pull qwen2:7b-instruct
    ```

### 2. 配置文件

-   将 `config.yaml.template` 复制为 `config.yaml`。
-   打开 `config.yaml` 并根据您的需求进行配置：
    -   **`llm`**: 设置 Ollama 服务的地址和要使用的模型名称。
    -   **`asset_providers`**: 配置素材源的 API Keys (例如 Pexels)。
    -   **`video`**: 设置视频的默认分辨率、帧率、字幕样式等。

### 3. 运行脚本

**阶段一: 分析字幕**

```bash
python analysis.py -s "path/to/your/subtitle.srt"
```

执行后，脚本会输出一个 `task_id`。请记下这个 ID。然后，您可以去 `storage/tasks/{task_id}/scenes.json` 检查并修改场景数据。

**阶段二: 合成视频**

```bash
python composition.py -id "your-task-id" -a "path/to/your/audio.mp3" -s
```

-   `-id`: 替换为阶段一生成的 `task_id`。
-   `-a`: 替换为您的音频文件路径。
-   `-s` (或 `--subtitles`): 一个可选参数，用于烧录字幕。
    -   只使用 `-s`：程序会根据 `scenes.json` 的内容自动生成字幕。
    -   使用 `-s path/to/your/subtitle.srt`：程序会使用您指定的外部字幕文件。
    -   不使用此参数：最终视频将不包含字幕。

### 4. 运行 API 服务

如果您希望通过 API 的方式来使用，可以运行 `api/main.py`：

```bash
uvicorn src.api.main:app --host 0.0.0.0 --port 9001 --reload

or

python src/api/main.py --host 0.0.0.0 --port 9001 --reload
```

启动后，您可以访问 `http://localhost:8000/docs` 查看 Swagger UI 和 API 文档。

### API 端点

以下是主要的 API 端点及其用法：

#### 1. 分析场景并生成关键词

- **URL**: `/tasks/{task_id}/analysis`
- **方法**: `POST`
- **描述**: 对指定任务执行场景分析和关键词生成。此端点将任务从“有字幕”阶段推进到“场景和关键词就绪”阶段，最终产出 `final_scenes.json` 文件。
- **路径参数**:
    - `task_id` (string, 必需): 任务的唯一标识符。
- **请求头**:
    - `Authorization`: `Bearer YOUR_TOKEN` (必需): 用于认证的 Bearer Token。
- **请求体**: 无
- **响应示例**:
```json
{
  "task_id": "your-task-id",
  "status": "success",
  "message": "Scene analysis and keyword generation completed.",
  "scenes_url": "http://localhost:8000/static/storage/tasks/your-task-id/final_scenes.json",
  "summary": {
    "scenes_count": 15
  }
}
```

#### 2. 合成最终视频

- **URL**: `/tasks/{task_id}/compose`
- **方法**: `POST`
- **描述**: 将所有处理好的场景、素材和音频合成为最终的视频文件。此步骤要求 `final_scenes.json` 和 `final_audio.wav` 文件已存在于任务目录中。
- **路径参数**:
    - `task_id` (string, 必需): 任务的唯一标识符。
- **请求头**:
    - `Authorization`: `Bearer YOUR_TOKEN` (必需): 用于认证的 Bearer Token。
- **请求体**:
```json
{
  "embed_subtitles": true
}
```
    - `embed_subtitles` (boolean, 可选): 是否将字幕硬编码到视频中。默认为 `true`。
- **响应示例**:
```json
{
  "task_id": "your-task-id",
  "status": "success",
  "message": "Video composition completed successfully.",
  "video_url": "http://localhost:8000/static/storage/tasks/your-task-id/final_video.mp4"
}
```

## 目录结构

```
.
├── api/                # FastAPI 相关代码
│   ├── routers/        # API 路由模块
│   └── main.py         # API 入口文件
├── assets/             # 存放字体等静态资源
├── input/              # 存放输入的 srt 和 wav 文件示例
├── src/                # 项目核心逻辑
│   ├── core/           # 核心组件 (场景分割, 素材管理, 视频合成)
│   ├── providers/      # 素材源提供者 (Pexels, 本地等)
│   └── ...             # 其他工具和模块
├── storage/            # 存储任务数据和输出文件
│   ├── tasks/          # 每个子目录代表一个任务
│   └── uploads/        # API 上传的文件
├── analysis.py         # 阶段一：分析与场景生成脚本
├── composition.py      # 阶段二：素材搜集与视频合成脚本
├── config.yaml         # 配置文件 (需从 .template 创建)
├── requirements.txt    # Python 依赖列表
└── README.md           # 本文档
