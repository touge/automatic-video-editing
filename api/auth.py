import sys
import os
from fastapi import Security, HTTPException, status
from fastapi.security import APIKeyHeader

# 将项目根目录添加到Python路径，以便能导入 'src' 模块
# 这是因为API服务在子目录中运行
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from src.utils import load_config

API_KEY_HEADER = APIKeyHeader(name="X-API-Key", auto_error=False)

def get_api_key() -> str:
    """从配置加载API密钥"""
    config = load_config()
    return config.get('api_server', {}).get('secret_key', '')

def verify_api_key(api_key: str = Security(API_KEY_HEADER)):
    """FastAPI依赖项，用于验证API密钥"""
    if not api_key:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="请求头中缺少 X-API-Key")
    
    expected_key = get_api_key()
    if not expected_key or "YOUR_SUPER_SECRET_API_KEY" in expected_key:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="API服务未配置安全密钥，请检查config.yaml文件。"
        )
    if api_key != expected_key:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="无效的API密钥")