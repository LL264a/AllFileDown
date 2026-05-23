"""
Allfiledown — Utils 单元测试
"""

from __future__ import annotations


class TestFormatFileSize:
    """文件大小格式化测试"""

    def test_zero(self) -> None:
        """0 字节应显示 '未知'"""
        from app.web.routes import _format_file_size

        assert _format_file_size(0) == "未知"

    def test_none(self) -> None:
        """None 应显示 '未知'"""
        from app.web.routes import _format_file_size

        assert _format_file_size(None) == "未知"

    def test_bytes(self) -> None:
        """B 级别"""
        from app.web.routes import _format_file_size

        result: str = _format_file_size(500)
        assert "500" in result
        assert "B" in result or "KB" not in result

    def test_kilobytes(self) -> None:
        """KB 级别"""
        from app.web.routes import _format_file_size

        result: str = _format_file_size(2048)
        assert "KB" in result

    def test_megabytes(self) -> None:
        """MB 级别"""
        from app.web.routes import _format_file_size

        result: str = _format_file_size(5 * 1024 * 1024)
        assert "MB" in result

    def test_gigabytes(self) -> None:
        """GB 级别"""
        from app.web.routes import _format_file_size

        result: str = _format_file_size(3 * 1024 * 1024 * 1024)
        assert "GB" in result

    def test_terabytes(self) -> None:
        """TB 级别"""
        from app.web.routes import _format_file_size

        result: str = _format_file_size(5 * 1024**4)
        assert "TB" in result


class TestResolvePublicHost:
    """地址解析测试"""

    def test_public_ip_unchanged(self) -> None:
        """公开 IP 不应该被替换"""
        from app.web.routes import _resolve_public_host

        result: str = _resolve_public_host("8.8.8.8")
        assert result == "8.8.8.8"

    def test_domain_unchanged(self) -> None:
        """域名不应该被替换"""
        from app.web.routes import _resolve_public_host

        result: str = _resolve_public_host("example.com")
        assert result == "example.com"
