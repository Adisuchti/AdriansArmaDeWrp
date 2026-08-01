(this readme is largely AI generated)
# Arma 3 Map Export & Web Viewer

This project provides a complete data pipeline to extract, convert, and visualize Arma 3 maps (WRP files) and mission files (SQM) in a custom 3D web viewer. It extracts terrain heightmaps, surface masks, all 3D object placements from WRP files, and placed entities from SQM mission files, then renders them in the browser using Three.js.

## Live Demo
Check out a live interactive demo of the 3D map viewer showing the town of Elektro on the Chernarus map:  
**[View Live Demo: Chernarus - Elektro](https://publictools.cinder9.com/3dViewer/?map=chernarus_summer_WRP&x=0.5425&y=0.7623&w=0.2112&h=0.1522)**

## Features
- Parses proprietary .wrp (OPRW v25) map files to extract terrain and object data.
- Parses .sqm mission files to extract placed vehicles, units, and objects.
- Automatically searches Arma 3 base game and !Workshop directories for required models.
- **Procedural Generation**: Does *not* extract or convert proprietary 3D meshes. Instead, procedurally generates abstract, blocky "Voxel" representations of buildings and trees based on collision bounding boxes. Voxelization is fully parallelized across all CPU cores.
- Mission entities displayed with side-colored markers (Blue=West, Red=East, Green=Independent, Grey=Empty).
- Interactive 3D Web Viewer built with Three.js.

## Prerequisites
- **Arma 3** (and any desired mods like CUP) installed.
- **Python 3.8+** (for the web server and intermediate scripts). Requires `Pillow`, `numpy`, and `matplotlib`.
  ```bash
  pip install Pillow numpy matplotlib
  ```
- **PowerShell** (for the automated pipeline).
- **.NET 10.0 SDK** (for compiling the C# WRP Analyzer).

## Setup
1. Clone this repository.
2. Clone the **[bis-file-formats](https://github.com/Braini01/bis-file-formats)** repository into the `scripts/` directory so that it sits at `scripts/bis-file-formats`.
3. Build the C# `WrpAnalyzer` tool using the .NET SDK:
   ```bash
   cd scripts/WrpAnalyzer
   dotnet build -c Release
   ```
4. Create `config.json` in the root directory to match your local paths:
   ```json
   {
       "arma3_dir": "E:\\SteamLibrary\\steamapps\\common\\Arma 3",
       "workshop_dir": "E:\\SteamLibrary\\steamapps\\workshop\\content\\107410",
       "exports_dir": "C:\\Users\\YourName\\Documents\\Arma3MapExports"
   }
   ```

## Usage - WRP Maps

### 1. Extract Map Data
The extraction step scans the map data to generate raw JSON, PNG data for each map, and calculates base placements. *It does not calculate building dimensions or voxelize models yet to keep extraction fast.*

**To extract all maps in your Arma 3 and Workshop folders:**
```powershell
cd scripts
.\extract_all_maps.ps1
```

**To extract a single specific map:**
```powershell
cd scripts
.\extract_map.ps1 -MapName "Altis"
```

### 2. Process Models (For a Specific Map)

#### Option A: Lightweight Dimensions (Fastest)
Instantly reads vertex extremes to calculate bounding boxes.
```powershell
cd scripts
.\process_map_simple.ps1 -MapName "Altis"
```
**Process all extracted maps (Recommended):**
```powershell
cd scripts
.\process_all_map_simple.ps1
```

#### Option B: Full Voxelization (Higher Quality)
Generates abstract voxel 3D representations as `.glb` files.
```powershell
cd scripts
.\process_map.ps1 -MapName "Altis"
```

### 3. Generate Topographic SVG Maps (Optional)
Generates a highly detailed, 2D vector map (`.svg`) with contour lines (e.g. 10m intervals), roads, and landmass.
```bash
cd scripts
python generate_svg.py C:\Users\YourName\Documents\Arma3MapExports\Altis_WRP
```
*Note: This script requires `numpy` and `matplotlib` to be installed.*

### 4. Generate Top-Down PNG Maps (Optional)
Generates a high-resolution top-down raster map (`.png`) representing terrain surface masks, roads, and object placements as coloured pixels and polygons.
```bash
cd scripts
python render_topdown.py C:\Users\YourName\Documents\Arma3MapExports\Altis_WRP --no-terrain --bg-color "#1e1e1e"
```
*Tip: Omit `--no-terrain` to automatically use `terrain_class.png` as the background if it was extracted.*

### 5. Start the Web Viewer
```bash
cd web
python server.py
```
Then open http://localhost:8000 in your web browser.

## Usage - SQM Mission Files

The mission pipeline extracts placed entities (vehicles, units, objects) from `.sqm` mission files.

### 1. Extract a Mission
Parses the mission file and outputs entities with their types, positions, and sides.
```powershell
cd scripts
.\extract_mission.ps1 -MissionFile "C:\path\to\mission.sqm" -MissionName "MyMission"
```
This creates `MyMission_SQM/` in your exports directory with `meta.json` and `entities.json`.

### 2. Process Mission Models (Optional)
Checks which model types from the mission are available in the central model cache.
```powershell
cd scripts
.\process_mission.ps1 -MissionName "MyMission"
```
*Note: Models are cached centrally in `{exports_dir}/models/` — if you've already processed the corresponding map with `process_map.ps1` or `process_map_simple.ps1`, all models should already be available.*

### 3. View in Browser
- Start the web viewer (`python server.py` from the `web/` directory)
- Select the map the mission is on from the **Map** dropdown
- Select the mission from the **Mission** dropdown
- Select a region and click **Render 3D**
- Mission entities are displayed as colored markers on the terrain:
  - 🔵 Blue spheres/boxes = BLUFOR/West
  - 🔴 Red = OPFOR/East
  - 🟢 Green = Independent/Resistance
  - ⚪ Grey = Empty/Civilian

## Documentation
- Detailed notes on the reverse-engineered WRP binary format can be found in `docs/WRP_FORMAT.md`.

## Credits & Acknowledgements
- **[bis-file-formats (Braini01 fork)](https://github.com/Braini01/bis-file-formats)**: Open-source C# library for parsing `.wrp` and `.p3d` binary structures. Included locally in `scripts/bis-file-formats`.

*Note: This tool does not distribute or convert Bohemia Interactive's proprietary 3D meshes (ODOL). All 3D assets generated by this tool are mathematically abstracted voxel bounding boxes designed for web mapping.*