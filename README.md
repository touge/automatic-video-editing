# 智能视频剪辑工具 (Auto-Cut-Tool)

这是一个强大的自动化视频剪辑工具，它能将一个简单的字幕文件（SRT）和一个音频文件，智能地转化为一个配有高质量素材、节奏感强的视频。

该工具利用大语言模型（LLM）进行语义分析，自动完成场景分割、关键词提取、素材搜索和视频合成，极大地简化了视频创作流程。

## ✨ 核心功能

- **智能场景分割**: 使用Ollama本地大模型，根据字幕内容的语义逻辑，自动将文稿分割成连贯的场景。
- **多语言关键词提取**: 利用Google Gemini API，为每个场景提取中英文双语关键词，确保素材搜索的精准性。
- **自动化素材搜集**:
  - **本地素材库**: 优先从本地 `assets/local` 目录搜索匹配的素材。
  - **在线下载与缓存**: 当本地素材不足时，自动从Pexels.com搜索、下载高质量视频素材，并将其缓存到本地（按日期分目录），以便未来复用。
  - **数据库索引**: 所有本地素材（包括下载的）都会被记录在SQLite数据库 (`storage/asset_library.db`) 中，实现秒级关键词检索，告别文件系统扫描的性能瓶颈。
- **动态素材切分**: 对于时长较长的场景，工具会自动计算并匹配多个视频片段，使视觉效果更丰富、不单调。
- **灵活的视频合成**:
  - 使用 `ffmpeg` 进行专业的视频合成。
  - 支持将音频与视频片段精确对齐。
  - 支持多种字幕烧录方式：不加字幕、自动生成字幕、或使用外部指定的SRT文件。

## ⚙️ 环境准备

1.  **Python 环境**: 推荐使用 Python 3.10 或更高版本。
2.  **FFmpeg**: 确保你的系统中已安装 `ffmpeg`。
    - **macOS (使用 Homebrew)**: `brew install ffmpeg`
    - **Windows**: 从 官网 下载并将其可执行文件路径添加到系统环境变量中。
3.  **Ollama (可选，推荐)**: 如果你想使用本地大模型进行场景分割，请先安装并运行 Ollama，并拉取所需模型（如 `ollama pull qwen2:7b`）。

## 🚀 安装与配置

1.  **克隆项目**
    ```bash
    git clone <your-repo-url>
    cd auto-cut-tool
    ```

2.  **安装依赖**
    项目的所有依赖都已在 `requirements.txt` 中列出。运行以下命令进行安装：
    ```bash
    pip install -r requirements.txt
    ```

3.  **配置 API Keys**
    打开 `config.yaml` 文件，填入你的API Keys，并根据需要配置Ollama。
    ```yaml
    # ...
    
    # 前往 https://www.pexels.com/api/ 获取你的免费API Key
    pexels:
      api_key: "YOUR_PEXELS_API_KEY_HERE"
    
    # 前往 https://aistudio.google.com/app/apikey 获取你的免费API Key
    gemini:
      api_key: "YOUR_GEMINI_API_KEY_HERE"
    
    # Ollama 本地大模型配置
    ollama:
      model: "qwen2:7b" # 或者 "llama3" 等你已拉取的模型
      host: "http://localhost:11434" # Ollama服务地址
      
    # ...
    ```

## 🎬 使用流程

整个工作流分为两个阶段，由两个独立的脚本执行。

### **阶段一：分析字幕，生成场景草稿**

这个阶段会读取你的SRT字幕文件，进行场景分割和关键词提取，并生成一个可供你审核和修改的 `scenes.json` 文件。

**命令格式**:
```bash
python run_stage_1_analysis.py --with-subtitles /path/to/your/subtitle.srt
```

**执行后**:
- 脚本会输出一个唯一的 **任务ID (Task ID)**，例如 `43c03346-ea44-479f-9f6a-78a0cbcff477`。**请务必记下这个ID**。
- 同时会生成一个任务目录 `storage/tasks/<your-task-id>/`，其中包含 `scenes.json` 文件。

**手动步骤**:
打开 `storage/tasks/<your-task-id>/scenes.json` 文件。你可以检查、修改或删除每个场景的 `keywords` 和 `keywords_en`，以确保后续素材搜索的准确性。

---

### **阶段二：合成视频**

在你对 `scenes.json` 感到满意后，运行此阶段的脚本来完成视频的最终合成。

**命令格式**:
```bash
python run_stage_2_composition.py \
    --with-task-id <your-task-id> \
    --with-audio /path/to/your/audio.mp3 \
    --with-subtitles /path/to/your/subtitle.srt

python run_stage_2_composition.py --with-task-id <your-task-id> --with-audio /path/to/your/audio.mp3 --with-subtitles /path/to/your/subtitle.srt
```

**参数说明**:
- `--with-task-id`: **必需**。填入阶段一生成的任务ID。
- `--with-audio`: **必需**。指定视频要匹配的音频文件路径。
- `--with-subtitles`: **可选**。用于烧录字幕。
  - `--with-subtitles`: 如果不带路径，会自动使用任务中的 `scenes.json` 生成字幕。
  - `--with-subtitles /path/to/your.srt`: 使用你指定的外部SRT文件进行烧录。
  - 如果省略此参数，则最终视频不带字幕。

**执行后**:
- 工具会自动搜索、下载、缓存素材，并进行视频剪辑与合成。
- 最终的视频文件会保存在 `storage/tasks/<your-task-id>/final_video.mp4`。

## 📁 目录结构

- `assets/local/`: 本地共享素材库。所有下载的视频会按日期（如 `2023-10-27`）存放在这里。
- `storage/asset_library.db`: 本地素材的SQLite索引数据库，用于快速搜索。
- `storage/tasks/`: 存放所有任务的目录。每个子目录代表一次运行。
- `config.yaml`: 全局配置文件。

---

## 🤖 API 服务 (微服务集成)

除了命令行，本工具还提供了一套完整的RESTful API，便于集成到其他微服务或自动化流程中。该API服务被设计为独立模块，不会影响原有的命令行工具。

### **启动 API 服务**

在项目 **根目录** 运行以下命令：
```bash
uvicorn api.main:app --host 0.0.0.0 --port 8000
```
服务启动后，你可以在浏览器中访问 `http://127.0.0.1:8000/docs` 查看交互式的API文档 (Swagger UI)。

### **API 认证**

所有API请求都需要通过API密钥进行认证。
1.  在 `config.yaml` 文件中设置你的 `secret_key`。
2.  在每个请求的Header中加入 `X-API-Key: YOUR_SUPER_SECRET_API_KEY`。

### **API 端点**

- **`POST /v1/analysis`**: 启动阶段一分析任务。
  - **Body**: `multipart/form-data`，包含一个名为 `subtitles` 的SRT文件。
  - **返回**: `{"task_id": "...", "message": "..."}`
- **`POST /v1/composition`**: 启动阶段二合成任务（后台执行）。
  - **Body**: `multipart/form-data`，包含 `task_id` (字符串), `audio` (音频文件), 和可选的 `subtitles` (SRT文件)。
  - **返回**: 立即返回确认信息，任务在后台运行。
- **`GET /v1/status/{task_id}`**: 查询指定任务的状态（`COMPLETED` 或 `PENDING_OR_IN_PROGRESS`）。
- **`GET /v1/download/{task_id}`**: 下载合成完成的视频文件。