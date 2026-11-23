param([string]$Model = 'deepseek-flash')

$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $projectRoot
git check-ignore --quiet -- .env
if ($LASTEXITCODE -ne 0) { throw '.env must be ignored by Git before storing a key.' }
$trackedEnv = @(git ls-files -- .env)
if ($trackedEnv.Count -gt 0) { throw '.env is tracked by Git. Remove it from the index first.' }

Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
[System.Windows.Forms.Application]::EnableVisualStyles()
$form = New-Object System.Windows.Forms.Form
$form.Text = 'ACM Agent - DeepSeek setup (local only)'
$form.Size = New-Object System.Drawing.Size(570, 325)
$form.StartPosition = 'CenterScreen'
$form.FormBorderStyle = 'FixedDialog'
$form.MaximizeBox = $false
$form.TopMost = $true

$description = New-Object System.Windows.Forms.Label
$description.Text = "Enter your DeepSeek API key below. It is saved only to this project's ignored .env file. Do not paste the key into chat."
$description.Location = New-Object System.Drawing.Point(25, 20)
$description.Size = New-Object System.Drawing.Size(510, 45)
$form.Controls.Add($description)
$keyLabel = New-Object System.Windows.Forms.Label
$keyLabel.Text = 'API key'
$keyLabel.Location = New-Object System.Drawing.Point(25, 80)
$form.Controls.Add($keyLabel)
$keyBox = New-Object System.Windows.Forms.TextBox
$keyBox.UseSystemPasswordChar = $true
$keyBox.Location = New-Object System.Drawing.Point(130, 76)
$keyBox.Size = New-Object System.Drawing.Size(390, 25)
$form.Controls.Add($keyBox)
$modelLabel = New-Object System.Windows.Forms.Label
$modelLabel.Text = 'Model'
$modelLabel.Location = New-Object System.Drawing.Point(25, 125)
$form.Controls.Add($modelLabel)
$modelBox = New-Object System.Windows.Forms.TextBox
$modelBox.Text = $Model
$modelBox.Location = New-Object System.Drawing.Point(130, 121)
$modelBox.Size = New-Object System.Drawing.Size(390, 25)
$form.Controls.Add($modelBox)
$statusLabel = New-Object System.Windows.Forms.Label
$statusLabel.Text = 'Endpoint: https://api.deepseek.com | The key is never printed.'
$statusLabel.Location = New-Object System.Drawing.Point(25, 171)
$statusLabel.Size = New-Object System.Drawing.Size(510, 35)
$form.Controls.Add($statusLabel)
$saveButton = New-Object System.Windows.Forms.Button
$saveButton.Text = 'Save locally'
$saveButton.Location = New-Object System.Drawing.Point(370, 220)
$saveButton.Size = New-Object System.Drawing.Size(150, 35)
$saveButton.Add_Click({
    $secretValue = $keyBox.Text.Trim()
    if ($secretValue -notmatch '^[A-Za-z0-9_-]{16,}$') {
        $statusLabel.Text = 'Please enter a valid API key without spaces or line breaks.'
        return
    }
    $modelValue = $modelBox.Text.Trim()
    if ($modelValue -notmatch '^[A-Za-z0-9._-]+$') {
        $statusLabel.Text = 'Please enter a valid model name.'
        return
    }
    try {
        $envPath = Join-Path $projectRoot '.env'
        $existingLines = @()
        if (Test-Path -LiteralPath $envPath) {
            $existingLines = [System.IO.File]::ReadAllLines($envPath)
        }
        $keptLines = @($existingLines | Where-Object { $_ -notmatch '^\s*(ACM_MODEL_PROVIDER|DEEPSEEK_API_KEY|DEEPSEEK_MODEL)\s*=' })
        $newLines = $keptLines + @('ACM_MODEL_PROVIDER=deepseek', ('DEEPSEEK_API_KEY=' + $secretValue), ('DEEPSEEK_MODEL=' + $modelValue))
        [System.IO.File]::WriteAllLines($envPath, $newLines, (New-Object System.Text.UTF8Encoding($false)))
        $keyBox.Clear()
        $secretValue = $null
        $form.DialogResult = [System.Windows.Forms.DialogResult]::OK
        $form.Close()
    } catch {
        $statusLabel.Text = 'Could not save configuration. Check folder permissions and retry.'
    }
})
$form.Controls.Add($saveButton)
$form.AcceptButton = $saveButton
$form.Add_Shown({ $keyBox.Focus() })
$result = $form.ShowDialog()
$keyBox.Clear()
$form.Dispose()
if ($result -eq [System.Windows.Forms.DialogResult]::OK) {
    Write-Output 'DeepSeek configuration saved locally. Restart ACM Agent to apply it.'
} else {
    Write-Output 'Setup cancelled. No key was saved.'
}
