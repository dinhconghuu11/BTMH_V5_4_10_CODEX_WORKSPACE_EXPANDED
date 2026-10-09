Set-StrictMode -Version 2.0

function Get-CampusFaceCurrentSid {
    return [System.Security.Principal.WindowsIdentity]::GetCurrent().User
}

function New-CampusFaceDirectorySecurity {
    param(
        [System.Security.Principal.SecurityIdentifier]$CurrentSid,
        [switch]$IncludeNetworkService
    )
    $sec = New-Object System.Security.AccessControl.DirectorySecurity
    $sec.SetOwner($CurrentSid)
    $sec.SetAccessRuleProtection($true, $false)

    $inherit = [System.Security.AccessControl.InheritanceFlags]::ContainerInherit -bor [System.Security.AccessControl.InheritanceFlags]::ObjectInherit
    $prop = [System.Security.AccessControl.PropagationFlags]::None
    $allow = [System.Security.AccessControl.AccessControlType]::Allow
    $full = [System.Security.AccessControl.FileSystemRights]::FullControl
    $modify = [System.Security.AccessControl.FileSystemRights]::Modify

    $sids = @(
        (New-Object System.Security.Principal.SecurityIdentifier('S-1-5-18')),       # SYSTEM
        (New-Object System.Security.Principal.SecurityIdentifier('S-1-5-32-544')),  # Administrators
        $CurrentSid
    )
    foreach($sid in $sids){
        $rule = New-Object System.Security.AccessControl.FileSystemAccessRule($sid, $full, $inherit, $prop, $allow)
        [void]$sec.AddAccessRule($rule)
    }
    if($IncludeNetworkService){
        $ns = New-Object System.Security.Principal.SecurityIdentifier('S-1-5-20')
        $rule = New-Object System.Security.AccessControl.FileSystemAccessRule($ns, $modify, $inherit, $prop, $allow)
        [void]$sec.AddAccessRule($rule)
    }
    return $sec
}

function New-CampusFaceFileSecurity {
    param(
        [System.Security.Principal.SecurityIdentifier]$CurrentSid,
        [switch]$IncludeNetworkService
    )
    $sec = New-Object System.Security.AccessControl.FileSecurity
    $sec.SetOwner($CurrentSid)
    $sec.SetAccessRuleProtection($true, $false)

    $inherit = [System.Security.AccessControl.InheritanceFlags]::None
    $prop = [System.Security.AccessControl.PropagationFlags]::None
    $allow = [System.Security.AccessControl.AccessControlType]::Allow
    $full = [System.Security.AccessControl.FileSystemRights]::FullControl
    $modify = [System.Security.AccessControl.FileSystemRights]::Modify

    $sids = @(
        (New-Object System.Security.Principal.SecurityIdentifier('S-1-5-18')),
        (New-Object System.Security.Principal.SecurityIdentifier('S-1-5-32-544')),
        $CurrentSid
    )
    foreach($sid in $sids){
        $rule = New-Object System.Security.AccessControl.FileSystemAccessRule($sid, $full, $inherit, $prop, $allow)
        [void]$sec.AddAccessRule($rule)
    }
    if($IncludeNetworkService){
        $ns = New-Object System.Security.Principal.SecurityIdentifier('S-1-5-20')
        $rule = New-Object System.Security.AccessControl.FileSystemAccessRule($ns, $modify, $inherit, $prop, $allow)
        [void]$sec.AddAccessRule($rule)
    }
    return $sec
}

function Set-CampusFacePathAcl {
    param(
        [Parameter(Mandatory=$true)][string]$Path,
        [switch]$Recursive,
        [switch]$IncludeNetworkService
    )
    $currentSid = Get-CampusFaceCurrentSid

    if(-not (Test-Path -LiteralPath $Path)){
        New-Item -ItemType Directory -Force -Path $Path | Out-Null
    }

    $dirSec = New-CampusFaceDirectorySecurity -CurrentSid $currentSid -IncludeNetworkService:$IncludeNetworkService
    [System.IO.Directory]::SetAccessControl($Path, $dirSec)

    if(-not $Recursive){ return }

    # Replace stale protected/deny ACLs left by older installers. Reparse points are skipped.
    $items = Get-ChildItem -LiteralPath $Path -Force -Recurse -ErrorAction Stop
    foreach($item in $items){
        if(($item.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0){ continue }
        try {
            if($item.PSIsContainer){
                $s = New-CampusFaceDirectorySecurity -CurrentSid $currentSid -IncludeNetworkService:$IncludeNetworkService
                [System.IO.Directory]::SetAccessControl($item.FullName, $s)
            } else {
                $s = New-CampusFaceFileSecurity -CurrentSid $currentSid -IncludeNetworkService:$IncludeNetworkService
                [System.IO.File]::SetAccessControl($item.FullName, $s)
            }
        } catch {
            throw "ACL repair failed for '$($item.FullName)': $($_.Exception.Message)"
        }
    }
}

function Test-CampusFaceDirectoryIo {
    param([Parameter(Mandatory=$true)][string]$Path)
    New-Item -ItemType Directory -Force -Path $Path | Out-Null
    $id=[guid]::NewGuid().ToString('N')
    $a=Join-Path $Path ("cf-io-$id.tmp")
    $b="$a.renamed"
    [System.IO.File]::WriteAllText($a,'CampusFace ACL OK',[System.Text.Encoding]::UTF8)
    $txt=[System.IO.File]::ReadAllText($a,[System.Text.Encoding]::UTF8).Trim([char]0xFEFF).Trim()
    if($txt -ne 'CampusFace ACL OK'){ throw "Read/write verification failed for $Path" }
    Move-Item -LiteralPath $a -Destination $b -Force
    Remove-Item -LiteralPath $b -Force
}
