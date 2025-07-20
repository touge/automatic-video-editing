# 素材收集工作流程文档

本文档详细描述了自动视频编辑项目中，为每个子场景查找、下载和验证视频素材的工作流程。

## 概述

素材收集的目标是为 `final_scenes.json` 中的每一个子场景（sub-scene），根据其关键词（keywords），找到一个符合要求的、唯一的视频素材。整个流程被设计为健壮且可容错的，它会尝试多个视频源（Provider）和多个关键词，直到找到一个可用的素材为止。

## 核心组件

整个流程主要由以下三个核心组件协同工作：

1.  **`VideoCompositionLogic`** (`src/logic/video_composer_logic.py`)
    - **角色**：高级流程编排器。
    - **职责**：启动并管理为每个子场景寻找素材的循环。它调用 `AssetManager` 来完成查找工作，并接收最终找到的单个素材。

2.  **`AssetManager`** (`src/core/asset_manager.py`)
    - **角色**：素材查找、下载与验证器。
    - **职责**：这是素材查找的核心。它管理多个 `Provider`，并完整地负责“找到第一个可用素材”的全部流程，包括遍历 `Provider` 和关键词、API请求、去重、下载以及文件有效性验证。

3.  **`Providers`** (`src/providers/search/`)
    - **角色**：实际的视频搜索接口。
    - **职责**：封装了对 Pexels、Pixabay、AI Search 等第三方视频源的 API 调用。

## 工作流程详解

素材查找遵循“找到第一个就停止” (Find-First-and-Done) 的高效原则。

### 第1步：启动流程

-   流程由 `VideoCompositionLogic._find_assets_for_sub_scenes` 方法为每个子场景（sub-scene）启动。
-   它调用 `asset_manager.find_assets_for_scene()`，并等待返回结果。

### 第2步：查找、下载与验证 (`AssetManager`)

`AssetManager` 内部的 `_find_and_validate_asset` 方法执行一个详尽的循环，直到找到一个完全可用的素材为止：

1.  **遍历 `Provider`**：按照优先级（默认为 AI Search -> Pexels -> Pixabay）开始遍历。

2.  **遍历关键词**：对于当前的 `Provider`，开始遍历子场景中的所有 `keyword`。

3.  **API 请求**：
    -   使用当前关键词向 `Provider` 的 API 发起搜索请求。
    -   请求时会附带 `online_search_count` 参数，告诉 `Provider` 单次返回多少个视频结果。这批返回的结果是当前关键词的“候选池”。

4.  **遍历候选池**：程序开始遍历这个刚刚从API获取的“候选池”列表。
    a. **去重**：检查当前视频是否已在全局的 `used_source_ids` 集合中，或者是否触发了针对 `AI Search` 的特殊去重规则（详见下文）。如果是，则跳过，继续处理候选池中的下一个视频。
    b. **下载**：如果视频是新的，则调用 `_download_asset` 方法尝试下载。如果下载失败，记录警告并继续处理候选池中的下一个视频。
    c. **验证**：如果下载成功，立即调用 `get_video_duration()` 检查文件是否有效。如果文件无效（例如损坏），则删除该文件，记录警告，并继续处理候选池中的下一个视频。

5.  **成功并立即返回**：
    -   一旦某个视频成功通过了去重、下载和验证，它就被视为最终可用的素材。
    -   `AssetManager` 会立即停止**所有**循环（不再尝试候选池中的其他视频，不再尝试其他关键词，也不再尝试其他 `Provider`）。
    -   它将这个已验证通过的素材信息返回给 `VideoCompositionLogic`。

### 第3步：分配

-   `VideoCompositionLogic` 接收到 `AssetManager` 返回的单个有效素材后，将其路径和时长信息更新到当前的子场景中。
-   然后，它开始为下一个子场景重复整个流程。

### 第4步：失败处理

-   只有在 `AssetManager` 遍历了**所有 `Provider`** 的**所有 `keyword`** 返回的**所有候选池**中的**所有视频**后，仍然没有找到一个能成功通过所有步骤的素材时，查找过程才被视为最终失败。此时，它会返回 `None`，并中断整个任务。

## Provider 特定逻辑与去重机制

系统在搜集素材时，会按特定顺序和规则处理不同的 `Provider`，并应用多层去重机制。

### Provider 优先级

`AssetManager` 按照 `self.video_providers` 列表中的顺序依次尝试 `Provider`。默认的优先级顺序是：
1.  **`AiSearchProvider`** (最高优先级)
2.  **`PexelsProvider`**
3.  **`PixabayProvider`**

**重要**：一旦在某个 `Provider` 中找到了一个最终可用的素材，系统就会立即停止，**不会**再尝试后续的 `Provider`。

### 去重机制 (Deduplication)

为了确保视频素材的多样性，系统采用了两层去重逻辑：

1.  **全局ID去重 (`used_source_ids`)**:
    -   这是一个全局的 `Set`，用于存储所有已被成功分配给某个场景的素材的唯一ID (`unique_id`)。
    -   此规则适用于**所有** `Provider`。在搜集候选素材时，任何 `id` 已存在于此集合中的素材都会被立即跳过。
    -   这是防止在同一个视频项目中重复使用完全相同素材的主要机制。

2.  **AI搜索名称去重 (`used_ai_video_names`)**:
    -   这是一个特殊的 `Set`，**只存储**来自 `AiSearchProvider` 的已用素材的 `video_name`。
    -   当系统轮到标准 `Provider`（如 Pexels, Pixabay）时，会触发一条特殊规则：如果一个标准 `Provider` 返回的素材，其 `video_name` 已经存在于 `used_ai_video_names` 集合中，那么这个素材也会被跳过。
    -   **目的**：此机制旨在防止标准 `Provider` 选中一个与 `AI Search` 已选中的素材内容上相似或相同的通用素材。这提升了素材的独特性，避免了“AI选了一个，Pexels又选了一个长得一样的”情况。

### `AiSearchProvider`

-   **下载位置**: 作为最高优先级的 `Provider`，它找到的素材被认为是高度相关的。这些素材被下载到与当前任务绑定的**临时目录**中：`tasks/<task_id>/.videos/ai_search_temp/`。
-   这些素材不会进入全局缓存，仅用于本次视频生成。

### 标准 `Provider` (Pexels, Pixabay)

-   **下载位置**: 这些 `Provider` 的素材被视为通用库存素材，适合跨任务复用。它们被下载到**全局的本地缓存**中，按日期存放：`assets/local/YYYY-MM-DD/`。
-   在未来的任务中，如果需要相同的素材，系统可以直接从本地缓存读取（此功能当前在代码中被注释，但文件结构已为此设计）。

## 相关配置

此流程的行为可以通过 `config.yaml` 中的 `asset_search` 部分进行配置：

-   `online_search_count`: 控制**单次API调用**向 `Provider` 请求返回多少个视频结果。增加此值可以增大在一次请求中就找到可用素材的几率，从而可能减少总的API请求次数。
-   `request_delay_seconds`: 两次API请求之间的最小时间间隔，用于遵守第三方API的速率限制，避免被封禁。
