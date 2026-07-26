(this readme is largely AI generated)
# Arma 3 Map Export & Web Viewer

This project provides a complete data pipeline to extract, convert, and visualize Arma 3 maps (WRP files) in a custom 3D web viewer. It extracts terrain heightmaps, surface masks, and all 3D object placements directly from the game's PBO files and renders them in the browser using Three.js.

## Live Demo
Check out a live interactive demo of the 3D map viewer showing the town of Elektro on the Chernarus map:  
**[View Live Demo: Chernarus - Elektro](https://publictools.cinder9.com/3dViewer/?map=chernarus_summer_WRP&x=0.5425&y=0.7623&w=0.2112&h=0.1522)**

## Features
- Parses proprietary .wrp (OPRW v25) map files to extract terrain and object data.
- Automatically searches Arma 3 base game and !Workshop directories for required models.
- Extracts binarized .p3d files using Mikero's BankRev.
- Debinarizes .p3d models (ODOL to MLOD) using a community P3DDebinarizer.
- Converts models to WebGL-friendly .glb format using a headless Blender script.
- Interactive 3D Web Viewer built with Three.js.

## Prerequisites
- **Arma 3** (and any desired mods like CUP) installed.
- **Arma 3 Tools** (Specifically Mikero's BankRev).
- **Blender 4.0+** (with ArmaToolbox extension installed).
- **Python 3.8+** (for the web server and intermediate scripts).
- **PowerShell** (for the automated pipeline).
- **.NET 6.0 SDK** (for compiling the C# WRP Analyzer).

## Setup
1. Clone this repository.
2. Clone the **[bis-file-formats](https://github.com/KoffeinFlummi/bis-file-formats)** repository into the `scripts/` directory so that it sits at `scripts/bis-file-formats`.
3. Download the **[P3D-Debinarizer-Arma-3](https://github.com/ScripyZz/P3D-Debinarizer-Arma-3)** tool from GitHub and extract the `.exe` to a folder on your computer.
4. Build the C# `WrpAnalyzer` tool using the .NET SDK:
   ```bash
   cd scripts/WrpAnalyzer
   dotnet build -c Release
   ```
5. Create `config.json` in the root directory to match your local paths:
   ```json
   {
       "arma3_dir": "E:\\SteamLibrary\\steamapps\\common\\Arma 3",
       "bankrev_exe": "D:\\path\\to\\Arma 3 Tools\\BankRev\\BankRev.exe",
       "blender_exe": "D:\\path\\to\\blender.exe",
       "debinarizer_exe": "D:\\path\\to\\P3DDebinarizer.exe",
       "exports_dir": "C:\\Users\\YourName\\Documents\\Arma3MapExports"
   }
   ```

### Patching P3DDebinarizer
The vanilla `P3DDebinarizer` is built for older assets (ODOL v73) and contains UI code that crashes PowerShell when run headlessly. To support modern mods (like CUP) which use ODOL v75:
1. Decompile `BisDll.dll` (used by P3DDebinarizer) using dotPeek or ILSpy.
2. In `BisDll.Model.ODOL.ODOL.cs`, change `LATEST_VERSION = 73` to `75`.
3. In the same file's `Read()` method, add logic to skip the 8-byte encryption signature introduced in v75 (`stream.Position += 8;`).
4. Recompile `BisDll.dll`.
5. Decompile `P3DDebinarizer.exe` to get the source code.
6. Open `Program.cs` and remove all instances of `Console.Clear()` and `Console.ForegroundColor` which cause `IOException: The handle is invalid` when standard output is redirected.
7. Rebuild the executable using `.NET 8.0` and the patched `BisDll.dll`.

## Usage

### 1. Extract Map Data
First, you must unpack a map's `.pbo` archive to extract its `.wrp` file. Then, use the C# `WrpAnalyzer` tool to parse the `.wrp` file (e.g., Altis or Chernarus) into raw JSON and PNG data:
```bash
cd scripts/WrpAnalyzer
dotnet run -- "C:\path\to\unpacked\altis.wrp" "C:\Users\YourName\Documents\Arma3MapExports\Altis"
```

### 2. Run the Asset Pipeline
Execute the PowerShell script to automatically extract and convert all 3D models referenced by the map. Models are stored in a centralized cache (`scripts/converted_models`) to avoid duplication across maps.
```powershell
cd scripts
.\process_map.ps1 -MapName "Altis"
```
*(Optional)* You can process all maps in your exports directory sequentially by running:
```powershell
.\process_all_maps.ps1
```

### 3. Start the Web Viewer
Start the local Python HTTP server, which acts as an API for the web frontend and serves the centralized models:
```bash
cd web
python server.py
```
Then open http://localhost:8000 in your web browser.

## Documentation
- Detailed notes on the reverse-engineered WRP binary format can be found in `docs/WRP_FORMAT.md`.

## Credits & Acknowledgements
This project relies on several fantastic community tools for reverse engineering and data extraction:
- **[bis-file-formats](https://github.com/KoffeinFlummi/bis-file-formats)**: An open-source C# library used by our `WrpAnalyzer` to parse the proprietary `.wrp` binary files. Included locally in `scripts/bis-file-formats`.
- **[Mikero's Tools (BankRev)](https://mikero.bytex.digital/)**: Used for unpacking binarized PBO archives and extracting the internal game files.
- **[P3D-Debinarizer-Arma-3 (by ScripyZz)](https://github.com/ScripyZz/P3D-Debinarizer-Arma-3)**: Included in the `scripts/` directory, this C# tool converts proprietary binarized Arma 3 models (ODOL) into an editable format (MLOD). 
- **[ArmaToolbox for Blender](https://github.com/AlwarrenSpt/ArmaToolbox)**: A Blender plugin used via a headless Python script to convert the MLOD models into standard GLB files for web rendering.

*Disclaimer: Attempting to reverse-engineer, decompile, or edit game assets is generally intended for educational purposes or for modders working with their own assets. Please ensure you comply with Bohemia Interactive’s EULA when handling proprietary game files.*
