# 给 idcheck 做本机信任：解除"网络来源"标记 + 自签代码签名证书
#
# SmartScreen 每次启动都拦，原因不是程序有毒，而是两点：
#   1. exe 从聊天/浏览器复制出来时带了 Zone.Identifier（"来自互联网"标记）；
#   2. 可执行文件没有代码签名，Windows 只能显示"发行者：未知"。
# 本脚本对"当前用户"生效，不改系统级设置，随时可撤销（见末尾注释）。
#
# 用法：
#   powershell -NoProfile -ExecutionPolicy Bypass -File tools\win_trust.ps1

param(
    [string]$DistDir = (Join-Path $PSScriptRoot '..\dist'),
    [string]$Subject = 'CN=idcheck local code signing, O=idcheck, C=CN'
)

$ErrorActionPreference = 'Stop'
$DistDir = (Resolve-Path $DistDir).Path
Write-Host "dist = $DistDir"

# ---------------------------------------------------------------- 1) 解除网络标记
$unblocked = 0
Get-ChildItem -Path $DistDir -Recurse -File | ForEach-Object {
    $zone = Get-Item -LiteralPath $_.FullName -Stream Zone.Identifier -ErrorAction SilentlyContinue
    if ($zone) {
        Unblock-File -LiteralPath $_.FullName
        $script:unblocked++
    }
}
Write-Host "已解除网络标记的文件数：$unblocked"
Get-ChildItem -Path $DistDir -Filter *.zip -File | ForEach-Object { Unblock-File -LiteralPath $_.FullName }

# ---------------------------------------------------------------- 2) 自签代码签名证书
$cert = Get-ChildItem Cert:\CurrentUser\My -CodeSigningCert | Where-Object { $_.Subject -eq $Subject } | Sort-Object NotAfter -Descending | Select-Object -First 1
if (-not $cert) {
    Write-Host '创建自签代码签名证书…'
    $params = @{
        Type               = 'CodeSigningCert'
        Subject            = $Subject
        KeyUsage           = 'DigitalSignature'
        KeyExportPolicy    = 'Exportable'
        CertStoreLocation  = 'Cert:\CurrentUser\My'
        NotAfter           = (Get-Date).AddYears(10)
        TextExtension      = @('2.5.29.37={text}1.3.6.1.5.5.7.3.3')
    }
    $cert = New-SelfSignedCertificate @params
} else {
    Write-Host "复用已有证书：$($cert.Thumbprint)"
}

$cerPath = Join-Path $DistDir 'idcheck-codesign.cer'
Export-Certificate -Cert $cert -FilePath $cerPath -Force | Out-Null
foreach ($store in @('Root', 'TrustedPublisher')) {
    $path = "Cert:\CurrentUser\$store"
    $already = Get-ChildItem $path | Where-Object { $_.Thumbprint -eq $cert.Thumbprint }
    if (-not $already) {
        Import-Certificate -FilePath $cerPath -CertStoreLocation $path | Out-Null
        Write-Host "已加入 CurrentUser\$store"
    } else {
        Write-Host "CurrentUser\$store 已有"
    }
}

# ---------------------------------------------------------------- 3) 签名
$targets = Get-ChildItem -Path $DistDir -Recurse -Filter *.exe -File | Where-Object { $_.Name -eq 'idcheck.exe' -or $_.Name -like 'idcheck-single*' }
foreach ($t in $targets) {
    $sig = Set-AuthenticodeSignature -FilePath $t.FullName -Certificate $cert -HashAlgorithm SHA256 -TimestampServer 'http://timestamp.digicert.com' -ErrorAction SilentlyContinue
    if (-not $sig -or $sig.Status -ne 'Valid') {
        $sig = Set-AuthenticodeSignature -FilePath $t.FullName -Certificate $cert -HashAlgorithm SHA256
    }
    Write-Host ("签名 {0} -> {1}" -f $t.Name, $sig.Status)
}

Write-Host ''
Write-Host '完成。撤销办法：'
Write-Host '  Get-ChildItem Cert:\CurrentUser\My,Cert:\CurrentUser\Root,Cert:\CurrentUser\TrustedPublisher | Where-Object { $_.Subject -like "*idcheck local code signing*" } | Remove-Item'
