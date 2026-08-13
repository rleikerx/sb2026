<#
.SYNOPSIS
    Rebuild export_aegisfall/ from the client cache and verify nothing regressed.

.DESCRIPTION
    Runs every exporter in dependency order, then every wiki checker, and fails loudly
    if a bundle shrinks or an agreement score drops. One command to go from arcane_dump/
    to a shippable export.

    The default is the data layer -- content, powers, zones, rules, terrain, motion
    tracks -- which takes minutes. The asset bakes (models, textures, skeletons, graph,
    maps, effects) are hours and multiple gigabytes, so they are behind -All.

    Every exporter's default --out already points at the right place, so this passes no
    paths. If you are tempted to add one, change the exporter instead: a path in two
    places is a path that will disagree with itself.

.PARAMETER All
    Also run the heavy asset bakes. Hours, and ~4 GB of output.

.PARAMETER SkipChecks
    Export only. Use when the wiki is unreachable -- the checkers need network.

.PARAMETER ChecksOnly
    Verify the export already on disk without rebuilding it.

.EXAMPLE
    .\loop.ps1
    .\loop.ps1 -All
    .\loop.ps1 -ChecksOnly
#>
[CmdletBinding()]
param(
    [switch]$All,
    [switch]$SkipChecks,
    [switch]$ChecksOnly
)

$ErrorActionPreference = 'Stop'
$root   = $PSScriptRoot
$python = Join-Path $root 'viewer_env\Scripts\python.exe'
$export = Join-Path $root 'export_aegisfall'

if (-not (Test-Path $python)) {
    Write-Host "python not found at $python" -ForegroundColor Red
    Write-Host "expected the viewer_env virtualenv; create it or edit `$python above."
    exit 1
}

# The scores this export currently achieves. A checker printing anything lower is a
# regression and fails the run; anything HIGHER is also reported, because a score that
# improves without someone intending it means the comparison changed, not the data.
$expected = [ordered]@{
    'check_powers_wiki.py'      = @{ Pattern = 'agreement (\d+)/(\d+)';            Score = 1; Total = 2; Floor = 384 }
    'check_races_wiki.py'       = @{ Pattern = 'classes (\d+)/(\d+)';              Score = 1; Total = 2; Floor = 167 }
    'check_classes_wiki.py'     = @{ Pattern = 'skills (\d+)/(\d+)';               Score = 1; Total = 2; Floor = 69  }
    'check_disciplines_wiki.py' = @{ Pattern = 'classes (\d+)/(\d+)';              Score = 1; Total = 2; Floor = 214 }
    'check_talents_wiki.py'     = @{ Pattern = '^(\d+)/(\d+) agree';               Score = 1; Total = 2; Floor = 407 }
    'check_structures_wiki.py'  = @{ Pattern = '^(\d+)/(\d+) agree';               Score = 1; Total = 2; Floor = 159 }
    # This one prints "811 weapons, 785 with damage" -- the score is the SECOND number.
    # Reading group 1 gives 811 against a floor of 785 and reports a phantom improvement.
    'check_items_wiki.py'       = @{ Pattern = '(\d+) weapons, (\d+) with damage'; Score = 2; Total = 1; Floor = 785 }
}

# Row counts the export is known to produce. A table that shrinks is the failure mode
# this whole exercise exists to catch -- an empty column looks exactly like a correct one.
$expectedRows = [ordered]@{
    'content\races.json'              = 33
    'content\classes.json'            = 27
    'content\disciplines.json'        = 48
    'content\talents.json'            = 240
    'content\items.json'              = 4021
    'content\structures.json'         = 1062
    'content\deeds.json'              = 880
    'content\starting_kits.json'      = 68
    'content\guild_ranks.json'        = 21
}

# Source material that ships and nothing reads. These are CEILINGS, the mirror image of the
# scores above: they are meant to fall as exporters are written, and a rise means either new
# material arrived unread or something stopped reading what it used to.
#
# 889 is honest rather than alarming -- 703 of it is the treasure tables, which decrypt now
# but have no exporter yet, and much of the rest is the UI config the sweep of the archives
# already judged out of scope. The number's job is to be unable to go up quietly.
$expectedCoverage = [ordered]@{
    'unread'   = @{ Ceiling = 889; Note = 'files no exporter names' }
    'dangling' = @{ Ceiling = 1;   Note = 'treasure ids pointing at nothing' }
    'orphans'  = @{ Ceiling = 107; Note = 'tables nothing points at' }
}

# Runs first: every exporter below reads out of config/, and this is what fills it. Cheap
# (seconds), and it no-ops with a note when the client is not mounted. It was outside the loop
# until the day it turned out to have been writing 727 of its 930 files back out as ciphertext
# -- a step nothing runs is a step nothing checks.
$configLayer = @(
    @{ Name = 'decrypt_wpak.py';         Note = 'client .wpak archives -> config/ (Blowfish CFB)' }
)

