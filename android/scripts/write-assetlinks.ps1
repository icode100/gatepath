[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string[]] $Fingerprint,

    [string] $OutputPath
)

$fingerprintPattern = '^([0-9A-Fa-f]{2}:){31}[0-9A-Fa-f]{2}$'
$normalized = foreach ($value in $Fingerprint) {
    $candidate = $value.Trim().ToUpperInvariant()
    if ($candidate -notmatch $fingerprintPattern) {
        throw "Invalid SHA-256 certificate fingerprint: $value"
    }
    $candidate
}

if (-not $OutputPath) {
    $OutputPath = Join-Path $PSScriptRoot '..\..\public\.well-known\assetlinks.json'
}

$resolvedOutput = [System.IO.Path]::GetFullPath($OutputPath)
$outputDirectory = Split-Path -Parent $resolvedOutput
[System.IO.Directory]::CreateDirectory($outputDirectory) | Out-Null

$statement = @(
    [ordered]@{
        relation = @('delegate_permission/common.handle_all_urls')
        target = [ordered]@{
            namespace = 'android_app'
            package_name = 'com.icode100.gatepath'
            sha256_cert_fingerprints = @($normalized)
        }
    }
)

$json = ConvertTo-Json -InputObject $statement -Depth 8
[System.IO.File]::WriteAllText(
    $resolvedOutput,
    "$json`n",
    [System.Text.UTF8Encoding]::new($false)
)

Write-Host "Wrote Digital Asset Links statement to $resolvedOutput"
