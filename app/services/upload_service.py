# -*- coding: utf-8 -*-
"""面单照片上传：类型白名单 + 随机文件名 + 按月分目录 + magic bytes 校验"""
import uuid
from datetime import datetime

from flask import current_app

ALLOWED_EXTENSIONS = {"jpg", "jpeg", "png", "webp"}

# 各扩展名的文件头 magic bytes（校验真实内容，防止改名 polyglot 绕过）
_MAGIC_BYTES = {
    "jpg": b"\xff\xd8\xff",
    "jpeg": b"\xff\xd8\xff",
    "png": b"\x89\x50\x4e\x47\x0d\x0a\x1a\x0a",
}


def allowed_file(filename: str) -> bool:
    if "." not in (filename or ""):
        return False
    ext = filename.rsplit(".", 1)[1].lower()
    return ext in ALLOWED_EXTENSIONS


def _has_valid_magic(ext: str, header: bytes) -> bool:
    """校验文件头是否与扩展名一致（webp 需同时校验 RIFF 与偏移 8 处的 WEBP）。"""
    if ext == "webp":
        return header[:4] == b"RIFF" and header[8:12] == b"WEBP"
    signature = _MAGIC_BYTES.get(ext)
    return signature is not None and header.startswith(signature)


def save_photo(file_storage) -> str:
    """保存照片并返回相对路径（如 202505/ab12cd.jpg），供 /uploads/<path> 访问。

    文件大小由 Flask 的 MAX_CONTENT_LENGTH 统一拦截（>10MB 返回 413）。
    除扩展名白名单外，另读文件头 magic bytes 校验真实图片格式。
    """
    filename = file_storage.filename if file_storage else ""
    if not filename:
        raise ValueError("未选择图片文件")
    if not allowed_file(filename):
        raise ValueError("仅支持 jpg/jpeg/png/webp 格式图片")

    ext = filename.rsplit(".", 1)[1].lower()
    # 读文件头校验 magic bytes，防止伪装扩展名
    file_storage.stream.seek(0)
    header = file_storage.stream.read(16)
    file_storage.stream.seek(0)  # 重置，供 save 从开头写入
    if not _has_valid_magic(ext, header):
        raise ValueError("文件内容与扩展名不符，仅支持真实的 jpg/png/webp 图片")

    subdir = datetime.now().strftime("%Y%m")
    target_dir = current_app.config["UPLOAD_DIR"] / subdir
    target_dir.mkdir(parents=True, exist_ok=True)

    new_name = uuid.uuid4().hex + "." + ext
    file_storage.save(str(target_dir / new_name))
    return f"{subdir}/{new_name}"
