"""
单元测试框架

为LLMReader项目提供统一的测试基础设施和测试工具
"""
import unittest
import tempfile
import shutil
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Callable
import logging
from unittest.mock import Mock, patch, MagicMock

# 添加项目根目录到系统路径
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from src.utils.exceptions import LLMReaderBaseException
from src.utils.error_handler import ErrorHandler
from src.utils.file_operations import SafeFileOperations, AdvancedFileOperations
from src.utils.validators import validate_file_path, validate_json_data
from src.utils.config_validator import validate_complete_config

# 配置测试日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


class LLMReaderTestCase(unittest.TestCase):
    """LLMReader项目测试基类"""

    def setUp(self):
        """测试前的设置"""
        self.temp_dir = tempfile.mkdtemp()
        self.test_files = []
        logger.info(f"创建临时测试目录: {self.temp_dir}")

    def tearDown(self):
        """测试后的清理"""
        try:
            shutil.rmtree(self.temp_dir)
            logger.info(f"清理临时测试目录: {self.temp_dir}")
        except Exception as e:
            logger.warning(f"清理临时目录失败: {e}")

    def create_test_file(self, filename: str, content: str = "test content", encoding: str = 'utf-8') -> str:
        """
        创建测试文件

        Args:
            filename: 文件名
            content: 文件内容
            encoding: 编码格式

        Returns:
            文件完整路径
        """
        file_path = os.path.join(self.temp_dir, filename)
        with open(file_path, 'w', encoding=encoding) as f:
            f.write(content)
        self.test_files.append(file_path)
        return file_path

    def create_test_json_file(self, filename: str, data: Dict[str, Any]) -> str:
        """
        创建测试JSON文件

        Args:
            filename: 文件名
            data: JSON数据

        Returns:
            文件完整路径
        """
        file_path = os.path.join(self.temp_dir, filename)
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        self.test_files.append(file_path)
        return file_path

    def assert_file_exists(self, file_path: str, msg: str = None):
        """断言文件存在"""
        self.assertTrue(os.path.exists(file_path), msg or f"文件不存在: {file_path}")

    def assert_file_not_exists(self, file_path: str, msg: str = None):
        """断言文件不存在"""
        self.assertFalse(os.path.exists(file_path), msg or f"文件应该不存在: {file_path}")

    def assert_file_contains(self, file_path: str, expected_content: str, msg: str = None):
        """断言文件包含指定内容"""
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
        self.assertIn(expected_content, content, msg or f"文件不包含期望内容: {expected_content}")


class TestSafeFileOperations(LLMReaderTestCase):
    """SafeFileOperations类的测试"""

    def test_read_text_file(self):
        """测试读取文本文件"""
        test_content = "这是一个测试文件\n包含中文内容"
        test_file = self.create_test_file("test.txt", test_content)

        # 测试正常读取
        result = SafeFileOperations.read_text_file(test_file)
        self.assertEqual(result, test_content)

    def test_read_nonexistent_file(self):
        """测试读取不存在的文件"""
        nonexistent_file = os.path.join(self.temp_dir, "nonexistent.txt")

        with self.assertRaises(Exception):
            SafeFileOperations.read_text_file(nonexistent_file)

    def test_write_text_file(self):
        """测试写入文本文件"""
        test_content = "写入测试内容\n中文测试"
        test_file = os.path.join(self.temp_dir, "write_test.txt")

        # 测试写入
        SafeFileOperations.write_text_file(test_file, test_content)

        # 验证文件存在并且内容正确
        self.assert_file_exists(test_file)
        with open(test_file, 'r', encoding='utf-8') as f:
            content = f.read()
        self.assertEqual(content, test_content)

    def test_read_json_file(self):
        """测试读取JSON文件"""
        test_data = {"name": "测试", "value": 123, "list": [1, 2, 3]}
        test_file = self.create_test_json_file("test.json", test_data)

        result = SafeFileOperations.read_json_file(test_file)
        self.assertEqual(result, test_data)

    def test_write_json_file(self):
        """测试写入JSON文件"""
        test_data = {"测试": "数据", "数字": 456}
        test_file = os.path.join(self.temp_dir, "write_test.json")

        SafeFileOperations.write_json_file(test_file, test_data)

        # 验证文件存在并且内容正确
        self.assert_file_exists(test_file)
        with open(test_file, 'r', encoding='utf-8') as f:
            loaded_data = json.load(f)
        self.assertEqual(loaded_data, test_data)

    def test_copy_file(self):
        """测试复制文件"""
        test_content = "复制测试内容"
        source_file = self.create_test_file("source.txt", test_content)
        dest_file = os.path.join(self.temp_dir, "dest.txt")

        SafeFileOperations.copy_file(source_file, dest_file)

        # 验证目标文件存在并且内容正确
        self.assert_file_exists(dest_file)
        with open(dest_file, 'r', encoding='utf-8') as f:
            content = f.read()
        self.assertEqual(content, test_content)

    def test_delete_file(self):
        """测试删除文件"""
        test_file = self.create_test_file("delete_test.txt")

        # 确认文件存在
        self.assert_file_exists(test_file)

        # 删除文件
        result = SafeFileOperations.delete_file(test_file)
        self.assertTrue(result)

        # 确认文件已删除
        self.assert_file_not_exists(test_file)

    def test_ensure_directory(self):
        """测试确保目录存在"""
        test_dir = os.path.join(self.temp_dir, "subdir", "nested")

        SafeFileOperations.ensure_directory(test_dir)

        # 验证目录创建成功
        self.assertTrue(os.path.isdir(test_dir))


