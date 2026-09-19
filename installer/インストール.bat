@echo off
setlocal DisableDelayedExpansion
chcp 65001 >nul
echo インストーラーを起動中… しばらくお待ちください。
set "PHAMU_INSTALLER_SELF=%~f0"
set "PHAMU_INSTALLER_PARENT=%~dp0"
powershell.exe -NoLogo -NoProfile -Command "$ErrorActionPreference='Stop'; try { $s=[IO.File]::ReadAllText($env:PHAMU_INSTALLER_SELF,[Text.Encoding]::UTF8); $m='#===PHAMU_POWERSHELL==='; & ([ScriptBlock]::Create($s.Substring($s.LastIndexOf($m)+$m.Length))) } catch { Write-Host $_ -ForegroundColor Red; exit 1 }"
set "PHAMU_INSTALLER_EXIT=%ERRORLEVEL%"
if not "%PHAMU_INSTALLER_NO_PAUSE%"=="1" pause
exit /b %PHAMU_INSTALLER_EXIT%
#===PHAMU_POWERSHELL===
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
$script:InstallLog = $null
$script:InstallLogBytes = 0
$script:InstallLogLimit = 1MB
[Console]::OutputEncoding = New-Object Text.UTF8Encoding($false)
# Resolve the inbox modules from this Windows PowerShell, not an inherited
# PowerShell 7 or embedding host's PSModulePath. No machine/user settings change.
Import-Module (Join-Path $PSHOME 'Modules\Microsoft.PowerShell.Utility\Microsoft.PowerShell.Utility.psd1') -ErrorAction Stop
Import-Module (Join-Path $PSHOME 'Modules\Microsoft.PowerShell.Archive\Microsoft.PowerShell.Archive.psd1') -ErrorAction Stop
$Release = @'
{
  "schema": 1,
  "version": "b1.1",
  "root": "RVC_Client_Phamu_Edition",
  "base_url": "https://github.com/Phamu-Ham/RVC-Client-Phamu-Edition/releases/download/b1.1/",
  "zip_name": "RVC_Client_Phamu_Edition.zip",
  "zip_bytes": 3610895254,
  "zip_sha256": "4f4c9a6ef8abb05bb3b2cc2ec023b5d57402f4e9657c00feaf8d25b63cad176f",
  "unpacked_bytes": 6130638375,
  "parts": [
    {
      "name": "RVC_Client_Phamu_Edition.zip.001",
      "bytes": 1900000000,
      "sha256": "13646586769792040195c530f97453bd17ffbb26da5f44d1241bf7b3dc82f473"
    },
    {
      "name": "RVC_Client_Phamu_Edition.zip.002",
      "bytes": 1710895254,
      "sha256": "2943eac6b2b3588713c0c2f959b49148e781d0dc4254dbd75eb45d189416f639"
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

function Protect-LogText([string]$Text) {
    $Text = [regex]::Replace($Text, '(?i)https?://[^\s"''<>]+', '<URL>')
    $Text = [regex]::Replace($Text, '(?i)"(?:[a-z]:[\\/]|\\\\)[^"\r\n]*"', '"<PATH>"')
    $Text = [regex]::Replace($Text, '(?i)(?:[a-z]:[\\/]|\\\\)[^\r\n"''<>|]*', '<PATH>')
    $Text = [regex]::Replace($Text, '[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}', '<EMAIL>')
    $Text = [regex]::Replace($Text, '(?i)\b(token|password|secret|api[_-]?key|authorization)\b\s*[:=]\s*[^\r\n]+', '$1=<REDACTED>')
    foreach ($identity in @($env:USERNAME, $env:COMPUTERNAME)) {
        if ($identity -and $identity.Length -ge 3) {
            $Text = [regex]::Replace($Text, '(?i)(?<!\w)' + [regex]::Escape($identity) + '(?!\w)', '<USER>')
        }
    }
    return $Text
}

function Initialize-InstallLog([string]$Parent) {
    $script:InstallLog = $null
    $script:InstallLogBytes = 0
    $script:InstallLogLimit = 1MB
    $script:InstallLogPath = $null
    try {
        $folder = Assert-ChildPath $Parent (Join-Path $Parent 'Phamu-Installer-Logs')
        Assert-NoReparse $folder
        [void][IO.Directory]::CreateDirectory($folder)
        $name = 'installer-' + (Get-Date -Format 'yyyyMMdd-HHmmssfff') + '-' + [Guid]::NewGuid().ToString('N').Substring(0,8) + '.log'
        $path = Assert-ChildPath $folder (Join-Path $folder $name)
        $stream = [IO.File]::Open($path, [IO.FileMode]::CreateNew, [IO.FileAccess]::Write, [IO.FileShare]::Read)
        $script:InstallLog = New-Object IO.StreamWriter($stream, (New-Object Text.UTF8Encoding($false)))
        $script:InstallLog.AutoFlush = $true
        $script:InstallLogPath = $path
        # Recycle only our own exact log names; leave other files and active logs alone.
        $old = @(Get-ChildItem -LiteralPath $folder -File | Where-Object {
            $_.Name -match '^installer-\d{8}-\d{9}-[0-9a-f]{8}\.log$'
        } | Sort-Object Name -Descending | Select-Object -Skip 8)
        foreach ($file in $old) {
            try {
                $safe = Assert-ChildPath $folder $file.FullName
                Assert-NoReparse $safe
                Add-Type -AssemblyName Microsoft.VisualBasic
                [Microsoft.VisualBasic.FileIO.FileSystem]::DeleteFile($safe,
                    [Microsoft.VisualBasic.FileIO.UIOption]::OnlyErrorDialogs,
                    [Microsoft.VisualBasic.FileIO.RecycleOption]::SendToRecycleBin)
            } catch { } # Never force-delete a locked/inaccessible diagnostic file.
        }
    } catch {
        Write-Host 'ログを保存できません。エラーが出た場合は画面の内容を控えてください。' -ForegroundColor Yellow
    }
}

function Write-InstallMessage([string]$Message, [ConsoleColor]$ForegroundColor = [ConsoleColor]::Gray) {
    Write-Host $Message -ForegroundColor $ForegroundColor
    if ($script:InstallLog) {
        try {
            $line = '[' + (Get-Date -Format 'yyyy-MM-ddTHH:mm:ss') + '] ' + (Protect-LogText $Message)
            $bytes = [Text.Encoding]::UTF8.GetByteCount($line + "`r`n")
            if ($script:InstallLogBytes + $bytes -le $script:InstallLogLimit - 128) {
                $script:InstallLog.WriteLine($line)
                $script:InstallLogBytes += $bytes
            } elseif ($script:InstallLogBytes -lt $script:InstallLogLimit) {
                $script:InstallLog.WriteLine('[support] Log size limit reached; further messages omitted.')
                $script:InstallLogBytes = $script:InstallLogLimit
            }
        } catch { } # Failure to write a support log must not corrupt installation.
    }
}

function Write-DownloadProgress([long]$Received, [long]$Total, [int]$LastPercent, [long]$ElapsedMs) {
    $percent = [int][Math]::Floor(100 * $Received / $Total)
    # Append-only lines: no cursor movement, repainting, or native progress overlay.
    if ($percent -ge $LastPercent + 10 -or $ElapsedMs -ge 15000 -or $Received -eq $Total) {
        Write-InstallMessage ('ダウンロード: {0}% ({1:N0} / {2:N0} MB)' -f $percent, ($Received/1MB), ($Total/1MB))
        return $percent
    }
    return -1
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
        $lastPercent = 0
        while (($count = $inputStream.Read($buffer, 0, $buffer.Length)) -gt 0) {
            $received += $count
            if ($received -gt $ExpectedBytes) { throw 'ダウンロードサイズが想定を超えました。' }
            $outputStream.Write($buffer, 0, $count)
            $reported = Write-DownloadProgress $received $ExpectedBytes $lastPercent $timer.ElapsedMilliseconds
            if ($reported -ge 0) {
                $lastPercent = $reported
                $timer.Restart()
            }
        }
        if ($received -ne $ExpectedBytes) { throw 'ダウンロードが途中で終了しました。' }
    } finally {
        if ($outputStream) { $outputStream.Dispose() }
        if ($inputStream) { $inputStream.Dispose() }
        if ($response) { $response.Dispose() }
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
            Write-InstallMessage "配置済みです。既存のモデル・画像・設定は上書きしません。`n$target\起動.lnk"
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
        Write-InstallMessage ('RVC Client -Phamu''s Edition- {0}' -f $Config.version) -ForegroundColor Cyan
        Write-InstallMessage "配置先: $target"
        Write-InstallMessage '実行環境を取得します。Git・Pythonの追加インストールは不要です。'
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
                        Write-InstallMessage ('取得中: {0}（試行{1}/3）' -f $part.name, $attempt)
                        Receive-Artifact ($Config.base_url + $part.name) $temporary $part.bytes
                        if (!(Test-Artifact $temporary $part.bytes $part.sha256)) { throw 'データのハッシュが一致しません。' }
                        [IO.File]::Move($temporary, $path)
                        break
                    } catch {
                        Write-InstallMessage ('取得・検証エラー: {0} (HRESULT={1})' -f $_.Exception.Message, $_.Exception.HResult) -ForegroundColor Yellow
                        if ($attempt -eq 3) { throw }
                        Start-Sleep -Seconds 2
                    }
                }
            } else { Write-InstallMessage ('確認済みデータを再利用: ' + $part.name) }
            $parts += $path
        }
        $zip = Assert-ChildPath $cache (Join-Path $cache $Config.zip_name)
        if (!(Test-Artifact $zip $Config.zip_bytes $Config.zip_sha256)) {
            Write-InstallMessage '分割データを結合・検証しています…'
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
        Write-InstallMessage '展開しています。ファイル数が多いため、しばらくお待ちください…'
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
        catch { Write-InstallMessage "導入は完了しました。一時データは手動で片付けられます: $cache" -ForegroundColor Yellow }
        Write-InstallMessage "`nインストール完了。次の「起動」ショートカットから使えます。`n$target\起動.lnk" -ForegroundColor Green
    }
}

