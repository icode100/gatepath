Set-Location 'C:\Users\ipsdas\Documents\GATE prep\backend'

$pooled = Read-Host 'Paste DB_URL now' -AsSecureString
$direct = Read-Host 'Paste DB_UNPOOLED_URL now' -AsSecureString

$env:DATABASE_URL = [System.Net.NetworkCredential]::new('', $pooled).Password
$env:DATABASE_URL_UNPOOLED = [System.Net.NetworkCredential]::new('', $direct).Password

.\.venv\Scripts\python.exe .\scripts\bootstrap_database.py

Remove-Item Env:DATABASE_URL
Remove-Item Env:DATABASE_URL_UNPOOLED
Remove-Variable pooled, direct