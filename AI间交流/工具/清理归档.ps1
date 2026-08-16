param([switch]$Execute)
$ErrorActionPreference = 'Stop'
$ai = Split-Path -Parent $PSScriptRoot
$archive = Join-Path $ai '任务\归档'
if (-not (Test-Path -LiteralPath $archive)) { Write-Output '归档目录不存在，无需清理'; return }
$cutoff = (Get-Date).AddDays(-30)
$targets = Get-ChildItem -LiteralPath $archive -Recurse -File -Force -ErrorAction SilentlyContinue | Where-Object { $_.LastWriteTime -lt $cutoff }
if (-not $targets) { Write-Output "无超过 30 天的归档文件（截止 $($cutoff.ToString('yyyy-MM-dd'))）"; return }
foreach ($t in $targets) { Write-Output ("{0}  |  {1} 天前" -f $t.FullName, [math]::Round(((Get-Date) - $t.LastWriteTime).TotalDays, 1)) }
if ($Execute) { $targets | Remove-Item -Force; Write-Output "已删除 $($targets.Count) 个文件" } else { Write-Output "dry-run：共 $($targets.Count) 个候选，加 -Execute 执行删除" }
