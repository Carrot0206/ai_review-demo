"""命令行入口：用真 DeepSeek 跑通审核流程。

用法：
  python -m backend.cli.run_review \
      --process pre_report \
      --materials backend/samples/事前报告模板.json backend/samples/事前报告申请书.pdf \
      --output backend/out/pre_report_result.json \
      --max-concurrency 4
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

# 允许在项目根目录直接 `python backend/cli/run_review.py`
ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.services.review_service import review  # noqa: E402


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="信托登记 AI 审核 — 命令行 runner（仅 DeepSeek，禁止 mock）"
    )
    p.add_argument(
        "--process",
        choices=[
            "pre_report",
            "initial",
            "pre_registration",
            "pre_registration_reapply",
            "termination",
        ],
        required=True,
        help="登记流程：pre_report=事前报告 / initial=初始登记 / pre_registration=预登记 / pre_registration_reapply=重新申请预登记 / termination=终止登记",
    )
    p.add_argument(
        "--materials",
        nargs="+",
        required=True,
        help="一个或多个材料文件路径（支持 .json / .pdf / .docx / .txt）",
    )
    p.add_argument(
        "--output",
        default="backend/out/review_result.json",
        help="结果 JSON 输出路径",
    )
    p.add_argument(
        "--max-concurrency",
        type=int,
        default=16,
        help="并发批次数上限（默认 16）",
    )
    p.add_argument(
        "--rules",
        nargs="*",
        default=None,
        help="可选：仅审核给定 rule_id 列表（用于小范围调试）",
    )
    return p


async def _amain(args: argparse.Namespace) -> int:
    async def log(msg: str) -> None:
        print(f"  · {msg}", flush=True)

    print(f"== 信托登记 AI 审核 ==")
    print(f"流程: {args.process}")
    print(f"材料: {args.materials}")
    print(f"并发: {args.max_concurrency}")
    print()

    whitelist = set(args.rules) if args.rules else None

    result = await review(
        process=args.process,
        material_paths=args.materials,
        max_concurrency=args.max_concurrency,
        progress_cb=log,
        rule_id_whitelist=whitelist,
    )

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(result.model_dump(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    s = result.summary
    print()
    print(f"== 审核完成 ==")
    print(f"流程: {s.registration_type}")
    print(f"总问题: {s.total_issues}（高 {s.high_risk_count} / 中 {s.medium_risk_count} / 低 {s.low_risk_count}）")
    print(f"需人工复核规则: {len(result.human_review_items)} 条")
    print(f"批次日志: {len(result.batch_logs)} 批")
    success = sum(1 for b in result.batch_logs if b.status == "success")
    failed = sum(1 for b in result.batch_logs if b.status == "failed")
    print(f"  成功 {success} / 失败 {failed}")
    total_in = sum(b.input_tokens for b in result.batch_logs)
    total_out = sum(b.output_tokens for b in result.batch_logs)
    print(f"  tokens in/out 合计：{total_in} / {total_out}")
    print(f"结果已写入：{out_path}")

    return 0 if failed == 0 else 2


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()
    try:
        code = asyncio.run(_amain(args))
    except KeyboardInterrupt:
        print("\n[中断]")
        sys.exit(130)
    sys.exit(code)


if __name__ == "__main__":
    main()
