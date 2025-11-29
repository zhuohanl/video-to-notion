# Creates the storage account (if missing) and blob containers used by the VI prototype.
# Ensures allowSharedKeyAccess is enabled.
# Usage: ./scripts/bootstrap-storage.ps1 -StorageAccountName <name> -ResourceGroup <rg> [-Location <loc>] [-Sku <sku>]

param(
  [Parameter(Mandatory = $true)]
  [string]$StorageAccountName,
  [Parameter(Mandatory = $true)]
  [string]$ResourceGroup,
  [string]$Location = "eastus",
  [string]$Sku = "Standard_LRS"
)

$containers = @("raw", "video-indexer", "frames", "outputs", "manifests")

function Ensure-AzCli {
  $az = Get-Command az -ErrorAction SilentlyContinue
  if (-not $az) {
    throw "Azure CLI (az) not found on PATH. Install az and run az login first."
  }
}

function Ensure-ResourceGroup {
  param([string]$Rg, [string]$Loc)
  $exists = az group exists --name $Rg | ConvertFrom-Json
  if (-not $exists) {
    Write-Host "Creating resource group '$Rg' in '$Loc'..." -ForegroundColor Cyan
    az group create --name $Rg --location $Loc | Out-Null
  } else {
    Write-Host "Resource group '$Rg' found." -ForegroundColor Green
  }
}

function Ensure-StorageAccount {
  param([string]$Name, [string]$Rg, [string]$Loc, [string]$Sku)
  $exists = $false
  $acct = az storage account show --name $Name --resource-group $Rg 2>$null
  if ($LASTEXITCODE -eq 0 -and $acct) {
    $exists = $true
    Write-Host "Storage account '$Name' already exists in '$Rg'." -ForegroundColor Green
  }
  if (-not $exists) {
    Write-Host "Creating storage account '$Name' in '$Rg' ($Loc, $Sku)..." -ForegroundColor Cyan
    az storage account create `
      --name $Name `
      --resource-group $Rg `
      --location $Loc `
      --sku $Sku `
      --kind StorageV2 `
      --allow-blob-public-access false `
      --https-only true `
      --min-tls-version TLS1_2 `
      --allow-shared-key-access true | Out-Null
  }

  Write-Host "Ensuring allowSharedKeyAccess is enabled..." -ForegroundColor Cyan
  $maxAttempts = 5
  $delaySeconds = 5
  $enabled = $false
  for ($i = 1; $i -le $maxAttempts; $i++) {
    az storage account update --name $Name --resource-group $Rg --allow-shared-key-access true | Out-Null
    $flag = az storage account show --name $Name --resource-group $Rg --query allowSharedKeyAccess -o tsv
    if ($flag -eq "True") {
      $enabled = $true
      break
    }
    Write-Host "allowSharedKeyAccess not yet enabled (attempt $i/$maxAttempts). Retrying in $delaySeconds sec..." -ForegroundColor Yellow
    Start-Sleep -Seconds $delaySeconds
  }
  if (-not $enabled) {
    throw "allowSharedKeyAccess is not enabled on '$Name' after $maxAttempts attempts. Enable it in portal/az or rerun."
  }
  Write-Host "allowSharedKeyAccess enabled on '$Name'." -ForegroundColor Green
}

function Ensure-Containers {
  param([string]$Name, [string]$Rg, [array]$Containers)
  foreach ($c in $Containers) {
    Write-Host "Creating container: $c" -ForegroundColor Cyan
    az storage container create --name $c --account-name $Name --resource-group $Rg --auth-mode login | Out-Null
  }
}

Ensure-AzCli
Ensure-ResourceGroup -Rg $ResourceGroup -Loc $Location
Ensure-StorageAccount -Name $StorageAccountName -Rg $ResourceGroup -Loc $Location -Sku $Sku
Ensure-Containers -Name $StorageAccountName -Rg $ResourceGroup -Containers $containers

Write-Host "Done. Containers: $($containers -join ', ')" -ForegroundColor Green
