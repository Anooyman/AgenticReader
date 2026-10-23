"""pipeline/ 批处理管线的路径常量。

改自 ai-research-pipeline 的 pipeline/paths.py。合并进 AgenticReader 后不再
需要 AGENTICREADER_ROOT/LLM_MEMORY_ROOT 这类跨仓库路径——pipeline 脚本现在
和 src/agents/、src/memory/ 在同一个项目根、同一套 sys.path 下运行，直接
`from src.agents.indexing import IndexingAgent` 之类的绝对 import 即可。

STATE_DIR/SUMMARIES_DIR/OUTPUT_DIR 沿用 data/ 下的子目录（与 AgenticReader
其余数据目录同级），不再是独立仓库自己的 state/、output/。
"""
import os
from pathlib import Path

# re-export：实现已下沉到 src/utils/json_io.py（与 path_guard 同层），以消除
# core/document_management → pipeline 的模块级反向依赖；既有调用方
# （registry/queue_store/job_runner/chat_ingest/process_*/generate_qa_brief/
# sync_memory_ingest）继续 `from src.pipeline.paths import write_json_atomic`
# 零改动。
from src.utils.json_io import write_json_atomic  # noqa: F401

from src.config.settings import DATA_ROOT

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent  # src/pipeline/ 的上两级是项目根
STATE_DIR = PROJECT_ROOT / DATA_ROOT / "pipeline"
SUMMARIES_DIR = STATE_DIR / "summaries"
OUTPUT_DIR = PROJECT_ROOT / DATA_ROOT / "output" / "pipeline"

# 每日研究简报的本地目录（沿用 ai-research-pipeline 原有的环境变量名，
# 方便熟悉旧项目的人直接迁移习惯）。
BRIEFS_DIR = Path(os.environ.get("BRIEFS_DIR", str(Path.home() / "Desktop" / "AATF-Intelligence-Briefs")))
