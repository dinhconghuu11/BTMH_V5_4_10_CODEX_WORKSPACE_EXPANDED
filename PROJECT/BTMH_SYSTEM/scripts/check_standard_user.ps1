$ErrorActionPreference = 'Stop'
try {
  $principal = New-Object Security.Principal.WindowsPrincipal([Security.Principal.WindowsIdentity]::GetCurrent())
  if ($principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Write-Host '[CANH BAO] Khong chay BTMH bang Run as administrator.'
    Write-Host 'Dong cua so nay va nhap dup file BAT bang tai khoan Windows thong thuong.'
    Write-Host 'PostgreSQL cuc bo khong chap nhan tien trinh co quyen quan tri.'
    exit 5
  }
  exit 0
} catch {
  Write-Host '[ERROR] Khong kiem tra duoc quyen Windows. Dung de bao ve qua trinh cai dat.'
  exit 6
}