$dataLayer = @(
    @{ Name = 'export_content.py';       Note = 'races, classes, talents, items, structures, deeds, kits, guilds' },
    @{ Name = 'export_powers.py';        Note = 'powers, effects, actions, enchantments' },
    @{ Name = 'export_rules.py';         Note = 'speeds, recovery, curves, mod types, skills' },
    @{ Name = 'export_zones.py';         Note = 'zones, placements, required models, macrozones' },
    @{ Name = 'export_terrain.py';       Note = 'zone heightmaps and the placing transform' },
    @{ Name = 'export_animation_table.py'; Note = 'ANIMID resolution and overrides' },
    @{ Name = 'export_motion_tracks.py'; Note = 'parent-frame motion tracks' }
)

# Hours, and gigabytes. export_content must precede these: export_zones names placements
# from models/assets.json when it is present.
$assetLayer = @(
    @{ Name = 'export_skeletons.py';     Note = 'rig/' },
    @{ Name = 'export_motions.py';       Note = 'skeletons.json / poses.json' },
    @{ Name = 'export_assets.py';        Note = 'models/ and textures -- the 1.8 GB one' },
    @{ Name = 'export_weapon_models.py'; Note = 'weapon meshes' },
    @{ Name = 'export_graph.py';         Note = 'graph/' },
    @{ Name = 'export_maps.py';          Note = 'world images' },
    @{ Name = 'export_effects.py';       Note = 'effects/' }
)

$failures = New-Object System.Collections.Generic.List[string]
$started  = Get-Date

function Invoke-Step {
    param([string]$Script, [string]$Note, [int]$Index, [int]$Total)

    $label = "[$Index/$Total] $Script"
    Write-Host ("{0,-42}{1}" -f $label, $Note) -ForegroundColor Cyan
    $path = Join-Path $root "tools\$Script"
    if (-not (Test-Path $path)) {
        $failures.Add("$Script - not found at $path")
        Write-Host "        MISSING" -ForegroundColor Red
        return
    }
    # No 2>&1: in PowerShell 5.1 that wraps a native command's stderr in ErrorRecords and
    # sets $? false even on a clean exit. stderr reaches the console on its own.
    & $python $path
    if ($LASTEXITCODE -ne 0) {
        $failures.Add("$Script - exit $LASTEXITCODE")
        Write-Host "        FAILED (exit $LASTEXITCODE)" -ForegroundColor Red
    }
}

function Test-RowCounts {
    Write-Host ''
    Write-Host 'row counts' -ForegroundColor Cyan
    foreach ($rel in $expectedRows.Keys) {
        $file = Join-Path $export $rel
        if (-not (Test-Path $file)) {
            $failures.Add("$rel - missing")
            Write-Host ("  {0,-34}MISSING" -f $rel) -ForegroundColor Red
            continue
        }
        $want = $expectedRows[$rel]
        $got  = (Get-Content $file -Raw | ConvertFrom-Json).Count
        if ($got -eq $want) {
            Write-Host ("  {0,-34}{1}" -f $rel, $got) -ForegroundColor Green
        } else {
            $failures.Add("$rel - $got rows, expected $want")
            $colour = if ($got -lt $want) { 'Red' } else { 'Yellow' }
            Write-Host ("  {0,-34}{1}  expected {2}" -f $rel, $got, $want) -ForegroundColor $colour
        }
    }
}

function Test-ConfigBundle {
    Write-Host ''
    Write-Host 'config bundle  (complete, and actually decrypted)' -ForegroundColor Cyan
    $out = & $python (Join-Path $root 'tools\decrypt_wpak.py') --verify
    $summary = $out | Select-String -Pattern 'verify\|dirs=(\d+)\|files=(\d+)\|ciphertext=(\d+)\|problems=(\d+)' | Select-Object -Last 1
    if (-not $summary) {
        $failures.Add('decrypt_wpak.py --verify - no summary line')
        Write-Host '  no summary line in output' -ForegroundColor Red
        return
    }
    $files      = [int]$summary.Matches[0].Groups[2].Value
    $ciphertext = [int]$summary.Matches[0].Groups[3].Value
    $problems   = [int]$summary.Matches[0].Groups[4].Value
    if ($problems -eq 0) {
        Write-Host ("  {0,-30}{1} files, all plaintext" -f 'decrypt_wpak.py --verify', $files) -ForegroundColor Green
        return
    }
    $failures.Add("decrypt_wpak.py --verify - $problems problem(s), $ciphertext still encrypted")
    Write-Host ("  {0,-30}{1} problem(s), {2} still encrypted" -f 'decrypt_wpak.py --verify', $problems, $ciphertext) -ForegroundColor Red
    $out | Select-String -Pattern '^  \S' | ForEach-Object { Write-Host "    $_" -ForegroundColor Red }
}

