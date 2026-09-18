@echo off
setlocal DisableDelayedExpansion
set "PHAMU_INSTALLER_SELF=%~f0"
set "PHAMU_INSTALLER_PARENT=%~dp0"
powershell.exe -NoLogo -NoProfile -Command "$ErrorActionPreference='Stop'; try { $s=[IO.File]::ReadAllText($env:PHAMU_INSTALLER_SELF,[Text.Encoding]::UTF8); $m='#===PHAMU_POWERSHELL==='; & ([ScriptBlock]::Create($s.Substring($s.LastIndexOf($m)+$m.Length))) } catch { Write-Host $_ -ForegroundColor Red; exit 1 }"
set "PHAMU_INSTALLER_EXIT=%ERRORLEVEL%"
if not "%PHAMU_INSTALLER_NO_PAUSE%"=="1" pause
exit /b %PHAMU_INSTALLER_EXIT%
#===PHAMU_POWERSHELL===
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = New-Object Text.UTF8Encoding($false)
# Resolve the inbox modules from this Windows PowerShell, not an inherited
# PowerShell 7 or embedding host's PSModulePath. No machine/user settings change.
Import-Module (Join-Path $PSHOME 'Modules\Microsoft.PowerShell.Utility\Microsoft.PowerShell.Utility.psd1') -ErrorAction Stop
Import-Module (Join-Path $PSHOME 'Modules\Microsoft.PowerShell.Archive\Microsoft.PowerShell.Archive.psd1') -ErrorAction Stop
$Release = @'
{
  "schema": 1,
  "version": "b1.0",
  "root": "RVC_Client_Phamu_Edition",
  "base_url": "https://github.com/Phamu-Ham/RVC-Client-Phamu-Edition/releases/download/b1.0/",
  "zip_name": "RVC_Client_Phamu_Edition.zip",
  "zip_bytes": 3637897035,
  "zip_sha256": "942f6b3125e38b7bdbe785514974c19be5ffc7677d240072e26edf615914024b",
  "unpacked_bytes": 6130618391,
  "parts": [
    {
      "name": "RVC_Client_Phamu_Edition.zip.001",
      "bytes": 1900000000,
      "sha256": "d45742c224d6098ab3ff19ffefd5adad0839fcb068f65377603e0e571243c286"
    },
    {
      "name": "RVC_Client_Phamu_Edition.zip.002",
      "bytes": 1737897035,
      "sha256": "a72a882f6bb4dfb88f5f4e8d403bfb6385d3b2a99980861efb50879c05fd8cd5"
    }
  ]
}
'@ | ConvertFrom-Json

