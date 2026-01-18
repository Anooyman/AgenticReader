"""
IndexingAgent 辅助方法

内部辅助工具，不对外暴露
"""

from typing import List, Optional, TYPE_CHECKING
import logging
from pathlib import Path

if TYPE_CHECKING:
    from .agent import IndexingAgent

logger = logging.getLogger(__name__)


class IndexingUtils:
    """IndexingAgent 辅助工具集合"""

    def __init__(self, agent: 'IndexingAgent'):
        """
        Args:
            agent: IndexingAgent实例（依赖注入）
        """
        self.agent = agent

    def check_stage_files_exist(self, stage_name: str, output_files: List[str]) -> bool:
        """
        检查阶段输出文件是否存在

        Args:
            stage_name: 阶段名称
            output_files: 输出文件路径列表

        Returns:
            所有文件都存在返回True，否则返回False
        """
        if not output_files:
            return False

        for file_path in output_files:
            path = Path(file_path)
            # 检查文件或目录是否存在
            if not path.exists():
                logger.info(f"⏭️  [{stage_name}] 文件不存在，需要执行: {file_path}")
                return False

            # 如果是目录，检查是否为空
            if path.is_dir():
                if not any(path.iterdir()):
                    logger.info(f"⏭️  [{stage_name}] 目录为空，需要执行: {file_path}")
                    return False

        logger.info(f"✅ [{stage_name}] 所有输出文件已存在")
        return True

    def should_skip_stage(self, doc_name: str, stage_name: str) -> tuple[bool, Optional[List[str]]]:
        """
        判断是否应该跳过某个阶段

        Args:
            doc_name: 文档名称
            stage_name: 阶段名称

        Returns:
            (should_skip, output_files): 是否跳过 和 输出文件列表
        """
        # 检查注册表中的阶段状态
        stage_info = self.agent.doc_registry.get_stage_status(doc_name, stage_name)

        if not stage_info or stage_info.get("status") != "completed":
            logger.info(f"🔄 [{stage_name}] 阶段未完成，需要执行")
            return False, None

        # 检查输出文件是否存在
        output_files = stage_info.get("output_files", [])
        if self.check_stage_files_exist(stage_name, output_files):
            logger.info(f"⏭️  [{stage_name}] 阶段已完成且文件存在，跳过执行")
            return True, output_files
        else:
            logger.info(f"🔄 [{stage_name}] 阶段状态为完成但文件不存在，重新执行")
            return False, None
