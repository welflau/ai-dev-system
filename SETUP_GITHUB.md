# GitHub仓库创建和推送指南

## 方式一: 手动创建(推荐)

### 步骤1: 在GitHub网站创建仓库

1. 访问: https://github.com/new
2. 填写仓库信息:
   - **Repository name**: `ai-dev-system`
   - **Description**: AI驱动的全自动软件开发系统
   - **Public/Private**: 根据需要选择
   - **不要勾选** "Initialize this repository with a README"
   - **不要勾选** "Add a .gitignore"
   - **不要勾选** "Choose a license"
3. 点击 "Create repository"

### 步骤2: 推送代码

打开PowerShell,执行以下命令:

```powershell
cd "C:\Users\admin\WorkBuddy\20260322020138\ai-dev-system"

# 添加远程仓库
git remote add origin https://github.com/welflau/ai-dev-system.git

# 重命名分支为main
git branch -M main

# 推送到GitHub
git push -u origin main
```

---

## 方式二: 安装GitHub CLI(可选)

如果你想使用GitHub CLI,可以按以下步骤安装:

### Windows安装

```powershell
# 使用winget安装
winget install --id GitHub.cli

# 或者下载安装包
# 访问: https://cli.github.com/
# 下载Windows安装包并运行
```

### 安装后使用

```powershell
# 登录GitHub
gh auth login

# 创建仓库
gh repo create ai-dev-system --public --description "AI驱动的全自动软件开发系统" --source=. --remote=origin --push
```

---

## 验证推送成功

推送完成后,访问:
https://github.com/welflau/ai-dev-system

你应该能看到:
- README.md
- .gitignore
- LICENSE

---

## 推送后的后续配置

成功推送后,我们可以:

1. ✅ 创建GitHub Issues模板
2. ✅ 配置GitHub Actions CI/CD
3. ✅ 创建项目结构
4. ✅ 开发核心功能

---

**推荐使用方式一**,因为不需要安装额外工具,操作简单直接。
