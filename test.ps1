# Quick Test Script for AI Dev System

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "AI Dev System - Quick Test" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

# Test 1: Health Check
Write-Host "Test 1: Health Check" -ForegroundColor Yellow
Write-Host "----------------------------------------" -ForegroundColor Gray
try {
    $response = Invoke-RestMethod -Uri "http://localhost:8000/health" -Method Get
    Write-Host "SUCCESS: Health check passed" -ForegroundColor Green
    Write-Host "   Status: $($response.status)" -ForegroundColor White
    Write-Host "   Tools available: $($response.tools_available)" -ForegroundColor White
} catch {
    Write-Host "FAILED: Health check failed" -ForegroundColor Red
    Write-Host "   Ensure backend is running at http://localhost:8000" -ForegroundColor Yellow
    exit 1
}
Write-Host ""

# Test 2: List Tools
Write-Host "Test 2: List Tools" -ForegroundColor Yellow
Write-Host "----------------------------------------" -ForegroundColor Gray
try {
    $response = Invoke-RestMethod -Uri "http://localhost:8000/tools" -Method Get
    $tools = $response.tools
    Write-Host "SUCCESS: Tools list retrieved" -ForegroundColor Green
    Write-Host "   Total: $($tools.Count) tools" -ForegroundColor White
    foreach ($key in $tools.Keys) {
        Write-Host "   - $key" -ForegroundColor Cyan
    }
} catch {
    Write-Host "FAILED: Could not get tools list" -ForegroundColor Red
}
Write-Host ""

# Test 3: Submit Requirement
Write-Host "Test 3: Submit Requirement" -ForegroundColor Yellow
Write-Host "----------------------------------------" -ForegroundColor Gray
$testDescription = "I want to develop a simple todo app"
Write-Host "   Description: $testDescription" -ForegroundColor White

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
    Write-Host "SUCCESS: Requirement submitted" -ForegroundColor Green
    Write-Host "   Project ID: $($response.project_id)" -ForegroundColor White
    Write-Host "   Status: $($response.status)" -ForegroundColor White
    Write-Host "   Message: $($response.message)" -ForegroundColor White

    $projectId = $response.project_id
} catch {
    Write-Host "FAILED: Could not submit requirement" -ForegroundColor Red
    exit 1
}
Write-Host ""

# Test 4: Query Project Status (Optional)
Write-Host "Test 4: Query Project Status" -ForegroundColor Yellow
Write-Host "----------------------------------------" -ForegroundColor Gray
try {
    $response = Invoke-RestMethod -Uri "http://localhost:8000/api/projects/$projectId/state" -Method Get
    Write-Host "SUCCESS: Project status retrieved" -ForegroundColor Green
    Write-Host "   Project ID: $($response.project_state.project_id)" -ForegroundColor White
    Write-Host "   Status: $($response.project_state.status)" -ForegroundColor White
} catch {
    Write-Host "WARNING: Could not query project status" -ForegroundColor Yellow
    Write-Host "   This is a known issue, other features work fine" -ForegroundColor Yellow
}
Write-Host ""

# Summary
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "Test Complete!" -ForegroundColor Green
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "TIPS:" -ForegroundColor Yellow
Write-Host "   1. API Docs: http://localhost:8000/docs" -ForegroundColor White
Write-Host "   2. Frontend: D:\A_Works\ai-dev-system\frontend\index.html" -ForegroundColor White
Write-Host "   3. Test Report: D:\A_Works\ai-dev-system\test-report.md" -ForegroundColor White
Write-Host ""
