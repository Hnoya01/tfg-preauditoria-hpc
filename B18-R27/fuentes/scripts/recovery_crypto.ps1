param(
 [Parameter(Mandatory)][ValidateSet('Encrypt','Decrypt')][string]$Mode,
 [Parameter(Mandatory)][string]$InputFile,
 [Parameter(Mandatory)][string]$OutputFile,
 [Parameter(Mandatory)][string]$KeyFile
)
$ErrorActionPreference='Stop'
if (-not [System.Security.Cryptography.AesGcm]::IsSupported) {throw 'AES-GCM no disponible en este entorno'}
if (Test-Path -LiteralPath $OutputFile) {throw 'No se reemplaza una salida existente'}
$magic=[System.Text.Encoding]::ASCII.GetBytes('TFGREC01')
$aes=$null
try {
 if ($Mode -eq 'Encrypt') {
  if (Test-Path -LiteralPath $KeyFile) {throw 'No se reemplaza una clave existente'}
  $key=[System.Security.Cryptography.RandomNumberGenerator]::GetBytes(32)
  $keyStream=[System.IO.File]::Open($KeyFile,[System.IO.FileMode]::CreateNew)
  try {$keyStream.Write($key);$keyStream.Flush($true)} finally {$keyStream.Dispose()}
  $plain=[System.IO.File]::ReadAllBytes($InputFile)
  $nonce=[System.Security.Cryptography.RandomNumberGenerator]::GetBytes(12)
  $cipher=[byte[]]::new($plain.Length);$tag=[byte[]]::new(16)
  $aes=[System.Security.Cryptography.AesGcm]::new($key,16)
  $aes.Encrypt($nonce,$plain,$cipher,$tag,$magic)
  $output=[System.IO.File]::Open($OutputFile,[System.IO.FileMode]::CreateNew)
  try {$output.Write($magic);$output.Write($nonce);$output.Write($tag);$output.Write($cipher);$output.Flush($true)} finally {$output.Dispose()}
 } else {
  $key=[System.IO.File]::ReadAllBytes($KeyFile)
  $envelope=[System.IO.File]::ReadAllBytes($InputFile)
  if ($key.Length -ne 32 -or $envelope.Length -lt 37 -or [System.Text.Encoding]::ASCII.GetString($envelope,0,8) -ne 'TFGREC01') {throw 'Formato de copia cifrada inválido'}
  [byte[]]$nonce=$envelope[8..19];[byte[]]$tag=$envelope[20..35];[byte[]]$cipher=$envelope[36..($envelope.Length-1)]
  $plain=[byte[]]::new($cipher.Length)
  $aes=[System.Security.Cryptography.AesGcm]::new($key,16)
  $aes.Decrypt($nonce,$cipher,$tag,$plain,$magic)
  $output=[System.IO.File]::Open($OutputFile,[System.IO.FileMode]::CreateNew)
  try {$output.Write($plain);$output.Flush($true)} finally {$output.Dispose()}
 }
 Write-Output ('AES-256-GCM '+$Mode+': OK')
} catch {throw 'La copia cifrada no pudo crearse o autenticarse; no usar su salida como recuperación válida.'}
finally {if ($aes) {$aes.Dispose()};if ($key) {[System.Array]::Clear($key,0,$key.Length)}}
