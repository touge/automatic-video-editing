import os
import requests
import random

def search_local_assets(keywords: list, local_path: str) -> str | None:
    """
    根据关键词在本地素材库中搜索。
    这是一个简单的实现，仅通过文件名匹配。
    :param keywords: 关键词列表
    :param local_path: 本地素材库路径
    :return: 匹配到的素材路径，如果没有则返回None
    """
    print(f"正在本地搜索: {keywords}")
    all_files = [f for f in os.listdir(local_path) if os.path.isfile(os.path.join(local_path, f))]
    for keyword in keywords:
        for file in all_files:
            if keyword.lower() in file.lower():
                print(f"在本地找到匹配素材: {file}")
                return os.path.join(local_path, file)
    return None

def search_online_assets(keywords: list, api_key: str, temp_dir: str) -> str | None:
    """
    使用Pexels API搜索并下载视频素材。
    :param keywords: 关键词列表
    :param api_key: Pexels API Key
    :param temp_dir: 下载视频的临时存放目录
    :return: 下载的视频文件路径，如果失败则返回None
    """
    if not keywords:
        return None
    query = " ".join(keywords)
    print(f"正在在线搜索: {query}")
    try:
        headers = {"Authorization": api_key}
        url = f"https://api.pexels.com/videos/search?query={query}&per_page=1"
        res = requests.get(url, headers=headers)
        res.raise_for_status()
        
        video_files = res.json().get("videos", [])[0].get("video_files", [])
        # 选择一个中等质量的视频进行下载
        video_link = next((v['link'] for v in video_files if 'hd' in v['quality']), video_files[0]['link'])
        
        video_res = requests.get(video_link)
        video_res.raise_for_status()

        output_path = os.path.join(temp_dir, f"{query.replace(' ', '_')}_{random.randint(1000,9999)}.mp4")
        with open(output_path, 'wb') as f:
            f.write(video_res.content)
        print(f"视频已下载到: {output_path}")
        return output_path
    except Exception as e:
        print(f"在线搜索或下载失败: {e}")
        return None

