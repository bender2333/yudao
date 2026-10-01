# 更新源与应用安装包：读取 Yudao 服务的 wheel 内的发布资源目录。桌面客户端从这里更新，
# 执行代理从同一个目录取得安装包（桌面客户端的安装、更新与发布设计说明第 5.1 节，ADR-0023）。
# 从源码运行没有这个目录，读取以「没有客户端安装包」结束，接口层据此返回 404。

from __future__ import annotations

from pathlib import Path

# 发布资源目录：被 git 忽略，发布脚本把客户端安装程序、blockmap、latest.yml 与执行代理的 wheel 放进去
RELEASE_ASSETS = Path(__file__).resolve().parent.parent / "release_assets"
# 没有发布资源时给用户的原因
NO_INSTALLER = "没有客户端安装包"

class ReleaseAssetNotFound(FileNotFoundError):
    # 发布资源目录不存在，或者请求的文件不在其中
    pass

class ReleaseAssets:
    def __init__(self, directory: Path | None = None) -> None:
        self.directory = RELEASE_ASSETS if directory is None else Path(directory)

    def available(self) -> bool:
        # 发布资源目录存在且是一个目录
        return self.directory.is_dir()

    def latest_manifest(self) -> Path:
        # 更新清单 latest.yml；没有发布资源时说明原因
        return self._file("latest.yml")

    def installer(self, name: str) -> Path:
        # 客户端安装程序或它的 blockmap；名字只允许是发布资源目录中的文件名，不接受路径分隔符
        return self._file(name)

    def _file(self, name: str) -> Path:
        if not self.available():
            raise ReleaseAssetNotFound(NO_INSTALLER)
        # 只提供目录中的文件，不接受路径分隔符与上级引用，防止读到发布资源目录之外
        if name != Path(name).name or name in ("", ".", ".."):
            raise ReleaseAssetNotFound(NO_INSTALLER)
        path = self.directory / name
        if not path.is_file():
            raise ReleaseAssetNotFound(NO_INSTALLER)
        return path
