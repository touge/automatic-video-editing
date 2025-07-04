import uvicorn
from fastapi import FastAPI, Depends
from api.endpoints import router as api_router
from api.auth import verify_api_key

app = FastAPI(
    title="智能视频剪辑工具 API",
    description="通过API驱动的自动化视频剪辑流程",
    version="1.0.0",
)

# 包含来自endpoints.py的路由
app.include_router(api_router, dependencies=[Depends(verify_api_key)])

@app.get("/", summary="API根路径", include_in_schema=False)
async def root():
    return {"message": "欢迎使用智能视频剪辑工具 API。请访问 /docs 查看API文档。"}

if __name__ == "__main__":
    # 运行命令: uvicorn api.main:app --host 0.0.0.0 --port 8000 --reload
    # 注意：uvicorn命令需要从项目根目录运行，以确保模块路径正确。
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
