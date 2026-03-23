"""
Git操作工具
"""
from typing import Optional, Dict, List
from .registry import BaseTool

try:
    from git import Repo, Actor, GitCommandError
    GIT_AVAILABLE = True
except ImportError:
    GIT_AVAILABLE = False
    print("警告: GitPython未安装,Git工具将不可用")


class GitInitTool(BaseTool):
    """Git初始化工具"""
    
    def __init__(self):
        super().__init__("git_init")
    
    async def execute(self, repo_path: str) -> Dict:
        """
        初始化Git仓库
        
        Args:
            repo_path: 仓库路径
        
        Returns:
            操作结果
        """
        if not GIT_AVAILABLE:
            return {
                "success": False,
                "error": "GitPython未安装"
            }
        
        try:
            import os
            # 确保目录存在
            if not os.path.exists(repo_path):
                os.makedirs(repo_path)
            
            # 检查是否已是Git仓库
            if os.path.exists(os.path.join(repo_path, '.git')):
                return {
                    "success": False,
                    "error": f"已经是Git仓库: {repo_path}"
                }
            
            # 初始化仓库
            repo = Repo.init(repo_path)
            
            return {
                "success": True,
                "repo_path": repo_path,
                "message": "Git仓库初始化成功"
            }
        except Exception as e:
            return {
                "success": False,
                "error": str(e)
            }
    
    def get_description(self) -> str:
        return """初始化Git仓库。如果目录不存在会自动创建。
        
        参数:
            repo_path: 仓库路径(必需)
        """
    
    def _get_parameters(self) -> Dict:
        return {
            "repo_path": {
                "type": "string",
                "description": "仓库路径",
                "required": True
            }
        }


class GitAddTool(BaseTool):
    """Git添加文件工具"""
    
    def __init__(self):
        super().__init__("git_add")
    
    async def execute(self, repo_path: str, files: List[str] = None) -> Dict:
        """
        添加文件到暂存区
        
        Args:
            repo_path: 仓库路径
            files: 文件列表,如果为None则添加所有修改
        
        Returns:
            操作结果
        """
        if not GIT_AVAILABLE:
            return {
                "success": False,
                "error": "GitPython未安装"
            }
        
        try:
            repo = Repo(repo_path)
            
            if files:
                repo.index.add(files)
            else:
                repo.index.add(["."])
            
            return {
                "success": True,
                "message": "文件已添加到暂存区",
                "files_count": len(files) if files else "all"
            }
        except GitCommandError as e:
            return {
                "success": False,
                "error": str(e)
            }
        except Exception as e:
            return {
                "success": False,
                "error": str(e)
            }
    
    def get_description(self) -> str:
        return """添加文件到Git暂存区。
        
        参数:
            repo_path: 仓库路径(必需)
            files: 文件路径列表,如果为None则添加所有修改(可选)
        """
    
    def _get_parameters(self) -> Dict:
        return {
            "repo_path": {
                "type": "string",
                "description": "仓库路径",
                "required": True
            },
            "files": {
                "type": "array",
                "description": "文件路径列表",
                "required": False
            }
        }


class GitCommitTool(BaseTool):
    """Git提交工具"""
    
    def __init__(self):
        super().__init__("git_commit")
    
    async def execute(
        self,
        repo_path: str,
        message: str,
        author_name: Optional[str] = "AI Agent",
        author_email: Optional[str] = "ai@agent.dev"
    ) -> Dict:
        """
        提交变更
        
        Args:
            repo_path: 仓库路径
            message: 提交消息
            author_name: 作者名称
            author_email: 作者邮箱
        
        Returns:
            操作结果
        """
        if not GIT_AVAILABLE:
            return {
                "success": False,
                "error": "GitPython未安装"
            }
        
        try:
            repo = Repo(repo_path)
            
            # 创建提交
            commit = repo.index.commit(
                message,
                author=Actor(author_name, author_email),
                committer=Actor(author_name, author_email)
            )
            
            return {
                "success": True,
                "commit_hash": commit.hexsha,
                "message": message,
                "author": f"{author_name} <{author_email}>"
            }
        except Exception as e:
            return {
                "success": False,
                "error": str(e)
            }
    
    def get_description(self) -> str:
        return """提交Git变更。
        
        参数:
            repo_path: 仓库路径(必需)
            message: 提交消息(必需)
            author_name: 作者名称,默认为"AI Agent"(可选)
            author_email: 作者邮箱,默认为"ai@agent.dev"(可选)
        """
    
    def _get_parameters(self) -> Dict:
        return {
            "repo_path": {
                "type": "string",
                "description": "仓库路径",
                "required": True
            },
            "message": {
                "type": "string",
                "description": "提交消息",
                "required": True
            },
            "author_name": {
                "type": "string",
                "description": "作者名称",
                "required": False
            },
            "author_email": {
                "type": "string",
                "description": "作者邮箱",
                "required": False
            }
        }


