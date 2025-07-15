import os
from fastapi import FastAPI
from fastapi.openapi.utils import get_openapi

from api.routers import analysis, composition, status, download
from api.auth import API_KEY_NAME

app = FastAPI(title="Video Composition API", version="1.0.0")

# 挂载路由
app.include_router(analysis.router)
app.include_router(composition.router)
app.include_router(status.router)
app.include_router(download.router)

# 自定义 OpenAPI，让 Swagger UI 出现 Authorize 弹窗
def custom_openapi():
    if app.openapi_schema:
        return app.openapi_schema
    schema = get_openapi(
        title=app.title,
        version=app.version,
        routes=app.routes,
    )
    schema["components"]["securitySchemes"] = {
        "ApiKeyAuth": {
            "type": "apiKey",
            "in": "header",
            "name": API_KEY_NAME,
        }
    }
    for path_item in schema["paths"].values():
        for op in path_item.values():
            op.setdefault("security", []).append({"ApiKeyAuth": []})
    app.openapi_schema = schema
    return schema

app.openapi = custom_openapi

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
sss