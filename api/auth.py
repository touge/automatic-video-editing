import os
from fastapi import HTTPException, Security, Depends, status
from fastapi.security.api_key import APIKeyHeader
from src.utils import load_config

def get_api_key() -> str:
    """
    从配置文件读取 API 密钥
    """
    config_path = os.getenv("CONFIG_PATH", "config.yaml")
    config = load_config(config_path)
    return config.get("api_server", {}).get("secret_key", "")

# 客户端在请求头 X-API-Key 中传递密钥
API_KEY_NAME   = "X-API-Key"
api_key_header = APIKeyHeader(name=API_KEY_NAME, auto_error=False)

async def verify_api_key(
    api_key: str    = Security(api_key_header),
    secret_key: str = Depends(get_api_key),
):
    if not api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing API Key"
        )
    if api_key != secret_key:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid API Key"
        )
    return api_key
