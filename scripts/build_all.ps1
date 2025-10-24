$ErrorActionPreference = "Stop"

Write-Host "==> Build backend" -ForegroundColor Cyan
pushd backend
python -m venv .venv
if ($IsWindows) { .venv/Scripts/Activate.ps1 } else { . .venv/bin/activate }
pip install -r requirements.txt
pytest
popd

Write-Host "==> Build frontend" -ForegroundColor Green
pushd frontend
npm install
npm run build
popd

Write-Host "==> Build desktop" -ForegroundColor Yellow
pushd desktop/tauri
npm install
npm run tauri build
popd