class GitPushTool(BaseTool):
    """Git推送工具"""
    
    def __init__(self):
        super().__init__("git_push")
    
    async def execute(
        self,
        repo_path: str,
        branch: str = "main",
        remote: str = "origin"
    ) -> Dict:
        """
        推送到远程仓库
        
        Args:
            repo_path: 仓库路径
            branch: 分支名称
            remote: 远程名称
        
        Returns:
            操作结果
        """
        if not GIT_AVAILABLE:
            return {
                "success": False,
                "error": "GitPython未安装"
            }
        
        try:
            repo = Repo(repo_path)
            origin = repo.remote(name=remote)
            
            # 推送
            push_info = origin.push(branch)
            
            return {
                "success": True,
                "branch": branch,
                "remote": remote,
                "remote_url": origin.url
            }
        except GitCommandError as e:
            return {
                "success": False,
                "error": str(e)
            }
        except Exception as e:
            return {
                "success": False,
                "error": str(e)
            }
    
    def get_description(self) -> str:
        return """推送到远程Git仓库。
        
        参数:
            repo_path: 仓库路径(必需)
            branch: 分支名称,默认为main(可选)
            remote: 远程名称,默认为origin(可选)
        """
    
    def _get_parameters(self) -> Dict:
        return {
            "repo_path": {
                "type": "string",
                "description": "仓库路径",
                "required": True
            },
            "branch": {
                "type": "string",
                "description": "分支名称",
                "required": False
            },
            "remote": {
                "type": "string",
                "description": "远程名称",
                "required": False
            }
        }


class GitCreateBranchTool(BaseTool):
    """Git创建分支工具"""
    
    def __init__(self):
        super().__init__("git_create_branch")
    
    async def execute(
        self,
        repo_path: str,
        branch_name: str,
        checkout: bool = True
    ) -> Dict:
        """
        创建新分支
        
        Args:
            repo_path: 仓库路径
            branch_name: 分支名称
            checkout: 是否切换到新分支
        
        Returns:
            操作结果
        """
        if not GIT_AVAILABLE:
            return {
                "success": False,
                "error": "GitPython未安装"
            }
        
        try:
            repo = Repo(repo_path)
            
            # 创建分支
            new_branch = repo.create_head(branch_name)
            
            # 如果需要,切换到新分支
            if checkout:
                new_branch.checkout()
            
            return {
                "success": True,
                "branch_name": branch_name,
                "checkout": checkout
            }
        except Exception as e:
            return {
                "success": False,
                "error": str(e)
            }
    
    def get_description(self) -> str:
        return """创建新的Git分支。
        
        参数:
            repo_path: 仓库路径(必需)
            branch_name: 分支名称(必需)
            checkout: 是否切换到新分支,默认为True(可选)
        """
    
    def _get_parameters(self) -> Dict:
        return {
            "repo_path": {
                "type": "string",
                "description": "仓库路径",
                "required": True
            },
            "branch_name": {
                "type": "string",
                "description": "分支名称",
                "required": True
            },
            "checkout": {
                "type": "boolean",
                "description": "是否切换到新分支",
                "required": False
            }
        }
