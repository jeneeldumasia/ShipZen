$ErrorActionPreference = "Stop"

Write-Host "Verifying AWS credentials..."
try {
    $callerIdentity = aws sts get-caller-identity | ConvertFrom-Json
} catch {
    Write-Host "AWS credentials not found or expired. Please run 'aws login' or configure your credentials first." -ForegroundColor Red
    exit 1
}

$accountId = $callerIdentity.Account
Write-Host "Authenticated as Account ID: $accountId" -ForegroundColor Green

Write-Host "Fetching account alias..."
$alias = aws iam list-account-aliases --query "AccountAliases[0]" --output text

if ($alias -eq "None" -or [string]::IsNullOrWhiteSpace($alias)) {
    $alias = "dry-run-$accountId"
    Write-Host "No account alias found. Creating temporary alias: $alias"
    aws iam create-account-alias --account-alias $alias
} else {
    Write-Host "Found account alias: $alias" -ForegroundColor Green
}

Write-Host "Fetching active AWS regions..."
$regions = aws ec2 describe-regions --query "Regions[].RegionName" --output text
$regionList = $regions -split "`t" | Where-Object { $_ -ne "" }

Write-Host "Generating nuke-config.yaml..."
$configPath = Join-Path $PWD "nuke-config.yaml"

$yaml = @"
regions:
  - global
"@

foreach ($region in $regionList) {
    $yaml += "`n  - $region"
}

$yaml += @"

account-blocklist:
  - "999999999999" # Placeholder to satisfy blocklist requirement

accounts:
  "$accountId":
    # Empty filters for dry-run
    filters: {}
"@

$yaml | Set-Content $configPath

Write-Host "Running aws-nuke in dry-run mode via Docker..." -ForegroundColor Yellow
Write-Host "This will take some time as it scans all regions." -ForegroundColor Cyan

# Use ekristen/aws-nuke, mapping the current directory and AWS credentials
docker run --rm -it `
  -v "${PWD}/nuke-config.yaml:/home/aws-nuke/config.yml" `
  -v "${env:USERPROFILE}\.aws:/home/aws-nuke/.aws" `
  -e AWS_PROFILE=$env:AWS_PROFILE `
  -e AWS_REGION=$env:AWS_REGION `
  -e AWS_DEFAULT_REGION=$env:AWS_DEFAULT_REGION `
  -e AWS_ACCESS_KEY_ID=$env:AWS_ACCESS_KEY_ID `
  -e AWS_SECRET_ACCESS_KEY=$env:AWS_SECRET_ACCESS_KEY `
  -e AWS_SESSION_TOKEN=$env:AWS_SESSION_TOKEN `
  ekristen/aws-nuke:latest --config /home/aws-nuke/config.yml --dry-run --force

Write-Host "`nDry-run complete!" -ForegroundColor Green