function Assert-ChildPath([string]$Parent, [string]$Child) {
    $prefix = [IO.Path]::GetFullPath($Parent).TrimEnd('\') + '\'
    $full = [IO.Path]::GetFullPath($Child)
    if (!$full.StartsWith($prefix, [StringComparison]::OrdinalIgnoreCase)) {
        throw '安全でない保存先のため停止しました。'
    }
    return $full
}

function Assert-NoReparse([string]$Path) {
    $current = [IO.Path]::GetFullPath($Path)
    while ($current) {
        if ([IO.File]::Exists($current) -or [IO.Directory]::Exists($current)) {
            if (([IO.File]::GetAttributes($current) -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
                throw 'リンク経由の保存先は使えません。通常のローカルフォルダへバッチを置いてください。'
            }
        }
        $current = [IO.Path]::GetDirectoryName($current)
    }
}

function Test-Artifact([string]$Path, [long]$Bytes, [string]$Hash) {
    Assert-NoReparse $Path
    if (![IO.File]::Exists($Path)) { return $false }
    if ((Get-Item -LiteralPath $Path).Length -ne $Bytes) { return $false }
    return (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash -eq $Hash
}

function Send-CacheToRecycleBin([string]$Parent, [string]$Path, [string]$Owner) {
    $safe = Assert-ChildPath $Parent $Path
    Assert-NoReparse $safe
    if ([IO.File]::ReadAllText((Join-Path $safe 'owner.txt')) -ne $Owner) {
        throw '一時フォルダの所有確認に失敗しました。削除しません。'
    }
    Add-Type -AssemblyName Microsoft.VisualBasic
    [Microsoft.VisualBasic.FileIO.FileSystem]::DeleteDirectory(
        $safe, [Microsoft.VisualBasic.FileIO.UIOption]::OnlyErrorDialogs,
        [Microsoft.VisualBasic.FileIO.RecycleOption]::SendToRecycleBin)
}

function Receive-Artifact([string]$Url, [string]$Path, [long]$ExpectedBytes) {
    $uri = [Uri]$Url
    if ($uri.Scheme -ne 'https' -or $uri.Host -ne 'github.com') { throw '取得先がGitHub HTTPSではありません。' }
    Assert-NoReparse $Path
    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
    $request = [Net.HttpWebRequest]::Create($uri)
    $request.UserAgent = 'Phamu-Installer/1.0'
    $request.Timeout = 30000
    $request.ReadWriteTimeout = 60000
    $request.AllowAutoRedirect = $true
    $request.UseDefaultCredentials = $false
    $response = $null; $inputStream = $null; $outputStream = $null
    try {
        $response = $request.GetResponse()
        $hostName = $response.ResponseUri.Host
        if ($response.ResponseUri.Scheme -ne 'https' -or
            !($hostName -eq 'github.com' -or $hostName.EndsWith('.githubusercontent.com'))) {
            throw '想定外のダウンロード先へ転送されたため停止しました。'
        }
        $inputStream = $response.GetResponseStream()
        $outputStream = [IO.File]::Open($Path, [IO.FileMode]::Create, [IO.FileAccess]::Write, [IO.FileShare]::None)
        $buffer = New-Object byte[] (1024 * 1024)
        [long]$received = 0
        $timer = [Diagnostics.Stopwatch]::StartNew()
        while (($count = $inputStream.Read($buffer, 0, $buffer.Length)) -gt 0) {
            $received += $count
            if ($received -gt $ExpectedBytes) { throw 'ダウンロードサイズが想定を超えました。' }
            $outputStream.Write($buffer, 0, $count)
            if ($timer.ElapsedMilliseconds -ge 500) {
                Write-Progress -Activity 'クライアントをダウンロード中' -Status ('{0:N0} / {1:N0} MB' -f ($received/1MB), ($ExpectedBytes/1MB)) -PercentComplete ([int](100*$received/$ExpectedBytes))
                $timer.Restart()
            }
        }
        if ($received -ne $ExpectedBytes) { throw 'ダウンロードが途中で終了しました。' }
    } finally {
        if ($outputStream) { $outputStream.Dispose() }
        if ($inputStream) { $inputStream.Dispose() }
        if ($response) { $response.Dispose() }
        Write-Progress -Activity 'クライアントをダウンロード中' -Completed
    }
}

function Assert-Release($Config) {
    if ($Config.schema -ne 1 -or $Config.root -ne 'RVC_Client_Phamu_Edition' -or
        $Config.zip_name -ne ($Config.root + '.zip') -or $Config.zip_sha256 -notmatch '^[a-f0-9]{64}$') {
        throw '配布情報の形式が不正です。'
    }
    $base = [Uri]$Config.base_url
    if ($base.Scheme -ne 'https' -or $base.Host -ne 'github.com' -or
        $base.AbsolutePath -notmatch '^/Phamu-Ham/RVC-Client-Phamu-Edition/releases/download/[^/]+/$' -or
        $base.Query -or $base.Fragment -or $base.UserInfo) { throw '配布先の設定が不正です。' }
    [long]$total = 0; $number = 0
    foreach ($part in $Config.parts) {
        $number++
        if ($part.name -ne ('{0}.{1:D3}' -f $Config.zip_name, $number) -or
            $part.sha256 -notmatch '^[a-f0-9]{64}$' -or $part.bytes -le 0 -or $part.bytes -ge 2GB) {
            throw '分割データの設定が不正です。'
        }
        $total += $part.bytes
    }
    if ($number -lt 1 -or $total -ne $Config.zip_bytes -or $Config.unpacked_bytes -le 0) { throw '配布サイズが不正です。' }
}

function Invoke-PhamuInstall($Config, [string]$Parent) {
    Assert-Release $Config
    $parentPath = [IO.Path]::GetFullPath($Parent)
    Assert-NoReparse $parentPath
    if (![IO.Directory]::Exists($parentPath)) { throw 'バッチの保存先フォルダが見つかりません。' }
    $target = Assert-ChildPath $parentPath (Join-Path $parentPath $Config.root)
    Assert-NoReparse $target
    if (Test-Path -LiteralPath $target) {
        if ([IO.File]::Exists((Join-Path $target '起動.lnk')) -and
            [IO.File]::Exists((Join-Path $target '本体\runtime\python.exe'))) {
            Write-Host "配置済みです。既存のモデル・画像・設定は上書きしません。`n$target\起動.lnk"
            return
        }
        throw '同名のファイル／フォルダが既にあります。安全のため上書きしません。'
    }
    $cache = Assert-ChildPath $parentPath (Join-Path $parentPath ('.Phamu-setup-' + $Config.zip_sha256.Substring(0,16)))
    $owner = 'phamu-installer-v1:' + $Config.zip_sha256
    Assert-NoReparse $cache
    if (Test-Path -LiteralPath $cache) {
        $marker = Join-Path $cache 'owner.txt'
        Assert-NoReparse $marker
        if (![IO.File]::Exists($marker) -or [IO.File]::ReadAllText($marker) -ne $owner) {
            throw '同名の一時フォルダが存在します。安全のため使用しません。'
        }
    } else {
        [void][IO.Directory]::CreateDirectory($cache)
        [IO.File]::WriteAllText((Join-Path $cache 'owner.txt'), $owner)
    }
    $lockPath = Join-Path $cache 'install.lock'
    Assert-NoReparse $lockPath
    $lock = [IO.File]::Open($lockPath, [IO.FileMode]::OpenOrCreate, [IO.FileAccess]::ReadWrite, [IO.FileShare]::None)
    $completed = $false
    try {
        $drive = New-Object IO.DriveInfo([IO.Path]::GetPathRoot($parentPath))
        [long]$required = 2 * $Config.zip_bytes + $Config.unpacked_bytes + 512MB
        if ($drive.AvailableFreeSpace -lt $required) { throw ('空き容量が不足しています。約{0:N1} GB以上必要です。' -f ($required/1GB)) }
        Write-Host ('RVC Client -Phamu''s Edition- {0}' -f $Config.version) -ForegroundColor Cyan
        Write-Host "配置先: $target"
        Write-Host '監査済みの実行環境を取得します。Git・Pythonの追加インストールは不要です。'
        $parts = @()
        foreach ($part in $Config.parts) {
            $path = Assert-ChildPath $cache (Join-Path $cache $part.name)
            if (!(Test-Artifact $path $part.bytes $part.sha256)) {
                if (Test-Path -LiteralPath $path) {
                    $quarantine = Assert-ChildPath $cache ($path + '.invalid-' + [Guid]::NewGuid().ToString('N'))
                    [IO.File]::Move($path, $quarantine)
                }
                $temporary = Assert-ChildPath $cache ($path + '.download')
                for ($attempt=1; $attempt -le 3; $attempt++) {
                    try {
                        Write-Host ('取得中: {0}（試行{1}/3）' -f $part.name, $attempt)
                        Receive-Artifact ($Config.base_url + $part.name) $temporary $part.bytes
                        if (!(Test-Artifact $temporary $part.bytes $part.sha256)) { throw 'データのハッシュが一致しません。' }
                        [IO.File]::Move($temporary, $path)
                        break
                    } catch {
                        if ($attempt -eq 3) { throw }
                        Start-Sleep -Seconds 2
                    }
                }
            } else { Write-Host ('確認済みデータを再利用: ' + $part.name) }
            $parts += $path
        }
        $zip = Assert-ChildPath $cache (Join-Path $cache $Config.zip_name)
        if (!(Test-Artifact $zip $Config.zip_bytes $Config.zip_sha256)) {
            Write-Host '分割データを結合・検証しています…'
            $stream = [IO.File]::Open($zip, [IO.FileMode]::Create, [IO.FileAccess]::Write, [IO.FileShare]::None)
            try {
                foreach ($partPath in $parts) {
                    $inputPart = [IO.File]::OpenRead($partPath)
                    try { $inputPart.CopyTo($stream) } finally { $inputPart.Dispose() }
                }
            } finally { $stream.Dispose() }
            if (!(Test-Artifact $zip $Config.zip_bytes $Config.zip_sha256)) { throw '結合後のZIPのハッシュが一致しません。' }
        }
        Add-Type -AssemblyName System.IO.Compression.FileSystem
        $archive = [IO.Compression.ZipFile]::OpenRead($zip)
        try {
            $names = New-Object 'Collections.Generic.HashSet[string]' ([StringComparer]::OrdinalIgnoreCase)
            [long]$expanded = 0
            foreach ($entry in $archive.Entries) {
                $name = $entry.FullName.Replace('\','/')
                $segments = $name.TrimEnd('/').Split('/')
                if ($segments[0] -ne $Config.root -or $segments -contains '..' -or $segments -contains '.' -or
                    $segments -contains '' -or $name.Contains(':') -or !$names.Add($name) -or
                    (($entry.ExternalAttributes -shr 16) -band 0xF000) -eq 0xA000) { throw 'ZIP内に想定外のパスがあります。' }
                $expanded += $entry.Length
            }
            if ($expanded -ne $Config.unpacked_bytes) { throw '展開後サイズが一致しません。' }
        } finally { $archive.Dispose() }
        $stage = Assert-ChildPath $cache (Join-Path $cache ('expand-' + [Guid]::NewGuid().ToString('N')))
        Write-Host '展開しています。ファイル数が多いため、しばらくお待ちください…'
        $savedProgress = $ProgressPreference
        try {
            $ProgressPreference = 'SilentlyContinue'
            Expand-Archive -LiteralPath $zip -DestinationPath $stage
        } finally { $ProgressPreference = $savedProgress }
        $stagedRoot = Assert-ChildPath $stage (Join-Path $stage $Config.root)
        $expectedTop = @('本体','起動.lnk','モデル（pth）を入れる.lnk','Indexを入れる.lnk')
        $actualTop = @(Get-ChildItem -LiteralPath $stagedRoot -Force | ForEach-Object {$_.Name})
        if (Compare-Object $expectedTop $actualTop) { throw '展開されたフォルダ構成が一致しません。' }
        if (![IO.File]::Exists((Join-Path $stagedRoot '本体\runtime\python.exe'))) { throw '実行環境が不足しています。' }
        $stagedRoot = Assert-ChildPath $cache $stagedRoot
        Assert-NoReparse $stagedRoot
        Assert-NoReparse $target
        if (Test-Path -LiteralPath $target) { throw 'インストール中に保存先が作成されました。上書きせず停止します。' }
        [IO.Directory]::Move($stagedRoot, $target)
        $completed = $true
    } finally { $lock.Dispose() }
    if ($completed) {
        try { Send-CacheToRecycleBin $parentPath $cache $owner }
        catch { Write-Host "導入は完了しました。一時データは手動で片付けられます: $cache" -ForegroundColor Yellow }
        Write-Host "`nインストール完了。次の「起動」ショートカットから使えます。`n$target\起動.lnk" -ForegroundColor Green
    }
}

try {
    Invoke-PhamuInstall $Release $env:PHAMU_INSTALLER_PARENT
    exit 0
} catch {
    Write-Host "`nインストールできませんでした。" -ForegroundColor Red
    Write-Host $_.Exception.Message -ForegroundColor Red
    Write-Host '通信失敗の場合は、接続を確認して同じバッチを再実行してください。検証済みの分割データは再利用します。'
    Write-Host 'このバッチは既存のクライアントや個人設定を上書きしません。'
    exit 1
}
