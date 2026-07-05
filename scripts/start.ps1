<#
.SYNOPSIS
    Pick 项目一键启动脚本
.DESCRIPTION
    按顺序启动: Docker 中间件 → Java 后端 → Python AI 服务 → Vue 前端
.PARAMETER InfraOnly
    仅启动 Docker 中间件，不启动应用服务
.PARAMETER NoFrontend
    跳过前端启动
.PARAMETER NoAgent
    跳过 AI 服务启动
.EXAMPLE
    .\scripts\start.ps1                  # 启动全部
    .\scripts\start.ps1 -InfraOnly       # 仅启动中间件
    .\scripts\start.ps1 -NoFrontend      # 不启动前端
#>

param(
    [switch]$InfraOnly,
    [switch]$NoFrontend,
    [switch]$NoAgent
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  Pick 本地开发环境启动" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

# ==================== 1. Docker 中间件 ====================
Write-Host "[1/4] 启动 Docker 中间件..." -ForegroundColor Yellow
Push-Location $ProjectRoot
try {
    docker compose up -d
    if ($LASTEXITCODE -ne 0) { throw "Docker Compose 启动失败" }
} finally {
    Pop-Location
}

Write-Host "  等待 MySQL 就绪..." -ForegroundColor Gray
do {
    Start-Sleep -Seconds 2
    $mysqlHealth = docker inspect --format='{{json .State.Health.Status}}' pick-mysql 2>$null | ConvertFrom-Json
} while ($mysqlHealth -ne "healthy")
Write-Host "  MySQL ✓" -ForegroundColor Green

Write-Host "  等待 Redis 就绪..." -ForegroundColor Gray
do {
    Start-Sleep -Seconds 1
    $redisHealth = docker inspect --format='{{json .State.Health.Status}}' pick-redis 2>$null | ConvertFrom-Json
} while ($redisHealth -ne "healthy")
Write-Host "  Redis ✓" -ForegroundColor Green

Write-Host "  等待 Kafka 就绪..." -ForegroundColor Gray
do {
    Start-Sleep -Seconds 3
    $kafkaHealth = docker inspect --format='{{json .State.Health.Status}}' pick-kafka 2>$null | ConvertFrom-Json
} while ($kafkaHealth -ne "healthy")
Write-Host "  Kafka ✓" -ForegroundColor Green

Write-Host "  等待 Milvus 就绪（首次启动较慢）..." -ForegroundColor Gray
do {
    Start-Sleep -Seconds 5
    $milvusHealth = docker inspect --format='{{json .State.Health.Status}}' milvus-standalone 2>$null | ConvertFrom-Json
} while ($milvusHealth -ne "healthy")
Write-Host "  Milvus ✓" -ForegroundColor Green

Write-Host "中间件全部就绪！" -ForegroundColor Green
Write-Host ""

if ($InfraOnly) {
    Write-Host "仅启动中间件模式，跳过应用服务。" -ForegroundColor Cyan
    Write-Host "可用端口: MySQL:3306  Redis:6379  Kafka:9092  Milvus:19530" -ForegroundColor Gray
    return
}

# ==================== 2. Java 后端 ====================
Write-Host "[2/4] 启动 Java 后端 (core-service :8085)..." -ForegroundColor Yellow
$javaJob = Start-Job -Name "pick-core-service" -ScriptBlock {
    param($root)
    Set-Location "$root\core-service"
    mvn spring-boot:run 2>&1 | Out-File "$root\logs\core-service.log" -Encoding utf8
} -ArgumentList $ProjectRoot

# 确保日志目录存在
$null = New-Item -ItemType Directory -Force -Path "$ProjectRoot\logs"

Write-Host "  Java 后端启动中（日志: logs\core-service.log）" -ForegroundColor Gray
Write-Host "  等待端口 8085..." -ForegroundColor Gray
do {
    Start-Sleep -Seconds 3
    $portReady = (Test-NetConnection -ComputerName localhost -Port 8085 -WarningAction SilentlyContinue).TcpTestSucceeded
} while (-not $portReady)
Write-Host "  Java 后端 ✓" -ForegroundColor Green
Write-Host ""

# ==================== 3. Python AI 服务 ====================
if (-not $NoAgent) {
    Write-Host "[3/4] 启动 Python AI 服务 (agent-service :8000)..." -ForegroundColor Yellow
    $agentJob = Start-Job -Name "pick-agent-service" -ScriptBlock {
        param($root)
        Set-Location "$root\agent-service"
        uvicorn src.main:app --reload --port 8000 2>&1 | Out-File "$root\logs\agent-service.log" -Encoding utf8
    } -ArgumentList $ProjectRoot

    Write-Host "  AI 服务启动中（日志: logs\agent-service.log）" -ForegroundColor Gray
    Write-Host "  等待端口 8000..." -ForegroundColor Gray
    do {
        Start-Sleep -Seconds 2
        $portReady = (Test-NetConnection -ComputerName localhost -Port 8000 -WarningAction SilentlyContinue).TcpTestSucceeded
    } while (-not $portReady)
    Write-Host "  Python AI ✓" -ForegroundColor Green
} else {
    Write-Host "[3/4] 跳过 Python AI 服务" -ForegroundColor DarkGray
}
Write-Host ""

# ==================== 4. Vue 前端 ====================
if (-not $NoFrontend) {
    Write-Host "[4/4] 启动 Vue 前端 (vue3 :5173)..." -ForegroundColor Yellow
    $frontendJob = Start-Job -Name "pick-frontend" -ScriptBlock {
        param($root)
        Set-Location "$root\vue3"
        pnpm dev 2>&1 | Out-File "$root\logs\frontend.log" -Encoding utf8
    } -ArgumentList $ProjectRoot

    Write-Host "  前端启动中（日志: logs\frontend.log）" -ForegroundColor Gray
    Write-Host "  等待端口 5173..." -ForegroundColor Gray
    do {
        Start-Sleep -Seconds 2
        $portReady = (Test-NetConnection -ComputerName localhost -Port 5173 -WarningAction SilentlyContinue).TcpTestSucceeded
    } while (-not $portReady)
    Write-Host "  Vue 前端 ✓" -ForegroundColor Green
} else {
    Write-Host "[4/4] 跳过 Vue 前端" -ForegroundColor DarkGray
}

Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  全部启动完成！" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  Java 后端:  http://localhost:8085" -ForegroundColor White
if (-not $NoAgent) {
    Write-Host "  AI 服务:    http://localhost:8000" -ForegroundColor White
}
if (-not $NoFrontend) {
    Write-Host "  Vue 前端:   http://localhost:5173" -ForegroundColor White
}
Write-Host ""
Write-Host "  运行 .\scripts\stop.ps1 停止所有服务" -ForegroundColor Gray
Write-Host "========================================" -ForegroundColor Cyan
