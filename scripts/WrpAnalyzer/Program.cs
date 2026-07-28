using System;
using System.IO;
using System.Linq;
using System.Globalization;
using System.Text;
using System.Collections.Generic;
using System.Collections.Concurrent;
using System.Diagnostics;
using System.Threading;
using System.Threading.Tasks;
using System.Text.Json;
using System.Text.Json.Nodes;
using Newtonsoft.Json;
using BIS.Core.Streams;
using BIS.WRP;
using BIS.PBO;
using BIS.P3D.ODOL;

namespace WrpAnalyzer
{
    class Program
    {
        static void Main(string[] args)
        {
            if (args.Length < 1)
            {
                PrintUsage();
                return;
            }

            string command = args[0].ToLower();

            if (command == "extract" && args.Length >= 4)
            {
                ExtractMaps(args[1], args[2], args[3], null);
            }
            else if (command == "extract_single" && args.Length >= 5)
            {
                ExtractMaps(args[1], args[2], args[3], args[4]);
            }
            else if (command == "voxelize" && args.Length >= 4)
            {
                VoxelizeMap(args[1], args[2], args[3]);
            }
            else if (command == "calc_dims" && args.Length >= 4)
            {
                CalcDims(args[1], args[2], args[3]);
            }
            else if (command == "calc_all_dims" && args.Length >= 3)
            {
                CalcAllDims(args[1], args[2]);
            }
            else
            {
                PrintUsage();
            }
        }

        static void PrintUsage()
        {
            Console.WriteLine("Usage:");
            Console.WriteLine("  WrpAnalyzer extract <arma3_dir> <extracted_data_dir> <exports_dir>");
            Console.WriteLine("  WrpAnalyzer extract_single <arma3_dir> <extracted_data_dir> <exports_dir> <map_name>");
            Console.WriteLine("  WrpAnalyzer calc_dims <arma3_dir> <exports_dir> <map_name>");
            Console.WriteLine("  WrpAnalyzer voxelize <arma3_dir> <exports_dir> <map_name>");
        }

        static Dictionary<string, string> IndexPbos(string armaDir)
        {
            Console.WriteLine("Indexing PBOs for models (this may take a minute)...");
            var pboFiles = Directory.GetFiles(armaDir, "*.pbo", SearchOption.AllDirectories);
            var p3dToPboMap = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);
            
            foreach (var pboPath in pboFiles)
            {
                try
                {
                    using (var pbo = new PBO(pboPath))
                    {
                        foreach (var file in pbo.Files)
                        {
                            if (file.FileName.EndsWith(".p3d", StringComparison.OrdinalIgnoreCase))
                            {
                                p3dToPboMap[Path.GetFileName(file.FileName)] = pboPath;
                            }
                        }
                    }
                }
                catch { }
            }
            Console.WriteLine($"Indexed {p3dToPboMap.Count} unique 3D models.");
            return p3dToPboMap;
        }

