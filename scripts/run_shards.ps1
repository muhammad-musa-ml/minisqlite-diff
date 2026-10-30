# Run the fuzzer as parallel containers. Each shard takes a disjoint seed range.
# Usage (from the repository root):
#   powershell -File scripts/run_shards.ps1 -Image msqdiff:3541 -First 0 -Count 30000 -Shards 6 -Out out/fuzz3541
# Results land in <Out>/shardN.json (clusters) and <Out>/shardN.txt (the printed report).
param(
    [string]$Image = "msqdiff:3541",
    [int]$First = 0,
    [int]$Count = 30000,
    [int]$Shards = 6,
    [string]$Out = "out/fuzz",
    [int]$ShrinkLimit = 150,
    [int]$Budget = 300
)
$outFull = Join-Path (Get-Location) $Out
New-Item -ItemType Directory -Force -Path $outFull | Out-Null
$outParent = Split-Path $outFull -Parent
$leaf = Split-Path $outFull -Leaf
$per = [int][math]::Ceiling($Count / $Shards)
$procs = @()
for ($i = 0; $i -lt $Shards; $i++) {
    $seed = $First + $i * $per
    $log = Join-Path $outFull ("shard{0}.txt" -f $i)
    $err = Join-Path $outFull ("shard{0}.err" -f $i)
    $dockerArgs = @("run", "--rm", "-v", "${outParent}:/out", $Image, "fuzz", "--seed", $seed, "--count", $per,
        "--shrink-limit", $ShrinkLimit, "--budget", $Budget, "--out", "/out/$leaf/shard$i.json")
    $procs += Start-Process -FilePath docker -ArgumentList $dockerArgs -RedirectStandardOutput $log -RedirectStandardError $err -PassThru -NoNewWindow
}
$procs | Wait-Process
"done: $Shards shards of $per cases from seed $First on $Image"
