from .base import DigitalHumanProvider
from .heygem import HeygemProvider
from ...config_loader import config

def get_digital_human_provider() -> DigitalHumanProvider:
    # 从全局配置中获取 heygem_api 的设置
    heygem_config = config.get('heygem_api')
    if heygem_config:
        return HeygemProvider(
            endpoint=heygem_config.get("endpoint"),
            token=heygem_config.get("token")
        )
    # 如果没有找到相关配置，则抛出错误
    raise ValueError("Heygem API provider not configured in config.yaml")