        static void ExtractMaps(string armaDir, string baseRawDir, string baseWebDir, string mapNameFilter)
        {
            Console.WriteLine("Searching for map PBOs in: " + armaDir);
            var pboFiles = Directory.GetFiles(armaDir, "*map*.pbo", SearchOption.AllDirectories);
            Console.WriteLine($"Found {pboFiles.Length} potential map PBOs.");
            
            string pythonScript = Path.Combine(AppDomain.CurrentDomain.BaseDirectory, "convert_pngs.py");
            HashSet<string> processedMaps = new HashSet<string>(StringComparer.OrdinalIgnoreCase);

            foreach (var pboPath in pboFiles)
            {
                try
                {
                    using (var pbo = new PBO(pboPath))
                    {
                        foreach (var file in pbo.Files)
                        {
                            if (file.FileName.EndsWith(".wrp", StringComparison.OrdinalIgnoreCase))
                            {
                                string mapName = Path.GetFileNameWithoutExtension(file.FileName);
                                
                                if (!string.IsNullOrEmpty(mapNameFilter) && !mapName.Equals(mapNameFilter, StringComparison.OrdinalIgnoreCase))
                                    continue;
                                
                                if (processedMaps.Contains(mapName)) continue;
                                processedMaps.Add(mapName);
                                
                                Console.WriteLine($"\n==========================================");
                                Console.WriteLine($"Processing Map: {mapName} (from {Path.GetFileName(pboPath)})");
                                Console.WriteLine($"==========================================");
                                
                                string mapRawDir = Path.Combine(baseRawDir, mapName, "raw");
                                string mapParsedDir = Path.Combine(baseRawDir, mapName, "parsed");
                                string mapWebDir = Path.Combine(baseWebDir, mapName + "_WRP");
                                
                                Directory.CreateDirectory(mapRawDir);
                                Directory.CreateDirectory(mapParsedDir);
                                Directory.CreateDirectory(mapWebDir);
                                
                                using (var stream = file.OpenRead())
                                {
                                    var oprw = StreamHelper.Read<OPRW>(stream);
                                    var wrp = oprw.ToEditableWrp();
                                    
                                    int hmWidth = oprw.TerrainRangeX;
                                    int hmHeight = oprw.TerrainRangeY;
                                    int matWidth = oprw.LandRangeX;
                                    int matHeight = oprw.LandRangeY;
                                    float cellSize = oprw.CellSize;
                                    int mapSize = (int)(matWidth * cellSize);
                                    float hmCellSize = (float)mapSize / hmWidth;
                                    
                                    string metaContent = $"{{ \"mapSize\": {mapSize}, \"cellSize\": {cellSize.ToString(CultureInfo.InvariantCulture)}, \"hmCellSize\": {hmCellSize.ToString(CultureInfo.InvariantCulture)}, \"terrainRangeX\": {hmWidth}, \"terrainRangeY\": {hmHeight}, \"landRangeX\": {matWidth}, \"landRangeY\": {matHeight}, \"version\": {oprw.Version}, \"minHeight\": {oprw.Elevation.Min().ToString(CultureInfo.InvariantCulture)}, \"maxHeight\": {oprw.Elevation.Max().ToString(CultureInfo.InvariantCulture)} }}";
                                    File.WriteAllText(Path.Combine(mapParsedDir, "meta.json"), metaContent);
                                    File.WriteAllText(Path.Combine(mapWebDir, "meta.json"), metaContent);
                                    
                                    if (oprw.Elevation != null)
                                    {
                                        using (BinaryWriter bw = new BinaryWriter(File.Open(Path.Combine(mapRawDir, "heightmap.bin"), FileMode.Create)))
                                        {
                                            foreach (float f in oprw.Elevation) bw.Write(f);
                                        }
                                    }

                                    if (wrp.MaterialIndex != null)
                                    {
                                        using (BinaryWriter bw = new BinaryWriter(File.Open(Path.Combine(mapRawDir, "material_mask.bin"), FileMode.Create)))
                                        {
                                            foreach (ushort m in wrp.MaterialIndex) bw.Write(m);
                                        }
                                    }

                                    if (wrp.Objects != null)
                                    {
                                        string webObjPath = Path.Combine(mapWebDir, "objects.json");
                                        string parsedObjPath = Path.Combine(mapParsedDir, "objects.json");
                                        
                                        Console.WriteLine($"Exporting {wrp.Objects.Count} objects to JSON...");
                                        
                                        int validCount = 0;
                                        using (StreamWriter sw = new StreamWriter(File.Open(webObjPath, FileMode.Create), new UTF8Encoding(false)))
                                        {
                                            sw.WriteLine("{");
                                            sw.WriteLine("  \"objects\": [");
                                            
                                            for (int i = 0; i < wrp.Objects.Count; i++)
                                            {
                                                var obj = wrp.Objects[i];
                                                if (obj.Model == null || obj.Model.Length == 0) continue;
                                                
                                                float x = obj.Transform.Matrix.M41;
                                                float y = obj.Transform.Matrix.M43; 
                                                float z = obj.Transform.Matrix.M42; 
                                                float yaw = (float)(Math.Atan2(obj.Transform.Matrix.M31, obj.Transform.Matrix.M33) * 180.0 / Math.PI);
                                                yaw = (yaw + 180.0f) % 360.0f;
                                                if (yaw < 0) yaw += 360.0f;
                                                
                                                float scaleX = (float)Math.Sqrt(obj.Transform.Matrix.M11 * obj.Transform.Matrix.M11 + obj.Transform.Matrix.M12 * obj.Transform.Matrix.M12 + obj.Transform.Matrix.M13 * obj.Transform.Matrix.M13);
                                                float scaleY = (float)Math.Sqrt(obj.Transform.Matrix.M21 * obj.Transform.Matrix.M21 + obj.Transform.Matrix.M22 * obj.Transform.Matrix.M22 + obj.Transform.Matrix.M23 * obj.Transform.Matrix.M23);
                                                float scaleZ = (float)Math.Sqrt(obj.Transform.Matrix.M31 * obj.Transform.Matrix.M31 + obj.Transform.Matrix.M32 * obj.Transform.Matrix.M32 + obj.Transform.Matrix.M33 * obj.Transform.Matrix.M33);
                                                
                                                float pitch = (float)(Math.Asin(Math.Max(-1.0, Math.Min(1.0, obj.Transform.Matrix.M32 / scaleZ))) * 180.0 / Math.PI);
                                                float roll = (float)(Math.Atan2(obj.Transform.Matrix.M12 / scaleX, obj.Transform.Matrix.M22 / scaleY) * 180.0 / Math.PI);
                                                
                                                string modelBaseName = Path.GetFileName(obj.Model);

                                                if (validCount > 0) sw.WriteLine(",");
                                                
                                                sw.Write("    {\n");
                                                sw.Write($"      \"class\": \"{obj.Model.Replace("\\", "\\\\")}\",\n");
                                                sw.Write($"      \"model\": \"{modelBaseName}\",\n");
                                                sw.Write($"      \"x\": {x.ToString(CultureInfo.InvariantCulture)},\n");
                                                sw.Write($"      \"y\": {y.ToString(CultureInfo.InvariantCulture)},\n");
                                                sw.Write($"      \"z\": {z.ToString(CultureInfo.InvariantCulture)},\n");
                                                sw.Write($"      \"dir\": {yaw.ToString(CultureInfo.InvariantCulture)},\n");
                                                sw.Write($"      \"pitch\": {pitch.ToString(CultureInfo.InvariantCulture)},\n");
                                                sw.Write($"      \"roll\": {roll.ToString(CultureInfo.InvariantCulture)},\n");
                                                sw.Write($"      \"w\": 1.0,\n");
                                                sw.Write($"      \"l\": 1.0,\n");
                                                sw.Write($"      \"h\": 1.0,\n");
                                                sw.Write($"      \"scaleX\": {scaleX.ToString(CultureInfo.InvariantCulture)},\n");
                                                sw.Write($"      \"scaleY\": {scaleY.ToString(CultureInfo.InvariantCulture)},\n");
                                                sw.Write($"      \"scaleZ\": {scaleZ.ToString(CultureInfo.InvariantCulture)}\n");
                                                sw.Write("    }");
                                                
                                                validCount++;
                                            }
                                            
                                            sw.WriteLine("\n  ]");
                                            sw.WriteLine("}");
                                        }
                                        File.Copy(webObjPath, parsedObjPath, true);
                                    }
                                    
                                    // Extract Shapefile-based roads from data PBOs if present
                                    try
                                    {
                                        ExtractRoads(mapName, pboFiles, mapRawDir);
                                    }
                                    catch (Exception ex)
                                    {
                                        Console.WriteLine($"Warning: Failed to extract shapefile roads: {ex.Message}");
                                    }
                                    
                                    // 4. Export Road Network from the full OPRW Roadnet grid
                                    if (oprw.Roadnet != null)
                                    {
                                        Console.WriteLine("Extracting road network...");
                                        string roadnetPath = Path.Combine(mapParsedDir, "roadnet.json");
                                        int totalLinks = 0;
                                        
                                        using (StreamWriter sw = new StreamWriter(File.Open(roadnetPath, FileMode.Create), new UTF8Encoding(false)))
                                        {
                                            sw.Write("{\"mapSize\":");
                                            sw.Write(mapSize.ToString(CultureInfo.InvariantCulture));
                                            sw.Write(",\"cellSize\":");
                                            sw.Write(cellSize.ToString(CultureInfo.InvariantCulture));
                                            sw.Write(",\"gridW\":");
                                            sw.Write(matWidth.ToString());
                                            sw.Write(",\"gridH\":");
                                            sw.Write(matHeight.ToString());
                                            sw.Write(",\"roads\":[");
                                            
                                            bool firstLink = true;
                                            for (int cellIdx = 0; cellIdx < oprw.Roadnet.Length; cellIdx++)
                                            {
                                                var cellLinks = oprw.Roadnet[cellIdx];
                                                if (cellLinks == null || cellLinks.Length == 0) continue;
                                                
                                                foreach (var link in cellLinks)
                                                {
                                                    if (link == null) continue;
                                                    
                                                    // Classify road type based on P3D path
                                                    string roadType = "road";
                                                    string p3d = link.P3dPath ?? "";
                                                    string p3dLower = p3d.ToLowerInvariant();
                                                    
                                                    if (p3dLower.Contains("highway") || p3dLower.Contains("main_road") || p3dLower.Contains("mainroad"))
                                                        roadType = "mainRoad";
                                                    else if (p3dLower.Contains("dirt") || p3dLower.Contains("track") || p3dLower.Contains("path") || p3dLower.Contains("gravel"))
                                                        roadType = "track";
                                                    else if (p3dLower.Contains("bridge"))
                                                        roadType = "mainRoad";
                                                    
                                                    if (!firstLink) sw.Write(",");
                                                    firstLink = false;
                                                    
                                                    sw.Write("{\"p3d\":\"");
                                                    sw.Write(p3d.Replace("\\", "\\\\"));
                                                    sw.Write("\",\"type\":\"");
                                                    sw.Write(roadType);
                                                    sw.Write("\",\"conns\":");
                                                    sw.Write(link.ConnectionCount.ToString());
                                                    
                                                    // Transform position (world coordinates)
                                                    if (link.ToWorld != null)
                                                    {
                                                        sw.Write(",\"tx\":");
                                                        sw.Write(link.ToWorld.TranslateX.ToString(CultureInfo.InvariantCulture));
                                                        sw.Write(",\"ty\":");
                                                        sw.Write(link.ToWorld.TranslateZ.ToString(CultureInfo.InvariantCulture));
                                                    }
                                                    
                                                    // Connection endpoint positions
                                                    if (link.Positions != null && link.Positions.Length > 0)
                                                    {
                                                        sw.Write(",\"pts\":[");
                                                        for (int p = 0; p < link.Positions.Length; p++)
                                                        {
                                                            if (p > 0) sw.Write(",");
                                                            sw.Write("[");
                                                            sw.Write(link.Positions[p].X.ToString(CultureInfo.InvariantCulture));
                                                            sw.Write(",");
                                                            sw.Write(link.Positions[p].Z.ToString(CultureInfo.InvariantCulture));
                                                            sw.Write("]");
                                                        }
                                                        sw.Write("]");
                                                    }
                                                    
                                                    // Connection types (v24+)
                                                    if (link.ConnectionTypes != null && link.ConnectionTypes.Length > 0)
                                                    {
                                                        sw.Write(",\"ctypes\":[");
                                                        for (int ct = 0; ct < link.ConnectionTypes.Length; ct++)
                                                        {
                                                            if (ct > 0) sw.Write(",");
                                                            sw.Write(link.ConnectionTypes[ct].ToString());
                                                        }
                                                        sw.Write("]");
                                                    }
                                                    
                                                    sw.Write("}");
                                                    totalLinks++;
                                                }
                                            }
                                            
                                            sw.Write("]}");
                                        }
                                        Console.WriteLine($"Exported {totalLinks} road links to roadnet.json.");
                                        File.Copy(roadnetPath, Path.Combine(mapWebDir, "roadnet.json"), true);
                                    }
                                    
                                    Console.WriteLine("Generating PNGs via python...");
                                    string mapBaseDir = Path.Combine(baseRawDir, mapName);
                                    ProcessStartInfo psi = new ProcessStartInfo
                                    {
                                        FileName = "python",
                                        Arguments = $"\"{pythonScript}\" \"{mapBaseDir}\" {hmWidth} {hmHeight} {matWidth} {matHeight}",
                                        UseShellExecute = false,
                                        RedirectStandardOutput = true,
                                        CreateNoWindow = true
                                    };
                                    using (var process = Process.Start(psi)) { process.WaitForExit(); }
                                    
                                    string hmPngSource = Path.Combine(mapParsedDir, "heightmap.png");
                                    string hmPngDest = Path.Combine(mapWebDir, "heightmap.png");
                                    if (File.Exists(hmPngSource)) File.Copy(hmPngSource, hmPngDest, true);
                                    
                                    string hmGreyPngSource = Path.Combine(mapParsedDir, "heightmap_grey.png");
                                    string hmGreyPngDest = Path.Combine(mapWebDir, "heightmap_grey.png");
                                    if (File.Exists(hmGreyPngSource)) File.Copy(hmGreyPngSource, hmGreyPngDest, true);
                                    
                                    // Generate roads.png from roadnet.json
                                    string renderRoadsScript = Path.Combine(AppDomain.CurrentDomain.BaseDirectory, "render_roads.py");
                                    string roadnetJsonPath = Path.Combine(mapParsedDir, "roadnet.json");
                                    if (File.Exists(renderRoadsScript) && File.Exists(roadnetJsonPath))
                                    {
                                        Console.WriteLine("Rendering roads.png...");
                                        ProcessStartInfo roadsPsi = new ProcessStartInfo
                                        {
                                            FileName = "python",
                                            Arguments = $"\"{renderRoadsScript}\" \"{roadnetJsonPath}\" \"{mapParsedDir}\" \"{mapWebDir}\"",
                                            UseShellExecute = false,
                                            RedirectStandardOutput = true,
                                            CreateNoWindow = true
                                        };
                                        using (var roadProcess = Process.Start(roadsPsi)) { roadProcess.WaitForExit(); }
                                    }
                                    
                                    Console.WriteLine($"Finished {mapName} successfully.");
                                }
                            }
                        }
                    }
                    GC.Collect();
                    GC.WaitForPendingFinalizers();
                }
                catch (Exception ex)
                {
                    Console.WriteLine($"Failed to process PBO {pboPath}: {ex.Message}");
                }
            }
            Console.WriteLine("\nAll Maps Processed!");
        }

