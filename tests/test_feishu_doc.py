# -*- coding: utf-8 -*-
"""飞书云文档创建的行为契约测试。

重点守护：内容写入失败时不得返回文档链接。否则上游会判定投递成功并跳过
长文本推送，群里最终只收到一个空白文档，而运行日志看起来一切正常。
"""
from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from src import feishu_doc as feishu_doc_module
from src.feishu_doc import FeishuDocManager


def _build_config() -> SimpleNamespace:
    return SimpleNamespace(
        feishu_app_id="cli_test",
        feishu_app_secret="secret_test",
        feishu_folder_token="fld_test",
    )


def _build_manager() -> FeishuDocManager:
    with patch.object(feishu_doc_module, "get_config", return_value=_build_config()):
        return FeishuDocManager()


def _create_response(success: bool, doc_id: str = "doc_test") -> MagicMock:
    response = MagicMock()
    response.success.return_value = success
    if success:
        response.data.document.document_id = doc_id
    else:
        response.code = 400
        response.msg = "create failed"
        response.error = MagicMock()
    return response


def _write_response(success: bool) -> MagicMock:
    response = MagicMock()
    response.success.return_value = success
    response.code = 0 if success else 400
    response.msg = "ok" if success else "write failed"
    return response


class FeishuDocManagerTest(unittest.TestCase):
    def _manager_with_client(self, create_ok: bool = True, write_ok: bool = True):
        manager = _build_manager()
        client = MagicMock()
        client.docx.v1.document.create.return_value = _create_response(create_ok)
        client.docx.v1.document_block_children.create.return_value = _write_response(write_ok)
        manager.client = client
        return manager, client

    def test_create_daily_doc_returns_url_on_success(self):
        manager, client = self._manager_with_client()

        url = manager.create_daily_doc("标题", "# 大盘复盘\n\n正文内容")

        self.assertEqual(url, "https://feishu.cn/docx/doc_test")
        client.docx.v1.document_block_children.create.assert_called_once()

    def test_create_daily_doc_returns_none_when_content_write_fails(self):
        """写入失败必须返回 None，让上游回退为长文本推送。"""
        manager, _ = self._manager_with_client(write_ok=False)

        url = manager.create_daily_doc("标题", "# 大盘复盘\n\n正文内容")

        self.assertIsNone(url)

    def test_create_daily_doc_returns_none_when_content_is_blank(self):
        """内容为空时不应返回一个空白文档的链接。"""
        manager, client = self._manager_with_client()

        url = manager.create_daily_doc("标题", "   \n\n  \n")

        self.assertIsNone(url)
        client.docx.v1.document_block_children.create.assert_not_called()

    def test_create_daily_doc_returns_none_when_doc_create_fails(self):
        manager, _ = self._manager_with_client(create_ok=False)

        url = manager.create_daily_doc("标题", "正文内容")

        self.assertIsNone(url)


if __name__ == "__main__":
    unittest.main()
