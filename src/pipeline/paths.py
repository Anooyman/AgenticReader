"""pipeline/ 批处理管线的路径常量。

改自 ai-research-pipeline 的 pipeline/paths.py。合并进 AgenticReader 后不再
需要 AGENTICREADER_ROOT/LLM_MEMORY_ROOT 这类跨仓库路径——pipeline 脚本现在
和 src/agents/、src/memory/ 在同一个项目根、同一套 sys.path 下运行，直接
`from src.agents.indexing import IndexingAgent` 之类的绝对 import 即可。

STATE_DIR/SUMMARIES_DIR/OUTPUT_DIR 沿用 data/ 下的子目录（与 AgenticReader
其余数据目录同级），不再是独立仓库自己的 state/、output/。
"""
import json
import os
from pathlib import Path

from src.config.settings import DATA_ROOT

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent  # src/pipeline/ 的上两级是项目根
STATE_DIR = PROJECT_ROOT / DATA_ROOT / "pipeline"
SUMMARIES_DIR = STATE_DIR / "summaries"
OUTPUT_DIR = PROJECT_ROOT / DATA_ROOT / "output" / "pipeline"

# 每日研究简报的本地目录（沿用 ai-research-pipeline 原有的环境变量名，
# 方便熟悉旧项目的人直接迁移习惯）。
BRIEFS_DIR = Path(os.environ.get("BRIEFS_DIR", str(Path.home() / "Desktop" / "AATF-Intelligence-Briefs")))


def write_json_atomic(path: Path, data) -> None:
    """先写 .tmp 再原子替换——进程在写入途中被杀时，原文件保持完好，
    不会留下半截 JSON。queue/summary 的落盘统一用这一个实现。

    注意它只防"写到一半崩溃"，不防"两个进程同时改"——后者要靠
    queue_transaction 的锁，两者互补。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    tmp_path.replace(path)
