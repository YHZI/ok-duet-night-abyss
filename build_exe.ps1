# Auto Build Script for ok-DNA
Write-Host "Starting build process..." -ForegroundColor Green

# 1. Clean old builds
Write-Host "Cleaning old build files..." -ForegroundColor Yellow
pyinstaller ok-dna.spec --clean

# 2. Check if build was successful
if ($LASTEXITCODE -eq 0) {
    Write-Host "PyInstaller build successful!" -ForegroundColor Green
    
    # 3. Copy necessary folders (manual copy needed due to Chinese filenames)
    Write-Host "Copying runtime folders..." -ForegroundColor Yellow
    
    $distPath = "dist\ok-DNA"
    
    # Copy folders
    Copy-Item -Path "mod" -Destination "$distPath\mod" -Recurse -Force -ErrorAction SilentlyContinue
    Copy-Item -Path "assets" -Destination "$distPath\assets" -Recurse -Force -ErrorAction SilentlyContinue
    Copy-Item -Path "icons" -Destination "$distPath\icons" -Recurse -Force -ErrorAction SilentlyContinue
    Copy-Item -Path "i18n" -Destination "$distPath\i18n" -Recurse -Force -ErrorAction SilentlyContinue
    
    # Copy onnxocr models (PyInstaller doesn't collect them properly)
    Write-Host "Copying ONNX OCR models..." -ForegroundColor Yellow
    $pythonPath = (Get-Command python).Source
    $pythonDir = Split-Path $pythonPath
    $onnxocrModels = "$pythonDir\Lib\site-packages\onnxocr\models"
    if (Test-Path $onnxocrModels) {
        $onnxocrDest = "$distPath\_internal\onnxocr\models"
        New-Item -ItemType Directory -Force -Path (Split-Path $onnxocrDest -Parent) | Out-Null
        Copy-Item -Path $onnxocrModels -Destination $onnxocrDest -Recurse -Force
        Write-Host "ONNX models copied successfully" -ForegroundColor Green
    }
    
    # Copy OpenVINO plugins
    Write-Host "Copying OpenVINO plugins..." -ForegroundColor Yellow
    $openvinoPath = "$pythonDir\Lib\site-packages\openvino"
    if (Test-Path $openvinoPath) {
        $openvinoDest = "$distPath\_internal\openvino"
        Copy-Item -Path $openvinoPath -Destination $openvinoDest -Recurse -Force -ErrorAction SilentlyContinue
        Write-Host "OpenVINO files copied" -ForegroundColor Green
    }
    
    Write-Host ""
    Write-Host "Build completed successfully!" -ForegroundColor Green
    Write-Host "Executable location: $distPath\ok-DNA.exe" -ForegroundColor Cyan
    Write-Host ""
    Write-Host "Note: Distribute the entire '$distPath' folder to users" -ForegroundColor Yellow
} else {
    Write-Host "Build failed! Please check error messages above" -ForegroundColor Red
}