class TestAdvancedFileOperations(LLMReaderTestCase):
    """AdvancedFileOperations类的测试"""

    def test_read_file_in_chunks(self):
        """测试分块读取文件"""
        test_content = "A" * 1000  # 创建1000字符的内容
        test_file = self.create_test_file("chunk_test.txt", test_content)

        chunks = AdvancedFileOperations.read_file_in_chunks(test_file, chunk_size=100)

        # 验证分块结果
        self.assertEqual(len(chunks), 10)  # 应该分成10块
        reconstructed = ''.join(chunks)
        self.assertEqual(reconstructed, test_content)

    def test_atomic_write(self):
        """测试原子性写入"""
        test_file = os.path.join(self.temp_dir, "atomic_test.txt")
        test_content = "原子性写入测试"

        with AdvancedFileOperations.atomic_write(test_file) as f:
            f.write(test_content)

        # 验证文件写入成功
        self.assert_file_exists(test_file)
        with open(test_file, 'r', encoding='utf-8') as f:
            content = f.read()
        self.assertEqual(content, test_content)

    def test_create_backup(self):
        """测试创建备份"""
        test_content = "备份测试内容"
        test_file = self.create_test_file("backup_test.txt", test_content)

        # 创建备份
        backup_path = AdvancedFileOperations.create_backup(test_file)

        # 验证备份文件创建成功
        self.assert_file_exists(backup_path)
        with open(backup_path, 'r', encoding='utf-8') as f:
            backup_content = f.read()
        self.assertEqual(backup_content, test_content)


class TestValidators(LLMReaderTestCase):
    """验证器测试"""

    def test_validate_file_path_existing_file(self):
        """测试验证存在的文件路径"""
        test_file = self.create_test_file("valid_file.txt")

        # 验证存在的文件
        result = validate_file_path(test_file, check_exists=True)
        self.assertIsInstance(result, str)

    def test_validate_file_path_nonexistent_file(self):
        """测试验证不存在的文件路径"""
        nonexistent_file = os.path.join(self.temp_dir, "nonexistent.txt")

        # 不检查存在性时应该通过
        result = validate_file_path(nonexistent_file, check_exists=False)
        self.assertIsInstance(result, str)

    def test_validate_json_data(self):
        """测试JSON数据验证"""
        valid_json = '{"key": "value", "number": 123}'
        result = validate_json_data(valid_json)
        expected = {"key": "value", "number": 123}
        self.assertEqual(result, expected)

    def test_validate_invalid_json_data(self):
        """测试无效JSON数据验证"""
        invalid_json = '{"key": "value", "invalid": }'

        with self.assertRaises(Exception):
            validate_json_data(invalid_json)


class TestErrorHandler(LLMReaderTestCase):
    """错误处理器测试"""

    def test_error_handler_basic(self):
        """测试基本错误处理"""
        handler = ErrorHandler()

        test_error = ValueError("测试错误")
        result = handler.handle_error(test_error, "测试上下文", reraise=False, fallback_value="fallback")

        self.assertEqual(result, "fallback")
        stats = handler.get_error_statistics()
        self.assertIn("ValueError:测试上下文", stats)

    def test_error_handler_reraise(self):
        """测试重新抛出异常"""
        handler = ErrorHandler()

        test_error = ValueError("测试错误")

        with self.assertRaises(ValueError):
            handler.handle_error(test_error, "测试上下文", reraise=True)


class TestRunner:
    """测试运行器"""

    def __init__(self):
        self.test_suite = unittest.TestSuite()
        self.test_results = []

    def add_test_class(self, test_class):
        """添加测试类"""
        tests = unittest.TestLoader().loadTestsFromTestCase(test_class)
        self.test_suite.addTests(tests)

    def run_all_tests(self) -> Dict[str, Any]:
        """运行所有测试"""
        logger.info("开始运行单元测试...")

        # 创建测试运行器
        runner = unittest.TextTestRunner(verbosity=2, stream=sys.stdout)
        result = runner.run(self.test_suite)

        # 整理测试结果
        test_results = {
            "tests_run": result.testsRun,
            "failures": len(result.failures),
            "errors": len(result.errors),
            "skipped": len(result.skipped) if hasattr(result, 'skipped') else 0,
            "success_rate": ((result.testsRun - len(result.failures) - len(result.errors)) / result.testsRun * 100) if result.testsRun > 0 else 0,
            "failure_details": [str(failure) for failure in result.failures],
            "error_details": [str(error) for error in result.errors]
        }

        logger.info(f"测试完成 - 运行: {test_results['tests_run']}, "
                   f"失败: {test_results['failures']}, "
                   f"错误: {test_results['errors']}, "
                   f"成功率: {test_results['success_rate']:.1f}%")

        return test_results


def run_comprehensive_tests() -> Dict[str, Any]:
    """运行完整的测试套件"""
    runner = TestRunner()

    # 添加所有测试类
    runner.add_test_class(TestSafeFileOperations)
    runner.add_test_class(TestAdvancedFileOperations)
    runner.add_test_class(TestValidators)
    runner.add_test_class(TestErrorHandler)

    # 运行测试
    return runner.run_all_tests()


if __name__ == "__main__":
    # 运行测试时的主入口
    print("LLMReader 单元测试框架")
    print("=" * 50)

    try:
        results = run_comprehensive_tests()
        print("\n测试结果摘要:")
        print(f"总测试数: {results['tests_run']}")
        print(f"成功: {results['tests_run'] - results['failures'] - results['errors']}")
        print(f"失败: {results['failures']}")
        print(f"错误: {results['errors']}")
        print(f"成功率: {results['success_rate']:.1f}%")

        if results['failures'] > 0 or results['errors'] > 0:
            print("\n详细错误信息:")
            for failure in results['failure_details']:
                print(f"失败: {failure}")
            for error in results['error_details']:
                print(f"错误: {error}")

    except Exception as e:
        logger.error(f"运行测试时出错: {e}")
        sys.exit(1)