from __future__ import annotations

import builtins
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, call, patch

import main
from src.brokers.futu.portfolio import FutuPortfolioError
from src.services.runtime_scheduler import RuntimeSchedulerService


class MainPortfolioTest(unittest.TestCase):
    def test_parse_arguments_accepts_futu_portfolio(self):
        with patch.object(sys, "argv", ["main.py", "--portfolio", "FUTU"]):
            args = main.parse_arguments()

        self.assertEqual(args.portfolio, "futu")

    def test_resolve_portfolio_stock_codes_uses_futu_loader(self):
        args = SimpleNamespace(portfolio="futu")
        with patch(
            "src.brokers.futu.portfolio.load_futu_stock_codes",
            return_value=["aapl", "HK01810", "005930"],
        ) as loader, patch.object(
            main,
            "resolve_index_stock_code_for_analysis",
            side_effect=AssertionError("broker codes must not be remapped"),
        ):
            result = main._resolve_portfolio_stock_codes(args)

        self.assertEqual(result, ["AAPL", "HK01810", "005930"])
        loader.assert_called_once_with()

    def test_resolve_portfolio_stock_codes_returns_none_when_disabled(self):
        self.assertIsNone(main._resolve_portfolio_stock_codes(SimpleNamespace()))

    def test_analysis_lock_propagates_requested_portfolio_failures(self):
        config = SimpleNamespace()
        args = SimpleNamespace(portfolio="futu")
        error = FutuPortfolioError("OpenD unavailable")

        with patch.object(
            main,
            "run_full_analysis",
            side_effect=error,
        ) as runner, self.assertRaisesRegex(FutuPortfolioError, "OpenD unavailable"):
            main._run_analysis_with_runtime_scheduler_lock(
                config,
                args,
                ["600519"],
            )

        runner.assert_called_once_with(config, args, ["600519"])

    def test_run_full_analysis_propagates_futu_portfolio_load_failure(self):
        config = SimpleNamespace()
        args = SimpleNamespace(portfolio="futu")
        error = FutuPortfolioError("OpenD unavailable")

        with patch.object(
            main,
            "_refresh_stock_index_cache_for_analysis",
        ), patch(
            "src.brokers.futu.portfolio.load_futu_stock_codes",
            side_effect=error,
        ), self.assertRaisesRegex(FutuPortfolioError, "OpenD unavailable"):
            main.run_full_analysis(config, args)

    def test_run_full_analysis_keeps_downstream_failures_non_propagating(self):
        config = SimpleNamespace()
        args = SimpleNamespace(portfolio="futu")

        with patch.object(
            main,
            "_refresh_stock_index_cache_for_analysis",
        ), patch(
            "src.brokers.futu.portfolio.load_futu_stock_codes",
            return_value=["AAPL"],
        ), patch.object(
            main,
            "_compute_trading_day_filter",
            side_effect=RuntimeError("calendar unavailable"),
        ):
            result = main.run_full_analysis(config, args)

        self.assertFalse(result)

    def test_run_full_analysis_returns_false_when_stock_analysis_generates_no_reports(self):
        args = SimpleNamespace(
            portfolio=None,
            single_notify=False,
            no_context_snapshot=True,
            no_market_review=True,
            workers=1,
            dry_run=False,
            no_notify=True,
            schedule=False,
        )
        config = SimpleNamespace(
            refresh_stock_list=MagicMock(),
            single_stock_notify=False,
            merge_email_notification=False,
            market_review_enabled=False,
            market_review_region="cn",
            daily_market_context_enabled=False,
            analysis_delay=0,
            backtest_enabled=False,
        )
        pipeline = MagicMock()
        pipeline.run.return_value = []

        with patch.object(main, "_refresh_stock_index_cache_for_analysis"), patch.object(
            main,
            "_compute_trading_day_filter",
            return_value=(["600519"], "cn", False),
        ), patch(
            "src.core.pipeline.StockAnalysisPipeline",
            return_value=pipeline,
        ), patch(
            "src.core.market_review.run_market_review",
        ), patch(
            "src.feishu_doc.FeishuDocManager",
        ) as feishu_manager, patch.object(
            main,
            "_run_auto_backtest",
        ) as run_auto_backtest:
            feishu_manager.return_value.is_configured.return_value = False
            result = main.run_full_analysis(config, args, ["600519"])

        self.assertFalse(result)
        self.assertEqual(main._LAST_ANALYSIS_FAILURE_REASON, "no_report")
        pipeline.run.assert_called_once()
        run_auto_backtest.assert_called_once_with(config)

    def test_run_full_analysis_returns_false_when_stock_list_is_empty_without_market_review(self):
        args = SimpleNamespace(
            portfolio=None,
            single_notify=False,
            no_context_snapshot=True,
            no_market_review=True,
            workers=1,
            dry_run=False,
            no_notify=True,
            schedule=False,
        )
        config = SimpleNamespace(
            refresh_stock_list=MagicMock(),
            stock_list=[],
            single_stock_notify=False,
            merge_email_notification=False,
            market_review_enabled=False,
            market_review_region="cn",
            daily_market_context_enabled=False,
            analysis_delay=0,
            backtest_enabled=False,
        )

        with patch.object(main, "_refresh_stock_index_cache_for_analysis"), patch.object(
            main,
            "_compute_trading_day_filter",
            side_effect=AssertionError("empty STOCK_LIST must fail before trading-day filter"),
        ), patch(
            "src.core.market_review.run_market_review",
        ), patch(
            "src.core.pipeline.StockAnalysisPipeline",
        ) as pipeline_cls, patch.object(
            main,
            "_run_auto_backtest",
        ) as run_auto_backtest:
            result = main.run_full_analysis(config, args)

        self.assertFalse(result)
        self.assertEqual(main._LAST_ANALYSIS_FAILURE_REASON, "empty_stock_list")
        pipeline_cls.assert_not_called()
        run_auto_backtest.assert_called_once_with(config)

    def test_run_full_analysis_returns_false_when_local_report_save_fails(self):
        args = SimpleNamespace(
            portfolio=None,
            single_notify=False,
            no_context_snapshot=True,
            no_market_review=True,
            workers=1,
            dry_run=False,
            no_notify=True,
            schedule=False,
        )
        config = SimpleNamespace(
            refresh_stock_list=MagicMock(),
            single_stock_notify=False,
            merge_email_notification=False,
            market_review_enabled=False,
            market_review_region="cn",
            daily_market_context_enabled=False,
            analysis_delay=0,
            backtest_enabled=False,
        )
        pipeline = MagicMock()
        pipeline.run.return_value = [
            SimpleNamespace(
                code="600519",
                success=True,
                sentiment_score=90,
                name="贵州茅台",
                operation_advice="持有",
                trend_prediction="震荡上行",
                get_emoji=MagicMock(return_value="📈"),
            )
        ]
        pipeline._last_local_report_path = None
        pipeline._last_local_report_error = "permission denied"

        with patch.object(main, "_refresh_stock_index_cache_for_analysis"), patch.object(
            main,
            "_compute_trading_day_filter",
            return_value=(["600519"], "cn", False),
        ), patch(
            "src.core.pipeline.StockAnalysisPipeline",
            return_value=pipeline,
        ), patch(
            "src.core.market_review.run_market_review",
        ), patch(
            "src.feishu_doc.FeishuDocManager",
        ) as feishu_manager, patch.object(
            main,
            "_run_auto_backtest",
        ) as run_auto_backtest:
            feishu_manager.return_value.is_configured.return_value = False
            result = main.run_full_analysis(config, args, ["600519"])

        self.assertFalse(result)
        self.assertEqual(main._LAST_ANALYSIS_FAILURE_REASON, "report_save_failed")
        pipeline.run.assert_called_once()
        run_auto_backtest.assert_called_once_with(config)

    def test_run_full_analysis_still_exports_feishu_doc_when_local_report_save_fails(self):
        args = SimpleNamespace(
            portfolio=None,
            single_notify=False,
            no_context_snapshot=True,
            no_market_review=True,
            workers=1,
            dry_run=False,
            no_notify=True,
            schedule=False,
        )
        config = SimpleNamespace(
            refresh_stock_list=MagicMock(),
            single_stock_notify=False,
            merge_email_notification=False,
            market_review_enabled=False,
            market_review_region="cn",
            daily_market_context_enabled=False,
            analysis_delay=0,
            backtest_enabled=False,
            report_type="simple",
        )
        result_item = SimpleNamespace(
            code="600519",
            success=True,
            sentiment_score=90,
            name="贵州茅台",
            operation_advice="持有",
            trend_prediction="震荡上行",
            get_emoji=MagicMock(return_value="📈"),
        )
        pipeline = MagicMock()
        pipeline.run.return_value = [result_item]
        pipeline._last_local_report_path = None
        pipeline._last_local_report_error = "permission denied"
        pipeline.notifier = MagicMock(
            generate_aggregate_report=MagicMock(return_value="dashboard")
        )

        with patch.object(main, "_refresh_stock_index_cache_for_analysis"), patch.object(
            main,
            "_compute_trading_day_filter",
            return_value=(["600519"], "cn", False),
        ), patch(
            "src.core.pipeline.StockAnalysisPipeline",
            return_value=pipeline,
        ), patch(
            "src.core.market_review.run_market_review",
        ), patch(
            "src.feishu_doc.FeishuDocManager",
        ) as feishu_manager, patch.object(
            main,
            "_run_auto_backtest",
        ) as run_auto_backtest:
            feishu_instance = feishu_manager.return_value
            feishu_instance.is_configured.return_value = True
            feishu_instance.create_daily_doc.return_value = "https://feishu.example/doc"

            result = main.run_full_analysis(config, args, ["600519"])

        self.assertFalse(result)
        self.assertEqual(main._LAST_ANALYSIS_FAILURE_REASON, "report_save_failed")
        pipeline.run.assert_called_once()
        pipeline.notifier.generate_aggregate_report.assert_called_once_with(
            [result_item],
            "simple",
        )
        feishu_instance.create_daily_doc.assert_called_once()
        _, doc_content = feishu_instance.create_daily_doc.call_args.args
        self.assertIn("# 🚀 个股决策仪表盘\n\ndashboard", doc_content)
        run_auto_backtest.assert_called_once_with(config)

    def test_run_full_analysis_still_sends_merged_notification_before_report_save_failure(self):
        args = SimpleNamespace(
            portfolio=None,
            single_notify=False,
            no_context_snapshot=True,
            no_market_review=False,
            workers=1,
            dry_run=False,
            no_notify=False,
            schedule=False,
        )
        config = SimpleNamespace(
            refresh_stock_list=MagicMock(),
            single_stock_notify=False,
            merge_email_notification=True,
            market_review_enabled=True,
            market_review_region="cn",
            daily_market_context_enabled=False,
            analysis_delay=0,
            backtest_enabled=False,
            report_type="simple",
        )
        pipeline = MagicMock()
        pipeline.run.return_value = [
            SimpleNamespace(
                code="600519",
                success=True,
                sentiment_score=90,
                name="贵州茅台",
                operation_advice="持有",
                trend_prediction="震荡上行",
                get_emoji=MagicMock(return_value="📈"),
            )
        ]
        pipeline._last_local_report_path = None
        pipeline._last_local_report_error = "permission denied"
        pipeline.notifier = MagicMock(
            is_available=MagicMock(return_value=True),
            generate_aggregate_report=MagicMock(return_value="dashboard"),
            send=MagicMock(return_value=True),
        )

        with patch.object(main, "_refresh_stock_index_cache_for_analysis"), patch.object(
            main,
            "_compute_trading_day_filter",
            return_value=(["600519"], "cn", False),
        ), patch(
            "src.core.pipeline.StockAnalysisPipeline",
            return_value=pipeline,
        ), patch(
            "src.core.market_review.run_market_review",
        ), patch.object(
            main,
            "_run_market_review_with_shared_lock",
            return_value=SimpleNamespace(report="market review"),
        ), patch(
            "src.feishu_doc.FeishuDocManager",
        ) as feishu_manager, patch.object(
            main,
            "_run_auto_backtest",
        ) as run_auto_backtest:
            feishu_manager.return_value.is_configured.return_value = False
            result = main.run_full_analysis(config, args, ["600519"])

        self.assertFalse(result)
        self.assertEqual(main._LAST_ANALYSIS_FAILURE_REASON, "report_save_failed")
        pipeline.notifier.send.assert_called_once()
        combined_content = pipeline.notifier.send.call_args.args[0]
        self.assertIn("# 📈 大盘复盘\n\nmarket review", combined_content)
        self.assertIn("# 🚀 个股决策仪表盘\n\ndashboard", combined_content)
        run_auto_backtest.assert_called_once_with(config)

    def test_run_full_analysis_sends_doc_link_instead_of_long_text_when_doc_configured(self):
        """云文档凭据齐全时：只推一条文档链接，不再推长文本合并消息。"""
        args = SimpleNamespace(
            portfolio=None,
            single_notify=False,
            no_context_snapshot=True,
            no_market_review=False,
            workers=1,
            dry_run=False,
            no_notify=False,
            schedule=False,
        )
        config = SimpleNamespace(
            refresh_stock_list=MagicMock(),
            single_stock_notify=False,
            merge_email_notification=False,
            market_review_enabled=True,
            market_review_region="cn",
            daily_market_context_enabled=False,
            analysis_delay=0,
            backtest_enabled=False,
            report_type="simple",
            feishu_app_id="cli_test",
            feishu_app_secret="secret_test",
            feishu_folder_token="fld_test",
        )
        pipeline = MagicMock()
        pipeline.run.return_value = [
            SimpleNamespace(
                code="600519",
                success=True,
                sentiment_score=90,
                name="贵州茅台",
                operation_advice="持有",
                trend_prediction="震荡上行",
                get_emoji=MagicMock(return_value="📈"),
            )
        ]
        pipeline._last_local_report_path = "report_600519.md"
        pipeline._last_local_report_error = None
        pipeline.notifier = MagicMock(
            is_available=MagicMock(return_value=True),
            generate_aggregate_report=MagicMock(return_value="dashboard"),
            send=MagicMock(return_value=True),
        )

        with patch.object(main, "_refresh_stock_index_cache_for_analysis"), patch.object(
            main,
            "_compute_trading_day_filter",
            return_value=(["600519"], "cn", False),
        ), patch(
            "src.core.pipeline.StockAnalysisPipeline",
            return_value=pipeline,
        ), patch(
            "src.core.market_review.run_market_review",
        ), patch.object(
            main,
            "_run_market_review_with_shared_lock",
            return_value=SimpleNamespace(report="market review"),
        ), patch(
            "src.feishu_doc.FeishuDocManager",
        ) as feishu_manager, patch.object(
            main,
            "_run_auto_backtest",
        ):
            feishu_instance = feishu_manager.return_value
            feishu_instance.is_configured.return_value = True
            feishu_instance.create_daily_doc.return_value = "https://feishu.example/doc"
            main.run_full_analysis(config, args, ["600519"])

        # 有云文档 -> 强制合并（流水线/大盘各自静默）
        self.assertTrue(pipeline.run.call_args.kwargs["merge_notification"])
        # 文档已创建，内容含大盘 + 个股
        feishu_instance.create_daily_doc.assert_called_once()
        _, doc_content = feishu_instance.create_daily_doc.call_args.args
        self.assertIn("# 🚀 个股决策仪表盘\n\ndashboard", doc_content)
        self.assertIn("# 📈 大盘复盘\n\nmarket review", doc_content)
        # 只推一条链接，且不是长文本
        pipeline.notifier.send.assert_called_once()
        sent = pipeline.notifier.send.call_args.args[0]
        self.assertIn("复盘文档创建成功", sent)
        self.assertIn("https://feishu.example/doc", sent)
        self.assertNotIn("# 🚀 个股决策仪表盘", sent)

    def test_doc_link_send_failure_falls_back_to_merged_long_text(self):
        """云文档链接推送失败时必须回退长文本，否则群里一条消息都收不到。

        回归点：修复前链接发送失败只打一条 warning，长文本分支被跳过，
        文档已建好而群里没有任何消息，进程仍以成功退出。
        """
        args = SimpleNamespace(
            portfolio=None,
            single_notify=False,
            no_context_snapshot=True,
            no_market_review=False,
            workers=1,
            dry_run=False,
            no_notify=False,
            schedule=False,
        )
        config = self._build_doc_mode_config()
        results = [
            SimpleNamespace(
                code="600519",
                success=True,
                sentiment_score=90,
                name="贵州茅台",
                operation_advice="持有",
                trend_prediction="震荡上行",
                get_emoji=MagicMock(return_value="📈"),
            )
        ]
        pipeline = self._build_doc_mode_pipeline(results)
        # 第一次发送（文档链接）失败，第二次（回退的长文本）成功
        pipeline.notifier.send = MagicMock(side_effect=[False, True])

        with patch.object(main, "_refresh_stock_index_cache_for_analysis"), patch.object(
            main,
            "_compute_trading_day_filter",
            return_value=(["600519"], "cn", False),
        ), patch(
            "src.core.pipeline.StockAnalysisPipeline",
            return_value=pipeline,
        ), patch.object(
            main,
            "_run_market_review_with_shared_lock",
            return_value=SimpleNamespace(report="market review"),
        ), patch(
            "src.feishu_doc.FeishuDocManager",
        ) as feishu_manager, patch.object(
            main,
            "_run_auto_backtest",
        ):
            feishu_instance = feishu_manager.return_value
            feishu_instance.is_configured.return_value = True
            feishu_instance.create_daily_doc.return_value = "https://feishu.example/doc"
            main.run_full_analysis(config, args, ["600519"])

        self.assertEqual(pipeline.notifier.send.call_count, 2)
        first_sent = pipeline.notifier.send.call_args_list[0].args[0]
        second_sent = pipeline.notifier.send.call_args_list[1].args[0]
        self.assertIn("https://feishu.example/doc", first_sent)
        # 回退的第二条必须是完整长文本，而不是再发一次链接
        self.assertIn("# 🚀 个股决策仪表盘", second_sent)
        self.assertNotIn("https://feishu.example/doc", second_sent)

    def _build_doc_mode_config(self, **overrides):
        """构造「云文档凭据齐全」的 config，供下方三种模式测试复用。"""
        base = dict(
            refresh_stock_list=MagicMock(),
            single_stock_notify=False,
            merge_email_notification=False,
            market_review_enabled=True,
            market_review_region="cn",
            daily_market_context_enabled=False,
            analysis_delay=0,
            backtest_enabled=False,
            report_type="simple",
            feishu_app_id="cli_test",
            feishu_app_secret="secret_test",
            feishu_folder_token="fld_test",
        )
        base.update(overrides)
        return SimpleNamespace(**base)

    def _build_doc_mode_pipeline(self, results):
        pipeline = MagicMock()
        pipeline.run.return_value = results
        pipeline._last_local_report_path = "report_600519.md"
        pipeline._last_local_report_error = None
        pipeline.notifier = MagicMock(
            is_available=MagicMock(return_value=True),
            generate_aggregate_report=MagicMock(return_value="dashboard"),
            send=MagicMock(return_value=True),
        )
        return pipeline

    def test_doc_mode_merges_notification_even_with_no_market_review(self):
        """云文档模式 + --no-market-review（仅个股）：个股文字推送必须被静默。

        回归点：修复前 merge_notification 会被 no_market_review 置为 False，
        导致个股自己推一条文字消息到群里。
        """
        args = SimpleNamespace(
            portfolio=None,
            single_notify=False,
            no_context_snapshot=True,
            no_market_review=True,
            workers=1,
            dry_run=False,
            no_notify=False,
            schedule=False,
        )
        config = self._build_doc_mode_config()
        pipeline = self._build_doc_mode_pipeline(
            [
                SimpleNamespace(
                    code="600519",
                    success=True,
                    sentiment_score=90,
                    name="贵州茅台",
                    operation_advice="持有",
                    trend_prediction="震荡上行",
                    get_emoji=MagicMock(return_value="📈"),
                )
            ]
        )

        with patch.object(main, "_refresh_stock_index_cache_for_analysis"), patch.object(
            main, "_compute_trading_day_filter", return_value=(["600519"], "cn", False)
        ), patch("src.core.pipeline.StockAnalysisPipeline", return_value=pipeline), patch(
            "src.core.market_review.run_market_review"
        ), patch.object(
            main, "_run_auto_backtest"
        ), patch("src.feishu_doc.FeishuDocManager") as feishu_manager:
            feishu_instance = feishu_manager.return_value
            feishu_instance.is_configured.return_value = True
            feishu_instance.create_daily_doc.return_value = "https://feishu.example/doc"
            main.run_full_analysis(config, args, ["600519"])

        # 关键断言：即使 --no-market-review，也要合并（个股文字被静默）
        self.assertTrue(pipeline.run.call_args.kwargs["merge_notification"])
        # 只推一条链接
        pipeline.notifier.send.assert_called_once()
        sent = pipeline.notifier.send.call_args.args[0]
        self.assertIn("https://feishu.example/doc", sent)
        self.assertNotIn("# 🚀 个股决策仪表盘", sent)
        # 标题应体现"个股"，而不是硬编码的"大盘复盘"
        _, doc_title = feishu_instance.create_daily_doc.call_args.args
        self.assertIn("个股", doc_title)

    def test_doc_mode_merges_notification_even_with_single_stock_notify(self):
        """云文档模式 + single_stock_notify=True：同样必须静默个股文字推送。"""
        args = SimpleNamespace(
            portfolio=None,
            single_notify=False,
            no_context_snapshot=True,
            no_market_review=False,
            workers=1,
            dry_run=False,
            no_notify=False,
            schedule=False,
        )
        config = self._build_doc_mode_config(single_stock_notify=True)
        pipeline = self._build_doc_mode_pipeline(
            [
                SimpleNamespace(
                    code="600519",
                    success=True,
                    sentiment_score=90,
                    name="贵州茅台",
                    operation_advice="持有",
                    trend_prediction="震荡上行",
                    get_emoji=MagicMock(return_value="📈"),
                )
            ]
        )

        with patch.object(main, "_refresh_stock_index_cache_for_analysis"), patch.object(
            main, "_compute_trading_day_filter", return_value=(["600519"], "cn", False)
        ), patch("src.core.pipeline.StockAnalysisPipeline", return_value=pipeline), patch(
            "src.core.market_review.run_market_review"
        ), patch.object(
            main, "_run_market_review_with_shared_lock",
            return_value=SimpleNamespace(report="market review"),
        ), patch.object(
            main, "_run_auto_backtest"
        ), patch("src.feishu_doc.FeishuDocManager") as feishu_manager:
            feishu_instance = feishu_manager.return_value
            feishu_instance.is_configured.return_value = True
            feishu_instance.create_daily_doc.return_value = "https://feishu.example/doc"
            main.run_full_analysis(config, args, ["600519"])

        self.assertTrue(pipeline.run.call_args.kwargs["merge_notification"])
        pipeline.notifier.send.assert_called_once()
        sent = pipeline.notifier.send.call_args.args[0]
        self.assertIn("https://feishu.example/doc", sent)

    def test_doc_mode_merges_notification_even_when_market_review_disabled(self):
        """云文档模式 + market_review_enabled=False：仅个股场景同样只推链接。"""
        args = SimpleNamespace(
            portfolio=None,
            single_notify=False,
            no_context_snapshot=True,
            no_market_review=False,
            workers=1,
            dry_run=False,
            no_notify=False,
            schedule=False,
        )
        config = self._build_doc_mode_config(market_review_enabled=False)
        pipeline = self._build_doc_mode_pipeline(
            [
                SimpleNamespace(
                    code="600519",
                    success=True,
                    sentiment_score=90,
                    name="贵州茅台",
                    operation_advice="持有",
                    trend_prediction="震荡上行",
                    get_emoji=MagicMock(return_value="📈"),
                )
            ]
        )

        with patch.object(main, "_refresh_stock_index_cache_for_analysis"), patch.object(
            main, "_compute_trading_day_filter", return_value=(["600519"], "cn", False)
        ), patch("src.core.pipeline.StockAnalysisPipeline", return_value=pipeline), patch(
            "src.core.market_review.run_market_review"
        ), patch.object(
            main, "_run_auto_backtest"
        ), patch("src.feishu_doc.FeishuDocManager") as feishu_manager:
            feishu_instance = feishu_manager.return_value
            feishu_instance.is_configured.return_value = True
            feishu_instance.create_daily_doc.return_value = "https://feishu.example/doc"
            main.run_full_analysis(config, args, ["600519"])

        self.assertTrue(pipeline.run.call_args.kwargs["merge_notification"])
        pipeline.notifier.send.assert_called_once()
        sent = pipeline.notifier.send.call_args.args[0]
        self.assertIn("https://feishu.example/doc", sent)

    def test_run_full_analysis_returns_false_when_market_review_only_run_generates_no_report(self):
        args = SimpleNamespace(
            portfolio=None,
            single_notify=False,
            no_context_snapshot=True,
            no_market_review=False,
            workers=1,
            dry_run=False,
            no_notify=True,
            schedule=True,
        )
        config = SimpleNamespace(
            refresh_stock_list=MagicMock(),
            single_stock_notify=False,
            merge_email_notification=False,
            market_review_enabled=True,
            market_review_region="cn",
            daily_market_context_enabled=False,
            analysis_delay=0,
            backtest_enabled=False,
        )
        pipeline = MagicMock()
        pipeline.run.return_value = []

        with patch.object(main, "_refresh_stock_index_cache_for_analysis"), patch.object(
            main,
            "_compute_trading_day_filter",
            return_value=([], "cn", False),
        ), patch(
            "src.core.pipeline.StockAnalysisPipeline",
            return_value=pipeline,
        ), patch(
            "src.core.market_review.run_market_review",
        ), patch.object(
            main,
            "_run_market_review_with_shared_lock",
            return_value=None,
        ) as run_with_lock, patch(
            "src.feishu_doc.FeishuDocManager",
        ) as feishu_manager, patch.object(
            main,
            "_run_auto_backtest",
        ) as run_auto_backtest:
            feishu_manager.return_value.is_configured.return_value = False
            result = main.run_full_analysis(config, args, [])

        self.assertFalse(result)
        self.assertEqual(main._LAST_ANALYSIS_FAILURE_REASON, "no_report")
        pipeline.run.assert_called_once()
        run_with_lock.assert_called_once()
        run_auto_backtest.assert_called_once_with(config)

    def test_run_full_analysis_uses_futu_holdings_and_reloads_each_run(self):
        args = SimpleNamespace(
            portfolio="futu",
            single_notify=False,
            no_context_snapshot=True,
            no_market_review=True,
            workers=1,
            dry_run=True,
            no_notify=True,
            schedule=False,
        )
        config = SimpleNamespace(
            refresh_stock_list=MagicMock(),
            single_stock_notify=False,
            merge_email_notification=False,
            market_review_enabled=False,
            market_review_region="cn",
            daily_market_context_enabled=False,
            analysis_delay=0,
            backtest_enabled=False,
        )
        pipeline = MagicMock()
        pipeline.run.return_value = []
        trading_day_filter = MagicMock(
            return_value=(["AAPL", "HK00700"], "us,hk", False)
        )

        with patch.object(main, "_refresh_stock_index_cache_for_analysis"), patch.object(
            main,
            "_compute_trading_day_filter",
            trading_day_filter,
        ), patch(
            "src.brokers.futu.portfolio.load_futu_stock_codes",
            return_value=["AAPL", "HK00700"],
        ) as loader, patch(
            "src.core.pipeline.StockAnalysisPipeline",
            return_value=pipeline,
        ), patch(
            "src.core.market_review.run_market_review",
        ), patch(
            "src.feishu_doc.FeishuDocManager",
        ) as feishu_manager:
            feishu_manager.return_value.is_configured.return_value = False
            cli_target = MagicMock()
            first_result = main.run_full_analysis(
                config, args, ["600519"], analysis_targets=[cli_target]
            )
            second_result = main.run_full_analysis(
                config, args, ["600519"], analysis_targets=[cli_target]
            )

        self.assertTrue(first_result)
        self.assertTrue(second_result)
        self.assertEqual(loader.call_count, 2)
        config.refresh_stock_list.assert_not_called()
        self.assertEqual(trading_day_filter.call_count, 2)
        trading_day_filter.assert_has_calls(
            [
                call(config, args, ["AAPL", "HK00700"]),
                call(config, args, ["AAPL", "HK00700"]),
            ]
        )
        self.assertEqual(pipeline.run.call_count, 2)
        for invocation in pipeline.run.call_args_list:
            self.assertEqual(invocation.kwargs["stock_codes"], ["AAPL", "HK00700"])
            self.assertIsNone(invocation.kwargs["analysis_targets"])

    def test_run_full_analysis_skips_empty_futu_portfolio_without_fallback(self):
        args = SimpleNamespace(
            portfolio="futu",
            force_run=True,
            single_notify=False,
            no_context_snapshot=True,
            no_market_review=True,
            workers=1,
            dry_run=True,
            no_notify=True,
            schedule=False,
        )
        config = SimpleNamespace(
            refresh_stock_list=MagicMock(),
            single_stock_notify=False,
            merge_email_notification=False,
            market_review_enabled=True,
            market_review_region="cn",
            daily_market_context_enabled=False,
            analysis_delay=0,
            backtest_enabled=False,
        )
        real_import = builtins.__import__

        def reject_pipeline_import(name, *args, **kwargs):
            if name in {"src.core.market_review", "src.core.pipeline"}:
                raise AssertionError(f"empty portfolio must not import {name}")
            return real_import(name, *args, **kwargs)

        with patch.object(
            main,
            "_refresh_stock_index_cache_for_analysis",
        ) as refresh_stock_index, patch.object(
            main,
            "_compute_trading_day_filter",
            return_value=([], None, False),
        ) as trading_day_filter, patch(
            "src.brokers.futu.portfolio.load_futu_stock_codes",
            return_value=[],
        ), patch.object(
            builtins,
            "__import__",
            side_effect=reject_pipeline_import,
        ), self.assertLogs(main.logger, level="INFO") as captured:
            result = main.run_full_analysis(config, args, ["600519"])

        self.assertTrue(result)
        config.refresh_stock_list.assert_not_called()
        refresh_stock_index.assert_not_called()
        trading_day_filter.assert_not_called()
        log_text = "\n".join(captured.output)
        self.assertIn("无符合条件的 Futu 持仓", log_text)
        self.assertNotIn("未配置自选股列表", log_text)

    def test_empty_futu_portfolio_is_noop_when_trading_day_check_is_disabled(self):
        args = SimpleNamespace(
            portfolio="futu",
            force_run=False,
            no_market_review=False,
        )
        config = SimpleNamespace(
            refresh_stock_list=MagicMock(),
            market_review_enabled=False,
            trading_day_check_enabled=False,
        )

        with patch.object(
            main,
            "_refresh_stock_index_cache_for_analysis",
        ) as refresh_stock_index, patch.object(
            main,
            "_compute_trading_day_filter",
        ) as trading_day_filter, patch(
            "src.brokers.futu.portfolio.load_futu_stock_codes",
            return_value=[],
        ), self.assertLogs(main.logger, level="INFO") as captured:
            result = main.run_full_analysis(config, args, ["600519"])

        self.assertTrue(result)
        config.refresh_stock_list.assert_not_called()
        refresh_stock_index.assert_not_called()
        trading_day_filter.assert_not_called()
        self.assertIn("无符合条件的 Futu 持仓", "\n".join(captured.output))

    def test_empty_futu_portfolio_preserves_enabled_auto_backtest(self):
        args = SimpleNamespace(
            portfolio="futu",
            no_market_review=True,
        )
        config = SimpleNamespace(
            market_review_enabled=True,
            backtest_enabled=True,
            backtest_eval_window_days=10,
            backtest_min_age_days=14,
        )
        backtest_service = MagicMock()
        backtest_service.run_backtest.return_value = {
            "processed": 1,
            "saved": 1,
            "completed": 1,
            "insufficient": 0,
            "errors": 0,
        }
        real_import = builtins.__import__

        def reject_pipeline_import(name, *args, **kwargs):
            if name in {"src.core.market_review", "src.core.pipeline"}:
                raise AssertionError(f"empty portfolio must not import {name}")
            return real_import(name, *args, **kwargs)

        with patch(
            "src.brokers.futu.portfolio.load_futu_stock_codes",
            return_value=[],
        ), patch(
            "src.services.backtest_service.BacktestService",
            return_value=backtest_service,
        ) as backtest_class, patch.object(
            builtins,
            "__import__",
            side_effect=reject_pipeline_import,
        ):
            result = main.run_full_analysis(config, args)

        self.assertTrue(result)
        backtest_class.assert_called_once_with()
        backtest_service.run_backtest.assert_called_once_with(
            force=False,
            eval_window_days=10,
            min_age_days=14,
            limit=200,
        )

    def test_empty_futu_portfolio_uses_an_accurate_skip_reason(self):
        args = SimpleNamespace(portfolio="futu")
        config = SimpleNamespace(refresh_stock_list=MagicMock())

        with patch.object(main, "_refresh_stock_index_cache_for_analysis"), patch.object(
            main,
            "_compute_trading_day_filter",
            return_value=([], "", True),
        ), patch(
            "src.brokers.futu.portfolio.load_futu_stock_codes",
            return_value=[],
        ), patch(
            "src.core.pipeline.StockAnalysisPipeline",
        ) as pipeline_class, patch(
            "src.core.market_review.run_market_review",
        ), self.assertLogs(main.logger, level="INFO") as captured:
            result = main.run_full_analysis(config, args)

        self.assertTrue(result)
        pipeline_class.assert_not_called()
        log_text = "\n".join(captured.output)
        self.assertIn("无符合条件的 Futu 持仓", log_text)
        self.assertNotIn("所有相关市场均为非交易日", log_text)

    def test_futu_portfolio_without_effective_codes_still_runs_market_review(self):
        args = SimpleNamespace(
            portfolio="futu",
            single_notify=False,
            no_context_snapshot=True,
            no_market_review=False,
            workers=1,
            dry_run=True,
            no_notify=True,
            schedule=False,
        )
        config = SimpleNamespace(
            refresh_stock_list=MagicMock(),
            single_stock_notify=False,
            merge_email_notification=False,
            market_review_enabled=True,
            market_review_region="cn",
            daily_market_context_enabled=False,
            analysis_delay=0,
            backtest_enabled=False,
        )
        for holdings in ([], ["AAPL"]):
            with self.subTest(holdings=holdings):
                pipeline = MagicMock()
                run_market_review = MagicMock()

                with patch.object(
                    main,
                    "_refresh_stock_index_cache_for_analysis",
                ), patch.object(
                    main,
                    "_compute_trading_day_filter",
                    return_value=([], "cn", False),
                ), patch(
                    "src.brokers.futu.portfolio.load_futu_stock_codes",
                    return_value=holdings,
                ), patch(
                    "src.core.pipeline.StockAnalysisPipeline",
                    return_value=pipeline,
                ), patch(
                    "src.core.market_review.run_market_review",
                    run_market_review,
                ), patch.object(
                    main,
                    "_run_market_review_with_shared_lock",
                    return_value=SimpleNamespace(report="market review"),
                ) as run_with_lock, patch(
                    "src.feishu_doc.FeishuDocManager",
                ) as feishu_manager:
                    feishu_manager.return_value.is_configured.return_value = False
                    result = main.run_full_analysis(config, args)

                self.assertTrue(result)
                pipeline.run.assert_not_called()
                run_with_lock.assert_called_once()

    def test_runtime_scheduler_preserves_futu_portfolio_override(self):
        scheduler = RuntimeSchedulerService(
            owns_schedule=False,
            schedule_args_overrides={"portfolio": "futu"},
        )

        self.assertEqual(scheduler._make_schedule_args().portfolio, "futu")

    def test_runtime_scheduler_records_futu_load_failure_and_keeps_running(self):
        config = SimpleNamespace(
            schedule_enabled=True,
            schedule_time="18:00",
            schedule_times=["18:00"],
        )
        error = FutuPortfolioError("OpenD unavailable")

        def runner(config_arg, args, stock_codes):
            raise error

        scheduler = RuntimeSchedulerService(
            config_provider=lambda: config,
            task_runner=runner,
        )
        scheduler._reload_config = lambda: config

        self.assertTrue(scheduler._run_analysis_once())
        status = scheduler.status()
        self.assertIsNone(status["last_success_at"])
        self.assertEqual(status["last_error"], "OpenD unavailable")


if __name__ == "__main__":
    unittest.main()
