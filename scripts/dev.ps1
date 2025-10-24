$ErrorActionPreference = "Stop"

Write-Host "[backend] Création de l'environnement virtuel" -ForegroundColor Cyan
python -m venv backend/.venv

Write-Host "[backend] Activation" -ForegroundColor Cyan
if ($IsWindows) { backend/.venv/Scripts/Activate.ps1 } else { . backend/.venv/bin/activate }

pip install -r backend/requirements.txt

Start-Process -FilePath python -ArgumentList "-m", "uvicorn", "backend.app:app", "--reload" -WorkingDirectory "backend"

Write-Host "[frontend] Installation des dépendances" -ForegroundColor Green
pushd frontend
npm install
npm run dev
