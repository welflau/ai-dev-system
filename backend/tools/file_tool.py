"""
文件操作工具
"""
import os
from typing import Dict, Optional
from .registry import BaseTool


class FileWriterTool(BaseTool):
    """文件写入工具"""
    
    def __init__(self):
        super().__init__("file_writer")
    
    async def execute(self, file_path: str, content: str, create_dirs: bool = True) -> Dict:
        """
        写入文件
        
        Args:
            file_path: 文件路径
            content: 文件内容
            create_dirs: 是否自动创建目录
        
        Returns:
            操作结果
        """
        try:
            # 确保目录存在
            if create_dirs:
                directory = os.path.dirname(file_path)
                if directory and not os.path.exists(directory):
                    os.makedirs(directory, exist_ok=True)
            
            # 写入文件
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(content)
            
            return {
                "success": True,
                "file_path": file_path,
                "bytes_written": len(content.encode('utf-8'))
            }
        except Exception as e:
            return {
                "success": False,
                "error": str(e)
            }
    
    def get_description(self) -> str:
        return """写入文件内容。支持自动创建目录。
        
        参数:
            file_path: 文件路径(必需)
            content: 文件内容(必需)
            create_dirs: 是否自动创建目录,默认为True(可选)
        """
    
    def _get_parameters(self) -> Dict:
        return {
            "file_path": {
                "type": "string",
                "description": "文件路径",
                "required": True
            },
            "content": {
                "type": "string",
                "description": "文件内容",
                "required": True
            },
            "create_dirs": {
                "type": "boolean",
                "description": "是否自动创建目录",
                "required": False
            }
        }


class FileReaderTool(BaseTool):
    """文件读取工具"""
    
    def __init__(self):
        super().__init__("file_reader")
    
    async def execute(self, file_path: str) -> Dict:
        """
        读取文件
        
        Args:
            file_path: 文件路径
        
        Returns:
            文件内容
        """
        try:
            if not os.path.exists(file_path):
                return {
                    "success": False,
                    "error": f"文件不存在: {file_path}"
                }
            
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
            
            return {
                "success": True,
                "file_path": file_path,
                "content": content,
                "bytes_read": len(content.encode('utf-8'))
            }
        except Exception as e:
            return {
                "success": False,
                "error": str(e)
            }
    
    def get_description(self) -> str:
        return """读取文件内容。
        
        参数:
            file_path: 文件路径(必需)
        """
    
    def _get_parameters(self) -> Dict:
        return {
            "file_path": {
                "type": "string",
                "description": "文件路径",
                "required": True
            }
        }


class DirectoryListerTool(BaseTool):
    """目录列表工具"""
    
    def __init__(self):
        super().__init__("directory_lister")
    
    async def execute(self, directory_path: str, recursive: bool = False) -> Dict:
        """
        列出目录内容
        
        Args:
            directory_path: 目录路径
            recursive: 是否递归列出子目录
        
        Returns:
            目录内容列表
        """
        try:
            if not os.path.exists(directory_path):
                return {
                    "success": False,
                    "error": f"目录不存在: {directory_path}"
                }
            
            if recursive:
                files = []
                for root, dirs, filenames in os.walk(directory_path):
                    for filename in filenames:
                        full_path = os.path.join(root, filename)
                        rel_path = os.path.relpath(full_path, directory_path)
                        files.append(rel_path)
            else:
                files = os.listdir(directory_path)
            
            return {
                "success": True,
                "directory_path": directory_path,
                "files": files,
                "count": len(files)
            }
        except Exception as e:
            return {
                "success": False,
                "error": str(e)
            }
    
    def get_description(self) -> str:
        return """列出目录中的文件和子目录。
        
        参数:
            directory_path: 目录路径(必需)
            recursive: 是否递归列出子目录,默认为False(可选)
        """
    
    def _get_parameters(self) -> Dict:
        return {
            "directory_path": {
                "type": "string",
                "description": "目录路径",
                "required": True
            },
            "recursive": {
                "type": "boolean",
                "description": "是否递归列出子目录",
                "required": False
            }
        }