        static void CalcDims(string armaDir, string baseWebDir, string mapName)
        {
            string mapWebDir = Path.Combine(baseWebDir, mapName + "_WRP");
            string objectsJsonPath = Path.Combine(mapWebDir, "objects.json");
            
            if (!File.Exists(objectsJsonPath))
            {
                Console.WriteLine($"Error: {objectsJsonPath} does not exist. Did you run extract first?");
                return;
            }

            Console.WriteLine("Parsing objects.json...");
            string jsonText = File.ReadAllText(objectsJsonPath);
            JsonNode rootNode = JsonNode.Parse(jsonText);
            JsonArray objectsArray = rootNode["objects"].AsArray();

            var neededModels = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
            foreach (var obj in objectsArray)
            {
                neededModels.Add(obj["model"].ToString());
            }
            Console.WriteLine($"Found {neededModels.Count} unique models on {mapName}.");

            var p3dToPboMap = IndexPbos(armaDir);
            var modelDimensions = new Dictionary<string, (float w, float l, float h)>(StringComparer.OrdinalIgnoreCase);

            int processed = 0;
            Console.WriteLine("Calculating exact physical bounds from Geometry LOD vertice extremes...");
            foreach (var modelBaseName in neededModels)
            {
                float width = 1f, length = 1f, height = 1f;

                if (p3dToPboMap.TryGetValue(modelBaseName, out string pboModelPath))
                {
                    try {
                        using (var modelPbo = new PBO(pboModelPath)) {
                            var pboFile = modelPbo.Files.FirstOrDefault(f => f.FileName.EndsWith(modelBaseName, StringComparison.OrdinalIgnoreCase));
                            if (pboFile != null) {
                                using (var pboStream = pboFile.OpenRead()) {
                                    var p3d = StreamHelper.Read<BIS.P3D.P3D>(pboStream);
                                    if (p3d.ODOL != null) {
                                        var geometryLod = p3d.ODOL.Lods.FirstOrDefault(l => l.Resolution == 1.0e13f);
                                        if (geometryLod == null) geometryLod = p3d.ODOL.Lods.FirstOrDefault();

                                        if (geometryLod != null && geometryLod.Vertices != null && geometryLod.Vertices.Count > 0)
                                        {
                                            float minX = float.MaxValue, minY = float.MaxValue, minZ = float.MaxValue;
                                            float maxX = float.MinValue, maxY = float.MinValue, maxZ = float.MinValue;
                                            
                                            foreach (var v in geometryLod.Vertices)
                                            {
                                                if (v.X < minX) minX = v.X;
                                                if (v.X > maxX) maxX = v.X;
                                                if (v.Y < minY) minY = v.Y;
                                                if (v.Y > maxY) maxY = v.Y;
                                                if (v.Z < minZ) minZ = v.Z;
                                                if (v.Z > maxZ) maxZ = v.Z;
                                            }
                                            
                                            width = maxX - minX;
                                            height = maxY - minY;
                                            length = maxZ - minZ;
                                        }
                                        else 
                                        {
                                            // Fallback to bounding box info
                                            width = p3d.ODOL.ModelInfo.BboxMax.X - p3d.ODOL.ModelInfo.BboxMin.X;
                                            height = p3d.ODOL.ModelInfo.BboxMax.Y - p3d.ODOL.ModelInfo.BboxMin.Y;
                                            length = p3d.ODOL.ModelInfo.BboxMax.Z - p3d.ODOL.ModelInfo.BboxMin.Z;
                                        }
                                    }
                                }
                            }
                        }
                    } catch {
                        // Skip if corrupt
                    }
                }

                if (width <= 0.01f) width = 1f;
                if (height <= 0.01f) height = 1f;
                if (length <= 0.01f) length = 1f;
                
                modelDimensions[modelBaseName] = (width, length, height);
                processed++;
                if (processed % 100 == 0) Console.WriteLine($"Processed {processed}/{neededModels.Count} models...");
            }

            Console.WriteLine($"Updating objects.json with precise vertice dimensions ({objectsArray.Count} objects)...");
            int objCounter = 0;
            foreach (var obj in objectsArray)
            {
                string model = obj["model"].ToString();
                if (modelDimensions.TryGetValue(model, out var dims))
                {
                    obj["w"] = dims.w;
                    obj["l"] = dims.l;
                    obj["h"] = dims.h;
                }
                
                objCounter++;
                if (objCounter % 10000 == 0) Console.WriteLine($"  Applied dimensions to {objCounter}/{objectsArray.Count} objects...");
            }

            File.WriteAllText(objectsJsonPath, rootNode.ToJsonString(new JsonSerializerOptions { WriteIndented = false }));
            Console.WriteLine($"\nDimension calculation complete! Perfectly sized bounding boxes are ready for {mapName}.");
        }

