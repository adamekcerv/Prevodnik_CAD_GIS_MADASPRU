#!/bin/bash
# Git setup script for CAD to GIS Toolbox

echo "🚀 Inicializace Git repository pro CAD to GIS Toolbox..."

# Initialize git repository
git init

# Add all files
git add .

# Initial commit
git commit -m "🎉 Initial commit: CAD to GIS Toolbox v1.0

✨ Features:
- Complete CAD import workflow (DWG/DXF/DGN)
- Automatic layer pre-selection  
- Polyline processing (merge → polygon → integrate)
- Spatial join analysis for point layers
- Snap operations for line adjustment
- Quality assessment with 'bod' field
- Comprehensive documentation

📊 Supported layers:
- 101110_PL_Resene_uzemi (Polyline)
- 200000_PL_Cast_uzemi (Polyline)  
- 101111_BL_Resene_uzemi (Point)
- 202110_BL_Cast_uzemi_UP (Point)
- 203110_BL_Cast_uzemi_SB (Point)
- 204110_BL_Cast_uzemi_NB (Point)
- 205110_BL_Cast_uzemi_XB (Point)

🎯 Outputs:
- Resene_uzemi_with_Points (polygon analysis)
- Resene_uzemi_Snapped (line analysis)
- All original layers preserved

📖 Documentation:
- README.md - User guide
- TECHNICAL_DOCS.md - Technical documentation  
- CHANGELOG.md - Version history
- Mermaid flowchart included"

echo "✅ Git repository inicializován!"
echo ""
echo "📋 Další kroky pro GitHub:"
echo "1. Vytvořte nový repository na GitHub"
echo "2. Spusťte:"
echo "   git remote add origin https://github.com/username/repository-name.git"
echo "   git branch -M main"
echo "   git push -u origin main"
echo ""
echo "🏷️ Pro vytvoření release tagu:"
echo "   git tag -a v1.0.0 -m 'Release v1.0.0'"
echo "   git push origin v1.0.0"
