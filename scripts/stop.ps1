<#
.SYNOPSIS
    停止 Pick 项目的所有服务
.DESCRIPTION
    停止前端/Vue → AI/Python → Java → Docker 中间件
.PARAMETER KeepInfra
    保留 Docker 中间件运行，仅停止应用服务
#>

param(
    [switch]$KeepInfra
)

$ErrorActionPreference = "Continue"
$ProjectRoot = Split-Path -Parent $PSScriptRoot

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  停止 Pick 开发环境" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan

# 停止后台 Job（前端、AI、Java）
Write-Host "停止应用服务..." -ForegroundColor Yellow
Get-Job -Name "pick-frontend" -ErrorAction SilentlyContinue | Stop-Job -PassThru | Remove-Job -Force
Get-Job -Name "pick-agent-service" -ErrorAction SilentlyContinue | Stop-Job -PassThru | Remove-Job -Force
Get-Job -Name "pick-core-service" -ErrorAction SilentlyContinue | Stop-Job -PassThru | Remove-Job -Force
Write-Host "  应用服务已停止" -ForegroundColor Green

# 停止 Docker 中间件
if (-not $KeepInfra) {
    Write-Host "停止 Docker 中间件..." -ForegroundColor Yellow
    Push-Location $ProjectRoot
    try {
        docker compose stop
        if ($LASTEXITCODE -eq 0) {
            Write-Host "  中间件已停止" -ForegroundColor Green
        }
    } finally {
        Pop-Location
    }
} else {
    Write-Host "保留 Docker 中间件运行" -ForegroundColor Gray
}

Write-Host ""
Write-Host "全部已停止。" -ForegroundColor Green
