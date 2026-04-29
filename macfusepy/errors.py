import os


class FuseOSError(OSError):
    """把 errno 值包装成可被 FUSE 回调桥识别的异常。"""

    def __init__(self, err: int) -> None:
        """使用 ``err`` 对应的系统错误消息初始化异常。"""
        super().__init__(err, os.strerror(err))
