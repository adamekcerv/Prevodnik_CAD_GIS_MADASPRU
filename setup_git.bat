@echo off
REM Git setup script for CAD to GIS Toolbox (Windows)

echo 🚀 Inicializace Git repository pro CAD to GIS Toolbox...

REM Initialize git repository
git init

REM Add all files
git add .

REM Initial commit
git commit -m "🎉 Initial commit: CAD to GIS Toolbox v1.0" -m "✨ Features:" -m "- Complete CAD import workflow (DWG/DXF/DGN)" -m "- Automatic layer pre-selection" -m "- Polyline processing (merge → polygon → integrate)" -m "- Spatial join analysis for point layers" -m "- Snap operations for line adjustment" -m "- Quality assessment with 'bod' field" -m "- Comprehensive documentation" -m "" -m "📊 Supported layers:" -m "- 101110_PL_Resene_uzemi (Polyline)" -m "- 200000_PL_Cast_uzemi (Polyline)" -m "- 101111_BL_Resene_uzemi (Point)" -m "- 202110_BL_Cast_uzemi_UP (Point)" -m "- 203110_BL_Cast_uzemi_SB (Point)" -m "- 204110_BL_Cast_uzemi_NB (Point)" -m "- 205110_BL_Cast_uzemi_XB (Point)" -m "" -m "🎯 Outputs:" -m "- Resene_uzemi_with_Points (polygon analysis)" -m "- Resene_uzemi_Snapped (line analysis)" -m "- All original layers preserved" -m "" -m "📖 Documentation:" -m "- README.md - User guide" -m "- TECHNICAL_DOCS.md - Technical documentation" -m "- CHANGELOG.md - Version history" -m "- Mermaid flowchart included"

echo ✅ Git repository inicializován!
echo.
echo 📋 Další kroky pro GitHub:
echo 1. Vytvořte nový repository na GitHub
echo 2. Spusťte:
echo    git remote add origin https://github.com/username/repository-name.git
echo    git branch -M main
echo    git push -u origin main
echo.
echo 🏷️ Pro vytvoření release tagu:
echo    git tag -a v1.0.0 -m "Release v1.0.0"
echo    git push origin v1.0.0

pause