try {
    Initialize-InstallLog $env:PHAMU_INSTALLER_PARENT
    Write-InstallMessage ('Installer started: version={0}; PowerShell={1}; Windows={2}; 64bit={3}' -f $Release.version, $PSVersionTable.PSVersion, [Environment]::OSVersion.Version, [Environment]::Is64BitOperatingSystem)
    if ($script:InstallLogPath) { Write-InstallMessage ('問い合わせ用ログ: ' + $script:InstallLogPath) }
    Invoke-PhamuInstall $Release $env:PHAMU_INSTALLER_PARENT
    Write-InstallMessage 'Installer exit: 0'
    exit 0
} catch {
    Write-InstallMessage "`nインストールできませんでした。" -ForegroundColor Red
    Write-InstallMessage ('{0}: {1} (HRESULT={2})' -f $_.Exception.GetType().Name, $_.Exception.Message, $_.Exception.HResult) -ForegroundColor Red
    Write-InstallMessage $_.ScriptStackTrace
    Write-InstallMessage '通信失敗の場合は、接続を確認して同じバッチを再実行してください。検証済みの分割データは再利用します。'
    Write-InstallMessage 'このバッチは既存のクライアントや個人設定を上書きしません。'
    Write-InstallMessage 'Installer exit: 1'
    exit 1
} finally {
    if ($script:InstallLog) { $script:InstallLog.Dispose(); $script:InstallLog = $null }
}
