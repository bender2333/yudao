# 页面文件（网页界面的提供与发布设计说明第 5.1 节）：/api/ 与 /openapi.json 之外的 GET 路径按文件路径
# 返回构建好的页面文件。页面文件只读、不含数据，不经过注册表，不列入 OpenAPI 与能力清单。

from __future__ import annotations

import json
from pathlib import Path

from starlette.responses import JSONResponse, Response
from starlette.staticfiles import StaticFiles
from starlette.types import Scope

# 发布资源目录（网页界面的提供与发布设计说明第 5.1、6.1 节）：被 git 忽略，
# 发布脚本把页面文件与执行代理的 wheel 放进去，随 wheel 一起发布
RELEASE_ASSETS = Path(__file__).resolve().parent.parent / "release_assets"
# 页面文件对应的接口版本写在发布资源目录的这个文件里（工单 #704）
PAGES_API_VERSION_FILE = "api-version.json"
# 从源码运行而没有构建页面时给用户的原因
NO_PAGES = "没有页面文件"
# Vite 把带内容摘要的文件放在 assets/ 下，文件名随内容改变，可以长期缓存
HASHED_DIRECTORY = "assets"


def pages_api_version() -> int | None:
    """这一份页面文件对应哪个接口版本；没有页面文件或没有写下版本时为空。

    发布脚本复制页面文件时一并写下这个版本（工单 #704）：服务与页面不匹配时，
    运维与日志能说清是哪一边落后了。
    """
    source = RELEASE_ASSETS / PAGES_API_VERSION_FILE
    try:
        document = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    version = document.get("api_version") if isinstance(document, dict) else None
    return version if isinstance(version, int) else None

class PageFiles(StaticFiles):
    def __init__(self, directory: Path) -> None:
        # 目录可以不存在（从源码运行）：请求时按「没有页面文件」回答
        super().__init__(directory=directory, html=True, check_dir=False)
        self.index = Path(directory) / "index.html"

    async def check_config(self) -> None:
        # 没有页面文件时不核对目录，由 get_response 写明原因
        if self.index.is_file():
            await super().check_config()

    async def get_response(self, path: str, scope: Scope) -> Response:
        # 没有匹配的接口路径不当作页面文件
        if path.split("\\")[0].split("/")[0] == "api":
            return Response(status_code=404)
        if not self.index.is_file():
            return JSONResponse(status_code=404, content={"error": NO_PAGES})
        response = await super().get_response(path, scope)
        # 入口页面与其他不带摘要的文件每次向服务确认；带摘要的文件长期缓存
        hashed = path.replace("\\", "/").startswith(HASHED_DIRECTORY + "/")
        response.headers["Cache-Control"] = "public, max-age=31536000, immutable" if hashed else "no-cache"
        return response
