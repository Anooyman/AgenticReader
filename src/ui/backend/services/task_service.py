"""后台任务管理服务"""

from typing import Dict, Any, Optional
from datetime import datetime
import json
from pathlib import Path
import uuid

from src.utils.json_io import write_json_atomic


class TaskManager:
    """后台任务管理器"""

    def __init__(self):
        self.tasks: Dict[str, Dict[str, Any]] = {}
        self.tasks_file = Path("data/tasks.json")
        self._load_tasks()

    def _load_tasks(self):
        """从文件加载任务历史"""
        try:
            if self.tasks_file.exists():
                with open(self.tasks_file, 'r', encoding='utf-8') as f:
                    loaded_tasks = json.load(f)
                    # 只加载最近的任务（最多100个）
                    if isinstance(loaded_tasks, dict):
                        recent_tasks = dict(list(loaded_tasks.items())[-100:])
                        self.tasks = recent_tasks
        except Exception as e:
            print(f"加载任务历史失败: {e}")
            self.tasks = {}

    def _save_tasks(self):
        """保存任务到文件（原子落盘，tmp + os.replace）"""
        try:
            write_json_atomic(self.tasks_file, self.tasks)
        except Exception as e:
            print(f"保存任务历史失败: {e}")

    def recover_interrupted(self) -> int:
        """进程重启后把残留的 running 任务标记为 interrupted。

        后台索引/重建任务是 asyncio 协程，进程死了它们就永远不会再被更新；
        留在 running 会让前端任务面板一直转圈。启动时调一次。返回修复条数。"""
        fixed = 0
        for task in self.tasks.values():
            if task.get("status") == "running":
                task["status"] = "interrupted"
                task["updated_at"] = datetime.now().isoformat()
                fixed += 1
        if fixed:
            self._save_tasks()
            print(f"♻️ 启动恢复：{fixed} 个残留 running 任务已标记为 interrupted")
        return fixed

    def create_task(self, task_type: str, filename: str, **extra) -> str:
        """
        创建新任务

        Args:
            task_type: 任务类型（如 "pdf_index"）
            filename: 文件名
            **extra: 额外参数

        Returns:
            任务ID
        """
        task_id = str(uuid.uuid4())
        task = {
            "task_id": task_id,
            "task_type": task_type,
            "filename": filename,
            "status": "running",
            "progress": 0,
            "created_at": datetime.now().isoformat(),
            "updated_at": datetime.now().isoformat(),
            "error": None,
            **extra
        }
        self.tasks[task_id] = task
        self._save_tasks()
        print(f"📋 创建任务: {task_id} - {filename}")
        return task_id

    def update_task(self, task_id: str, **kwargs):
        """更新任务状态"""
        if task_id in self.tasks:
            self.tasks[task_id].update(kwargs)
            self.tasks[task_id]["updated_at"] = datetime.now().isoformat()
            self._save_tasks()

    def get_task(self, task_id: str) -> Optional[Dict[str, Any]]:
        """获取任务状态"""
        return self.tasks.get(task_id)

    def complete_task(self, task_id: str, success: bool = True, error: str = None):
        """标记任务完成"""
        if task_id in self.tasks:
            self.tasks[task_id].update({
                "status": "completed" if success else "failed",
                "progress": 100 if success else self.tasks[task_id].get("progress", 0),
                "updated_at": datetime.now().isoformat(),
                "error": error
            })
            self._save_tasks()

            status_icon = "✅" if success else "❌"
            filename = self.tasks[task_id].get("filename", "unknown")
            print(f"{status_icon} 任务完成: {task_id} - {filename}")


# 全局单例
task_manager = TaskManager()