        static void CalcAllDims(string armaDir, string baseWebDir)
        {
            var objectsFiles = Directory.GetFiles(baseWebDir, "objects.json", SearchOption.AllDirectories);
            if (objectsFiles.Length == 0)
            {
                Console.WriteLine("No objects.json files found in " + baseWebDir);
                return;
            }

            Console.WriteLine($"Found {objectsFiles.Length} map exports. Collecting unique models across all maps...");
            var neededModels = new HashSet<string>(StringComparer.OrdinalIgnoreCase);

            int totalProcessedFiles = 0;
            long totalObjectsFound = 0;

            foreach (var file in objectsFiles)
            {
                totalProcessedFiles++;
                Console.WriteLine($"  Scanning {Path.GetFileName(Path.GetDirectoryName(file))} ({totalProcessedFiles}/{objectsFiles.Length})...");
                
                using (var sr = new StreamReader(file))
                {
                    string line;
                    while ((line = sr.ReadLine()) != null)
                    {
                        int pos = 0;
                        while ((pos = line.IndexOf("\"model\":", pos, StringComparison.Ordinal)) != -1)
                        {
                            pos += 8;
                            while (pos < line.Length && (line[pos] == ' ' || line[pos] == '"')) pos++;
                            int end = line.IndexOf("\"", pos, StringComparison.Ordinal);
                            if (end > pos) {
                                string model = line.Substring(pos, end - pos);
                                neededModels.Add(model);
                                totalObjectsFound++;
                            }
                            pos = end;
                            if (pos <= 0) break;
                        }
                    }
                }
                
                Console.WriteLine($"    Found {totalObjectsFound} objects globally so far.");
            }
            Console.WriteLine($"Found {neededModels.Count} unique models globally.");

            var p3dToPboMap = IndexPbos(armaDir);
            var modelDimensions = new Dictionary<string, (float w, float l, float h)>(StringComparer.OrdinalIgnoreCase);

            int processed = 0;
            Console.WriteLine("Calculating exact physical bounds from Geometry LOD vertice extremes (this is done only once per unique object)...");
            foreach (var modelBaseName in neededModels)
            {
                float width = 1f, length = 1f, height = 1f;

                if (p3dToPboMap.TryGetValue(modelBaseName, out string pboModelPath))
                {
                    try {
                        using (var modelPbo = new PBO(pboModelPath)) {
                            var pboFile = modelPbo.Files.FirstOrDefault(f => f.FileName.EndsWith(modelBaseName, StringComparison.OrdinalIgnoreCase));
                            if (pboFile != null) {
                                using (var pboStream = pboFile.OpenRead()) {
                                    var p3d = StreamHelper.Read<BIS.P3D.P3D>(pboStream);
                                    if (p3d.ODOL != null) {
                                        var geometryLod = p3d.ODOL.Lods.FirstOrDefault(l => l.Resolution == 1.0e13f);
                                        if (geometryLod == null) geometryLod = p3d.ODOL.Lods.FirstOrDefault();

                                        if (geometryLod != null && geometryLod.Vertices != null && geometryLod.Vertices.Count > 0)
                                        {
                                            float minX = float.MaxValue, minY = float.MaxValue, minZ = float.MaxValue;
                                            float maxX = float.MinValue, maxY = float.MinValue, maxZ = float.MinValue;
                                            
                                            foreach (var v in geometryLod.Vertices)
                                            {
                                                if (v.X < minX) minX = v.X;
                                                if (v.X > maxX) maxX = v.X;
                                                if (v.Y < minY) minY = v.Y;
                                                if (v.Y > maxY) maxY = v.Y;
                                                if (v.Z < minZ) minZ = v.Z;
                                                if (v.Z > maxZ) maxZ = v.Z;
                                            }
                                            
                                            width = maxX - minX;
                                            height = maxY - minY;
                                            length = maxZ - minZ;
                                        }
                                        else 
                                        {
                                            width = p3d.ODOL.ModelInfo.BboxMax.X - p3d.ODOL.ModelInfo.BboxMin.X;
                                            height = p3d.ODOL.ModelInfo.BboxMax.Y - p3d.ODOL.ModelInfo.BboxMin.Y;
                                            length = p3d.ODOL.ModelInfo.BboxMax.Z - p3d.ODOL.ModelInfo.BboxMin.Z;
                                        }
                                    }
                                }
                            }
                        }
                    } catch { }
                }

                if (width <= 0.01f) width = 1f;
                if (height <= 0.01f) height = 1f;
                if (length <= 0.01f) length = 1f;
                
                modelDimensions[modelBaseName] = (width, length, height);
                processed++;
                if (processed % 100 == 0) Console.WriteLine($"Processed {processed}/{neededModels.Count} models...");
            }

            Console.WriteLine("\nUpdating objects.json for all maps...");
            foreach (var file in objectsFiles)
            {
                string mapName = Path.GetFileName(Path.GetDirectoryName(file));
                Console.WriteLine($"Applying dimensions and minifying {mapName}...");
                
                // Stream JSON processing using Newtonsoft.Json to avoid reading 1GB+ into memory
                string tempFile = file + ".tmp";
                
                using (var sr = new StreamReader(file))
                using (var reader = new JsonTextReader(sr))
                using (var sw = new StreamWriter(tempFile))
                using (var writer = new JsonTextWriter(sw))
                {
                    writer.Formatting = Formatting.None; // Minify to save space
                    
                    int objCounter = 0;
                    string currentModel = null;
                    
                    while (reader.Read())
                    {
                        if (reader.TokenType == JsonToken.PropertyName)
                        {
                            string propName = (string)reader.Value;
                            if (propName == "model")
                            {
                                writer.WritePropertyName(propName);
                                reader.Read();
                                currentModel = (string)reader.Value;
                                writer.WriteValue(currentModel);
                            }
                            else if (propName == "w" || propName == "l" || propName == "h")
                            {
                                writer.WritePropertyName(propName);
                                reader.Read(); // Consume the old value
                                
                                if (modelDimensions.TryGetValue(currentModel ?? "", out var dims))
                                {
                                    if (propName == "w") writer.WriteValue(dims.w);
                                    else if (propName == "l") writer.WriteValue(dims.l);
                                    else if (propName == "h") writer.WriteValue(dims.h);
                                }
                                else
                                {
                                    writer.WriteValue(1.0); // Fallback
                                }
                            }
                            else
                            {
                                writer.WritePropertyName(propName);
                            }
                        }
                        else if (reader.TokenType == JsonToken.Float)
                        {
                            // Correct Arma 3 corrupted float exports (Infinity, NaN) which break JS parsers
                            double val = (double)reader.Value;
                            if (double.IsInfinity(val) || double.IsNaN(val))
                            {
                                writer.WriteValue(0.0);
                            }
                            else
                            {
                                writer.WriteValue(val);
                            }
                        }
                        else if (reader.TokenType == JsonToken.StartObject)
                        {
                            currentModel = null;
                            writer.WriteStartObject();
                        }
                        else if (reader.TokenType == JsonToken.EndObject)
                        {
                            writer.WriteEndObject();
                            objCounter++;
                            if (objCounter % 100000 == 0) Console.WriteLine($"  Applied dimensions to {objCounter} objects...");
                        }
                        else
                        {
                            writer.WriteToken(reader, false);
                        }
                    }
                }
                
                // Replace the old file with the new temp file
                File.Move(tempFile, file, true);
                
                // Force GC
                GC.Collect();
                GC.WaitForPendingFinalizers();
            }
            Console.WriteLine("\nGlobal dimension calculation complete! All maps are perfectly sized.");
        }

