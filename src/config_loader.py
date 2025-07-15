import yaml
from pathlib import Path
import os
import sys

# 确保项目根目录在 sys.path 中，以便可以找到 config.yaml
# __file__ 是 logic/config_loader.py, '..' 是 logic, '..' 是项目根目录
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if project_root not in sys.path:
    sys.path.append(project_root)

class Config:
    def __init__(self, config_path='config.yaml'):
        # 确保我们总是从项目根目录加载配置文件
        self.config_path = Path(project_root) / config_path
        self.data = self._load_config()

    def _load_config(self):
        """加载并解析 YAML 配置文件，并解析文件路径引用"""
        if not self.config_path.is_file():
            raise FileNotFoundError(f"配置文件未找到: {self.config_path}")
        with open(self.config_path, 'r', encoding='utf-8') as f:
            config_data = yaml.safe_load(f)
        self._resolve_paths(config_data)
        return config_data

    def _resolve_paths(self, data):
        """递归地解析配置文件中指向 .md 文件的路径"""
        if isinstance(data, dict):
            for key, value in data.items():
                data[key] = self._resolve_paths(value)
        elif isinstance(data, list):
            for i, item in enumerate(data):
                data[i] = self._resolve_paths(item)
        elif isinstance(data, str) and data.endswith('.md'):
            file_path = Path(project_root) / data
            if file_path.is_file():
                with open(file_path, 'r', encoding='utf-8') as f:
                    return f.read().strip()
        return data

    def get(self, key_path, default=None):
        """
        通过点分隔的路径获取配置项
        例如: get('server.port', 8000)
        """
        keys = key_path.split('.')
        value = self.data
        try:
            for key in keys:
                value = value[key]
            return value
        except (KeyError, TypeError):
            return default

    def __getattr__(self, name):
        """允许通过属性访问顶层配置项, e.g., config.server"""
        if name in self.data:
            value = self.data[name]
            if isinstance(value, dict):
                return _AttrDict(value)
            return value
        return None

class _AttrDict(dict):
    """一个允许通过属性访问其键的字典"""
    def __init__(self, *args, **kwargs):
        super(_AttrDict, self).__init__(*args, **kwargs)
        for key, value in self.items():
            if isinstance(value, dict):
                self[key] = _AttrDict(value)

    def __getattr__(self, attr):
        return self.get(attr)

    def __setattr__(self, key, value):
        self.__setitem__(key, value)

# 创建一个全局配置实例，供整个项目导入和使用
# e.g., from logic.config_loader import config
#      port = config.server.port
config = Config()

if __name__ == '__main__':
    # 测试配置加载器
    print("服务器端口:", config.get('server.port'))
    print("数据库URL:", config.database.url)
    print("支持的视频格式:", config.paths.video_extensions)
    print("默认正向阈值:", config.get('model.defaults.positive_threshold'))
    print("Assets Path:", config.paths.assets)
    print("database.url:", config.database.url)
    print("temp_path:", config.get('paths.temp'))
    print("video_extensions", config.paths.video_extensions)
    # print("Assets Path:", config.paths.assets)
