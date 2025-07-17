from fastapi import Security, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from src.config_loader import config

# 将 APIKeyHeader 替换为 HTTPBearer
bearer_scheme = HTTPBearer(auto_error=False)

def get_valid_tokens():
    """Retrieves the list of valid API tokens from the configuration."""
    api_config = config.get('api_server', {})
    return api_config.get('tokens', [])

async def verify_token(credentials: HTTPAuthorizationCredentials = Security(bearer_scheme)):
    """
    Dependency to verify the API token provided in the Authorization: Bearer header.
    """
    valid_tokens = get_valid_tokens()
    
    # 如果没有配置 token，则允许访问。
    # 对于更安全的设置，您可能希望拒绝访问。
    if not valid_tokens:
        return
    
    # 检查 credentials 是否存在且 token 是否有效
    if not credentials or credentials.credentials not in valid_tokens:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing Bearer token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return credentials.credentials # 返回 token，如果需要的话
