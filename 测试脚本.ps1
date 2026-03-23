# AI 自动开发系统 - 快速测试脚本

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "AI 自动开发系统 - 快速测试脚本" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

# 测试 1: 健康检查
Write-Host "测试 1: 健康检查" -ForegroundColor Yellow
Write-Host "----------------------------------------" -ForegroundColor Gray
try {
    $response = Invoke-RestMethod -Uri "http://localhost:8000/health" -Method Get
    Write-Host "✅ 健康检查成功" -ForegroundColor Green
    Write-Host "   状态: $($response.status)" -ForegroundColor White
    Write-Host "   可用工具: $($response.tools_available)" -ForegroundColor White
} catch {
    Write-Host "❌ 健康检查失败: $($_.Exception.Message)" -ForegroundColor Red
    Write-Host "   请确保后端服务正在运行在 http://localhost:8000" -ForegroundColor Yellow
    exit 1
}
Write-Host ""

# 测试 2: 查看工具列表
Write-Host "测试 2: 查看工具列表" -ForegroundColor Yellow
Write-Host "----------------------------------------" -ForegroundColor Gray
try {
    $response = Invoke-RestMethod -Uri "http://localhost:8000/tools" -Method Get
    $tools = $response.tools
    Write-Host "✅ 工具列表获取成功" -ForegroundColor Green
    Write-Host "   共 $($tools.Count) 个工具:" -ForegroundColor White
    foreach ($key in $tools.Keys) {
        Write-Host "   - $key" -ForegroundColor Cyan
    }
} catch {
    Write-Host "❌ 获取工具列表失败: $($_.Exception.Message)" -ForegroundColor Red
}
Write-Host ""

# 测试 3: 提交需求
Write-Host "测试 3: 提交需求" -ForegroundColor Yellow
Write-Host "----------------------------------------" -ForegroundColor Gray
$testDescription = "我想开发一个简单的待办事项应用"
Write-Host "   提交需求: $testDescription" -ForegroundColor White

try {
    $body = @{
        description = $testDescription
        tech_stack = @{
            frontend = "HTML"
            backend = "Python"
            framework = "FastAPI"
        }
    } | ConvertTo-Json -Depth 3

    $response = Invoke-RestMethod -Uri "http://localhost:8000/api/process" -Method Post -Body $body -ContentType "application/json"
    Write-Host "✅ 需求提交成功" -ForegroundColor Green
    Write-Host "   项目 ID: $($response.project_id)" -ForegroundColor White
    Write-Host "   状态: $($response.status)" -ForegroundColor White
    Write-Host "   消息: $($response.message)" -ForegroundColor White

    $projectId = $response.project_id
} catch {
    Write-Host "❌ 需求提交失败: $($_.Exception.Message)" -ForegroundColor Red
    exit 1
}
Write-Host ""

# 测试 4: 查询项目状态（可选）
Write-Host "测试 4: 查询项目状态" -ForegroundColor Yellow
Write-Host "----------------------------------------" -ForegroundColor Gray
try {
    $response = Invoke-RestMethod -Uri "http://localhost:8000/api/projects/$projectId/state" -Method Get
    Write-Host "✅ 项目状态查询成功" -ForegroundColor Green
    Write-Host "   项目 ID: $($response.project_state.project_id)" -ForegroundColor White
    Write-Host "   状态: $($response.project_state.status)" -ForegroundColor White
    Write-Host "   创建时间: $($response.project_state.created_at)" -ForegroundColor White
} catch {
    Write-Host "⚠️  项目状态查询失败: $($_.Exception.Message)" -ForegroundColor Yellow
    Write-Host "   这是一个已知问题，不影响其他功能使用" -ForegroundColor Yellow
}
Write-Host ""

# 总结
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "测试完成!" -ForegroundColor Green
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "💡 提示:" -ForegroundColor Yellow
Write-Host "   1. 查看 API 文档: http://localhost:8000/docs" -ForegroundColor White
Write-Host "   2. 打开前端界面: D:\A_Works\ai-dev-system\frontend\index.html" -ForegroundColor White
Write-Host "   3. 查看完整测试报告: D:\A_Works\ai-dev-system\测试报告.md" -ForegroundColor White
Write-Host ""
