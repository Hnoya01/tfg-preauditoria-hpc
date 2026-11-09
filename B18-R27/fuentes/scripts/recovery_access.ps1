param(
 [Parameter(Mandatory)][ValidateSet('Prepare','PrepareKey','Snapshot','Apply','Verify')][string]$Mode,
 [string]$SourceRoot,
 [Parameter(Mandatory)][string]$TargetRoot,
 [string]$Report
)
$ErrorActionPreference='Stop'
function Rules($acl) {
 @($acl.GetAccessRules($true,$true,[System.Security.Principal.SecurityIdentifier]) | ForEach-Object {
  '{0}|{1}|{2}|{3}|{4}' -f $_.IdentityReference.Value,[int64]$_.FileSystemRights,$_.AccessControlType,[int]$_.InheritanceFlags,[int]$_.PropagationFlags
 } | Sort-Object)
}
function Record($path) {
 $acl=Get-Acl -LiteralPath $path
 @{sddl=$acl.GetSecurityDescriptorSddlForm([System.Security.AccessControl.AccessControlSections]::Access);
   owner=$acl.GetOwner([System.Security.Principal.SecurityIdentifier]).Value;rules=@(Rules $acl)}
}
function FreezeAcl($path,$record) {
 $node=Get-Item -LiteralPath $path
 $acl=if ($node.PSIsContainer) {[System.Security.AccessControl.DirectorySecurity]::new()} else {[System.Security.AccessControl.FileSecurity]::new()}
 $acl.SetSecurityDescriptorSddlForm($record.sddl,[System.Security.AccessControl.AccessControlSections]::Access)
 $acl.SetAccessRuleProtection($true,$true)
 if ($node.PSIsContainer) {[System.IO.FileSystemAclExtensions]::SetAccessControl([System.IO.DirectoryInfo]$node,$acl)}
 else {[System.IO.FileSystemAclExtensions]::SetAccessControl([System.IO.FileInfo]$node,$acl)}
}
function NodePath($root,$relative) {
 if ($relative -eq '.') {return $root}
 if ([System.IO.Path]::IsPathRooted($relative) -or ($relative -split '[/\\]') -contains '..') {throw 'Localizador ACL inválido'}
 $path=[System.IO.Path]::GetFullPath((Join-Path $root $relative))
 if (-not $path.StartsWith($root+[System.IO.Path]::DirectorySeparatorChar,[System.StringComparison]::OrdinalIgnoreCase)) {throw 'ACL fuera de la carpeta objetivo'}
 if ((Get-Item -LiteralPath $path).Attributes -band [System.IO.FileAttributes]::ReparsePoint) {throw 'No se admiten enlaces en la recuperación'}
 return $path
}
$target=[System.IO.Path]::GetFullPath($TargetRoot).TrimEnd('\','/')
if ($Mode -eq 'PrepareKey') {
 if (@(Get-ChildItem -LiteralPath $target -Force).Count) {throw 'La carpeta de claves debe estar vacía'}
 $acl=[System.Security.AccessControl.DirectorySecurity]::new()
 $acl.SetAccessRuleProtection($true,$false)
 $identities=@([System.Security.Principal.WindowsIdentity]::GetCurrent().User.Value,'S-1-5-18','S-1-5-32-544') | Select-Object -Unique
 foreach ($identity in $identities) {
  $rule=[System.Security.AccessControl.FileSystemAccessRule]::new([System.Security.Principal.SecurityIdentifier]::new($identity),
   [System.Security.AccessControl.FileSystemRights]::FullControl,
   [System.Security.AccessControl.InheritanceFlags]::ContainerInherit -bor [System.Security.AccessControl.InheritanceFlags]::ObjectInherit,
   [System.Security.AccessControl.PropagationFlags]::None,[System.Security.AccessControl.AccessControlType]::Allow)
  $acl.AddAccessRule($rule)
 }
 [System.IO.FileSystemAclExtensions]::SetAccessControl([System.IO.DirectoryInfo]::new($target),$acl)
 $actual=Get-Acl -LiteralPath $target
 $actualIds=@($actual.GetAccessRules($true,$true,[System.Security.Principal.SecurityIdentifier]) | ForEach-Object {$_.IdentityReference.Value} | Sort-Object -Unique)
 if (-not $actual.AreAccessRulesProtected -or (Compare-Object @($identities | Sort-Object) $actualIds)) {throw 'Custodia de claves no restringida'}
 Write-Output 'Clave restringida al usuario actual, SYSTEM y administradores';exit
}
if ($Mode -eq 'Prepare') {
 if (@(Get-ChildItem -LiteralPath $target -Force).Count) {throw 'La carpeta privada debe estar vacía'}
 FreezeAcl $target (Record ([System.IO.Path]::GetFullPath($SourceRoot)))
 Write-Output 'DACL privada preparada';exit
}
if ($Mode -eq 'Snapshot') {
 $records=@{'.'=(Record $target)}
 foreach ($path in (Get-Content -LiteralPath $Report -Raw | ConvertFrom-Json).paths) {
  $node=NodePath $target $path
  $records[$path]=Record $node
 }
 $records | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $Report -Encoding utf8NoBOM
 Write-Output ('Permisos registrados: '+$records.Count);exit
}
$records=Get-Content -LiteralPath $Report -Raw | ConvertFrom-Json -AsHashtable
foreach ($relative in @($records.Keys | Sort-Object {$_.Length}, {$_})) {
 $path=NodePath $target $relative
 if ($Mode -eq 'Apply') {FreezeAcl $path $records[$relative]}
 $actual=Record $path
 if ($actual.owner -ne $records[$relative].owner -or (Compare-Object @($actual.rules) @($records[$relative].rules))) {throw 'Permisos restaurados diferentes del respaldo'}
 if (-not (Get-Acl -LiteralPath $path).AreAccessRulesProtected) {throw 'Permisos restaurados con herencia no fijada'}
}
Write-Output ('Permisos verificados sin ampliación: '+$records.Count)