function Test-Coverage {
    Write-Host ''
    Write-Host 'coverage  (source material nothing reads - ceilings, not floors)' -ForegroundColor Cyan
    $out = & $python (Join-Path $root 'tools\check_coverage.py')
    if ($LASTEXITCODE -ne 0) {
        $failures.Add("check_coverage.py - exit $LASTEXITCODE")
        Write-Host ("  {0,-30}FAILED (exit $LASTEXITCODE)" -f 'check_coverage.py') -ForegroundColor Red
        return
    }
    $summary = $out | Select-String -Pattern 'coverage\|unread=(\d+)\|dangling=(\d+)\|orphans=(\d+)' | Select-Object -Last 1
    if (-not $summary) {
        $failures.Add('check_coverage.py - no summary line')
        Write-Host '  no summary line in output' -ForegroundColor Red
        return
    }
    $got = @{
        'unread'   = [int]$summary.Matches[0].Groups[1].Value
        'dangling' = [int]$summary.Matches[0].Groups[2].Value
        'orphans'  = [int]$summary.Matches[0].Groups[3].Value
    }
    foreach ($key in $expectedCoverage.Keys) {
        $rule = $expectedCoverage[$key]
        $value = $got[$key]
        $label = "$key ($($rule.Note))"
        if ($value -gt $rule.Ceiling) {
            $failures.Add("coverage $key - $value, ceiling $($rule.Ceiling)")
            Write-Host ("  {0,-48}{1}  ROSE from {2}" -f $label, $value, $rule.Ceiling) -ForegroundColor Red
        } elseif ($value -lt $rule.Ceiling) {
            # Progress. Say so, and say the ceiling is now stale -- an unlowered ceiling lets
            # the number climb back to the old value without anyone hearing about it.
            Write-Host ("  {0,-48}{1}  down from {2} - lower the ceiling" -f $label, $value, $rule.Ceiling) -ForegroundColor Yellow
        } else {
            Write-Host ("  {0,-48}{1}" -f $label, $value) -ForegroundColor Green
        }
    }
}

function Test-Checkers {
    Write-Host ''
    Write-Host 'wiki checks  (needs network; cached under .wikicache/)' -ForegroundColor Cyan
    foreach ($script in $expected.Keys) {
        $path = Join-Path $root "tools\$script"
        if (-not (Test-Path $path)) {
            $failures.Add("$script - not found")
            Write-Host ("  {0,-30}MISSING" -f $script) -ForegroundColor Red
            continue
        }
        $out = & $python $path
        if ($LASTEXITCODE -ne 0) {
            $failures.Add("$script - exit $LASTEXITCODE")
            Write-Host ("  {0,-30}FAILED (exit $LASTEXITCODE)" -f $script) -ForegroundColor Red
            continue
        }
        $rule  = $expected[$script]
        $match = $out | Select-String -Pattern $rule.Pattern | Select-Object -Last 1
        if (-not $match) {
            $failures.Add("$script - no line matching '$($rule.Pattern)'")
            Write-Host ("  {0,-30}score not found in output" -f $script) -ForegroundColor Red
            continue
        }
        $score = [int]$match.Matches[0].Groups[$rule.Score].Value
        $total = $match.Matches[0].Groups[$rule.Total].Value
        if ($score -lt $rule.Floor) {
            $failures.Add("$script - $score, floor $($rule.Floor)")
            Write-Host ("  {0,-30}{1}/{2}  REGRESSED from {3}" -f $script, $score, $total, $rule.Floor) -ForegroundColor Red
        } elseif ($score -gt $rule.Floor) {
            # Not a failure, but not silent either. A score that rises on its own means
            # the comparison changed; update the floor deliberately or find out why.
            Write-Host ("  {0,-30}{1}/{2}  above the recorded {3} - raise the floor if intended" -f $script, $score, $total, $rule.Floor) -ForegroundColor Yellow
        } else {
            Write-Host ("  {0,-30}{1}/{2}" -f $script, $score, $total) -ForegroundColor Green
        }
    }
}

Write-Host ''
Write-Host 'rebuilding export_aegisfall/' -ForegroundColor White
Write-Host "  python  $python"
Write-Host "  output  $export"
Write-Host ''

if (-not $ChecksOnly) {
    $steps = $configLayer + $dataLayer
    if ($All) { $steps = $configLayer + $dataLayer + $assetLayer }
    $n = $steps.Count
    for ($i = 0; $i -lt $n; $i++) {
        Invoke-Step -Script $steps[$i].Name -Note $steps[$i].Note -Index ($i + 1) -Total $n
    }
    if (-not $All) {
        Write-Host ''
        Write-Host 'skipped the asset bakes (models, textures, rig, graph, maps, effects) - pass -All for those' -ForegroundColor DarkGray
    }
    Test-RowCounts
}

# Both run even under -SkipChecks: they read the export on disk and need no network, which is
# the situation -SkipChecks exists for.
Test-ConfigBundle
Test-Coverage

if (-not $SkipChecks) { Test-Checkers }

$elapsed = (Get-Date) - $started
Write-Host ''
if ($failures.Count -eq 0) {
    Write-Host ("OK - no regressions  ({0:mm\:ss})" -f $elapsed) -ForegroundColor Green
    exit 0
}
Write-Host ("{0} problem(s)  ({1:mm\:ss})" -f $failures.Count, $elapsed) -ForegroundColor Red
foreach ($f in $failures) { Write-Host "  $f" -ForegroundColor Red }
exit 1