        static void VoxelizeMap(string armaDir, string baseWebDir, string mapName)
        {
            string mapWebDir = Path.Combine(baseWebDir, mapName + "_WRP");
            string objectsJsonPath = Path.Combine(mapWebDir, "objects.json");
            
            if (!File.Exists(objectsJsonPath))
            {
                Console.WriteLine($"Error: {objectsJsonPath} does not exist. Did you run extract first?");
                return;
            }

            string modelsWebDir = Path.Combine(baseWebDir, "models");
            Directory.CreateDirectory(modelsWebDir);
            
            // Fast parse to get unique models needed for this map
            var neededModels = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
            Console.WriteLine($"Reading {objectsJsonPath} to find needed models...");
            using (var sr = new StreamReader(objectsJsonPath))
            {
                string line;
                while ((line = sr.ReadLine()) != null)
                {
                    int pos = 0;
                    while ((pos = line.IndexOf("\"model\":", pos, StringComparison.Ordinal)) != -1)
                    {
                        pos += 8;
                        while (pos < line.Length && (line[pos] == ' ' || line[pos] == '"')) pos++;
                        int end = line.IndexOf("\"", pos, StringComparison.Ordinal);
                        if (end > pos)
                        {
                            string model = line.Substring(pos, end - pos);
                            neededModels.Add(model);
                        }
                        pos = end;
                        if (pos <= 0) break;
                    }
                }
            }
            Console.WriteLine($"Found {neededModels.Count} unique models on {mapName}.");
            
            // Filter out models we already generated
            var missingModels = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
            foreach (var model in neededModels)
            {
                string glbFileName = Path.GetFileNameWithoutExtension(model) + ".glb";
                string glbFilePath = Path.Combine(modelsWebDir, glbFileName);
                if (!File.Exists(glbFilePath))
                {
                    missingModels.Add(model);
                }
            }
            
            if (missingModels.Count == 0)
            {
                Console.WriteLine($"All models for {mapName} are already voxelized!");
                return;
            }
            
            Console.WriteLine($"{missingModels.Count} models need to be voxelized.");
            Console.WriteLine($"Using {Environment.ProcessorCount} threads for parallel voxelization.");
            var p3dToPboMap = IndexPbos(armaDir);
            
            int processed = 0;
            var processedLock = new object();
            var total = missingModels.Count;
            
            Parallel.ForEach(missingModels,
                new ParallelOptions { MaxDegreeOfParallelism = Environment.ProcessorCount },
                (modelBaseName) =>
            {
                string glbFileName = Path.GetFileNameWithoutExtension(modelBaseName) + ".glb";
                string glbFilePath = Path.Combine(modelsWebDir, glbFileName);
                
                if (p3dToPboMap.TryGetValue(modelBaseName, out string pboModelPath))
                {
                    try {
                        using (var modelPbo = new PBO(pboModelPath)) {
                            var pboFile = modelPbo.Files.FirstOrDefault(f => f.FileName.EndsWith(modelBaseName, StringComparison.OrdinalIgnoreCase));
                            if (pboFile != null) {
                                using (var pboStream = pboFile.OpenRead()) {
                                    var p3d = StreamHelper.Read<BIS.P3D.P3D>(pboStream);
                                    if (p3d.ODOL != null) {
                                        var geometryLod = p3d.ODOL.Lods.FirstOrDefault(l => l.Resolution == 1.0e13f);
                                        if (geometryLod == null) geometryLod = p3d.ODOL.Lods.FirstOrDefault();
                                        
                                        if (geometryLod != null) {
                                            Voxelizer.ExportToGlb(p3d.ODOL.ModelInfo, geometryLod, glbFilePath);
                                            
                                            lock (processedLock)
                                            {
                                                processed++;
                                                if (processed % 100 == 0)
                                                    Console.WriteLine($"Voxelized {processed}/{total} models...");
                                            }
                                        }
                                    }
                                }
                            }
                        }
                    } catch {
                        // Skip if corrupt
                    }
                }
            });
            
            Console.WriteLine($"\nVoxelization complete! Generated {processed} new models for {mapName}.");
        }
        static void ExtractRoads(string mapName, string[] pboFiles, string rawDir)
        {
            Console.WriteLine($"Searching for shapefile roads for {mapName}...");
            foreach (var pboPath in pboFiles)
            {
                string pboName = Path.GetFileNameWithoutExtension(pboPath).ToLowerInvariant();
                if (!pboName.Contains(mapName.ToLowerInvariant())) continue;

                try
                {
                    using (var pbo = new PBO(pboPath))
                    {
                        var shpFile = pbo.Files.FirstOrDefault(f => f.FileName.EndsWith("roads.shp", StringComparison.OrdinalIgnoreCase));
                        if (shpFile != null)
                        {
                            string roadsDir = Path.GetDirectoryName(shpFile.FileName) ?? "";
                            string roadsRawDest = Path.Combine(rawDir, "roads");
                            Directory.CreateDirectory(roadsRawDest);
                            
                            foreach (var file in pbo.Files)
                            {
                                string fileDir = Path.GetDirectoryName(file.FileName) ?? "";
                                if (fileDir.Equals(roadsDir, StringComparison.OrdinalIgnoreCase))
                                {
                                    string ext = Path.GetExtension(file.FileName).ToLowerInvariant();
                                    if (ext == ".shp" || ext == ".dbf" || ext == ".shx" || ext == ".cfg" || ext == ".bin")
                                    {
                                        string destPath = Path.Combine(roadsRawDest, Path.GetFileName(file.FileName));
                                        using (var srcStream = file.OpenRead())
                                        using (var destStream = File.OpenWrite(destPath))
                                        {
                                            srcStream.CopyTo(destStream);
                                        }
                                        Console.WriteLine($"Extracted road file: {Path.GetFileName(file.FileName)} from {Path.GetFileName(pboPath)}");
                                    }
                                }
                            }
                            break; // Found roads for this map
                        }
                    }
                }
                catch { }
            }
        }
    }
}
