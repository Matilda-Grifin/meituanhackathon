$ErrorActionPreference = "Continue"
Set-Location "D:\projects\meituan hackathon\meituan-lifecare-agent\测试\模型选型"
$host = "root@121.41.81.58"
$out = "/root/meituan-lifecare-agent/benchmark/model_selection/results/v63-batch/qwen"
Write-Host "[watch] retry batch monitor started $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')"

while ($true) {
    try {
        $state = ssh -o BatchMode=yes -o ConnectTimeout=25 $host "test -f $out/batch.pid && ps -p `$(cat $out/batch.pid) >/dev/null 2>&1 && echo RUNNING || echo STOPPED; tail -n 3 $out/batch.log 2>/dev/null"
        Write-Host "`n--- $(Get-Date -Format 'HH:mm:ss') ---"
        Write-Host $state
        if ($state -match "STOPPED") {
            Write-Host "[watch] batch stopped, pulling results..."
            python remote_vitabench_batch.py --pull
            python -c "import json; d=json.load(open('results/v63-batch/qwen/batch_summary.json',encoding='utf-8')); f=[r['task_id'] for r in d.get('results',[]) if not r.get('ok')]; print('remaining_failed:', f)"
            break
        }
    } catch {
        Write-Host "[watch] poll error: $_"
    }
    Start-Sleep -Seconds 120
}
Write-Host "[watch] done $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')"
