"""
工具测试
"""
import pytest
import asyncio
import os
import tempfile
import shutil

from tools.registry import ToolRegistry
from tools.file_tool import FileWriterTool, FileReaderTool, DirectoryListerTool


class TestFileTools:
    """文件工具测试"""
    
    @pytest.fixture
    def temp_dir(self):
        """临时目录fixture"""
        temp = tempfile.mkdtemp()
        yield temp
        shutil.rmtree(temp)
    
    @pytest.mark.asyncio
    async def test_file_writer_tool(self, temp_dir):
        """测试文件写入工具"""
        tool = FileWriterTool()
        
        file_path = os.path.join(temp_dir, "test.txt")
        content = "Hello, World!"
        
        result = await tool.execute(
            file_path=file_path,
            content=content
        )
        
        assert result["success"] is True
        assert result["file_path"] == file_path
        assert os.path.exists(file_path)
        
        with open(file_path, 'r') as f:
            assert f.read() == content
    
    @pytest.mark.asyncio
    async def test_file_reader_tool(self, temp_dir):
        """测试文件读取工具"""
        # 先创建文件
        file_path = os.path.join(temp_dir, "test.txt")
        content = "Test content"
        with open(file_path, 'w') as f:
            f.write(content)
        
        # 读取文件
        tool = FileReaderTool()
        result = await tool.execute(file_path=file_path)
        
        assert result["success"] is True
        assert result["content"] == content
    
    @pytest.mark.asyncio
    async def test_file_reader_not_found(self, temp_dir):
        """测试读取不存在的文件"""
        tool = FileReaderTool()
        result = await tool.execute(
            file_path=os.path.join(temp_dir, "nonexistent.txt")
        )
        
        assert result["success"] is False
        assert "error" in result
    
    @pytest.mark.asyncio
    async def test_directory_lister_tool(self, temp_dir):
        """测试目录列表工具"""
        # 创建一些文件
        for i in range(3):
            with open(os.path.join(temp_dir, f"file{i}.txt"), 'w') as f:
                f.write(f"content{i}")
        
        # 创建子目录
        subdir = os.path.join(temp_dir, "subdir")
        os.makedirs(subdir)
        with open(os.path.join(subdir, "subfile.txt"), 'w') as f:
            f.write("subcontent")
        
        # 非递归列出
        tool = DirectoryListerTool()
        result = await tool.execute(
            directory_path=temp_dir,
            recursive=False
        )
        
        assert result["success"] is True
        assert result["count"] == 4  # 3 files + 1 directory
        assert "file0.txt" in result["files"]
        assert "subdir" in result["files"]
    
    @pytest.mark.asyncio
    async def test_directory_lister_recursive(self, temp_dir):
        """测试递归目录列表"""
        # 创建目录结构
        subdir = os.path.join(temp_dir, "subdir")
        os.makedirs(subdir)
        with open(os.path.join(subdir, "subfile.txt"), 'w') as f:
            f.write("subcontent")
        
        # 递归列出
        tool = DirectoryListerTool()
        result = await tool.execute(
            directory_path=temp_dir,
            recursive=True
        )
        
        assert result["success"] is True
        # 兼容 Windows 和 Linux 路径分隔符
        normalized_files = [f.replace("\\", "/") for f in result["files"]]
        assert "subdir/subfile.txt" in normalized_files


class TestToolRegistry:
    """工具注册表测试"""
    
    def test_register_tool(self):
        """测试工具注册"""
        registry = ToolRegistry()
        tool = FileWriterTool()
        
        registry.register(tool)
        
        assert "file_writer" in registry.list_tools()
        assert registry.get("file_writer") == tool
    
    def test_get_nonexistent_tool(self):
        """测试获取不存在的工具"""
        registry = ToolRegistry()
        
        assert registry.get("nonexistent_tool") is None
    
    def test_list_tools(self):
        """测试列出工具"""
        registry = ToolRegistry()
        registry.register(FileWriterTool())
        registry.register(FileReaderTool())
        
        tools = registry.list_tools()
        
        assert "file_writer" in tools
        assert "file_reader" in tools
        assert len(tools) == 2
