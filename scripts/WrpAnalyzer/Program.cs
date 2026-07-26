using System;
using System.IO;
using System.Linq;
using System.Globalization;
using System.Text;
using System.Collections.Generic;
using System.Diagnostics;
using BIS.Core.Streams;
using BIS.WRP;
using BIS.PBO;

namespace WrpAnalyzer
{
    class Program
    {
        static void Main(string[] args)
        {
            if (args.Length < 3)
            {
                Console.WriteLine("Usage: WrpAnalyzer <arma3_dir> <extracted_data_dir> <exports_dir>");
                return;
            }

            string armaDir = args[0];
            string baseRawDir = args[1];
            string baseWebDir = args[2];
            string pythonScript = Path.Combine(AppDomain.CurrentDomain.BaseDirectory, "convert_pngs.py");
            
            Console.WriteLine("Searching for map PBOs in: " + armaDir);
            
            var pboFiles = Directory.GetFiles(armaDir, "*map*.pbo", SearchOption.AllDirectories);
            Console.WriteLine($"Found {pboFiles.Length} potential map PBOs.");
            
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
                                    
                                    Console.WriteLine($"Map Size: Heightmap={hmWidth}x{hmHeight}, Material={matWidth}x{matHeight}, MapSize={mapSize}, CellSize={cellSize}, HMCellSize={hmCellSize}");
                                    
                                    string metaContent = $"{{ \"mapSize\": {mapSize}, \"cellSize\": {cellSize.ToString(CultureInfo.InvariantCulture)}, \"hmCellSize\": {hmCellSize.ToString(CultureInfo.InvariantCulture)}, \"terrainRangeX\": {hmWidth}, \"terrainRangeY\": {hmHeight}, \"landRangeX\": {matWidth}, \"landRangeY\": {matHeight}, \"version\": {oprw.Version} }}";
                                    File.WriteAllText(Path.Combine(mapParsedDir, "meta.json"), metaContent);
                                    File.WriteAllText(Path.Combine(mapWebDir, "meta.json"), metaContent);
                                    
                                    // 1. Export Models String Table (Raw)
                                    if (oprw.Models != null)
                                    {
                                        File.WriteAllLines(Path.Combine(mapRawDir, "models.txt"), oprw.Models);
                                    }
                                    
                                    // 2. Export Material Mask (Raw)
                                    if (wrp.MaterialIndex != null)
                                    {
                                        using (BinaryWriter bw = new BinaryWriter(File.Open(Path.Combine(mapRawDir, "material_mask.bin"), FileMode.Create)))
                                        {
                                            foreach (ushort m in wrp.MaterialIndex) bw.Write(m);
                                        }
                                    }
                                    
                                    // 3. Export Heightmap (Raw)
                                    if (oprw.Elevation != null)
                                    {
                                        using (BinaryWriter bw = new BinaryWriter(File.Open(Path.Combine(mapRawDir, "heightmap.bin"), FileMode.Create)))
                                        {
                                            foreach (float f in oprw.Elevation) bw.Write(f);
                                        }
                                    }

                                    // 4. Export Sound Map (Raw)
                                    if (oprw.SoundMap != null)
                                    {
                                        using (BinaryWriter bw = new BinaryWriter(File.Open(Path.Combine(mapRawDir, "sound_map.bin"), FileMode.Create)))
                                        {
                                            foreach (byte b in oprw.SoundMap) bw.Write(b);
                                        }
                                    }
                                    
                                    // 4.1 Geography
                                    if (oprw.Geography != null)
                                    {
                                        using (BinaryWriter bw = new BinaryWriter(File.Open(Path.Combine(mapRawDir, "geography.bin"), FileMode.Create)))
                                        {
                                            foreach (GeographyInfo m in oprw.Geography) bw.Write((short)m);
                                        }
                                    }
                                    
                                    // 4.2 GrassApprox
                                    if (oprw.GrassApprox != null)
                                    {
                                        using (BinaryWriter bw = new BinaryWriter(File.Open(Path.Combine(mapRawDir, "grass_approx.bin"), FileMode.Create)))
                                        {
                                            foreach (byte b in oprw.GrassApprox) bw.Write(b);
                                        }
                                    }
                                    
                                    // 4.3 PrimTexIndex
                                    if (oprw.PrimTexIndex != null)
                                    {
                                        using (BinaryWriter bw = new BinaryWriter(File.Open(Path.Combine(mapRawDir, "prim_tex.bin"), FileMode.Create)))
                                        {
                                            foreach (byte b in oprw.PrimTexIndex) bw.Write(b);
                                        }
                                    }
                                    
                                    // 4.4 Persistent
                                    if (oprw.Persistent != null)
                                    {
                                        using (BinaryWriter bw = new BinaryWriter(File.Open(Path.Combine(mapRawDir, "persistent.bin"), FileMode.Create)))
                                        {
                                            foreach (byte b in oprw.Persistent) bw.Write(b);
                                        }
                                    }

                                    // 4.5 Random
                                    if (oprw.Random != null)
                                    {
                                        using (BinaryWriter bw = new BinaryWriter(File.Open(Path.Combine(mapRawDir, "random.bin"), FileMode.Create)))
                                        {
                                            foreach (byte b in oprw.Random) bw.Write(b);
                                        }
                                    }

                                    // 5. Export Mountains (Parsed)
                                    if (oprw.Mountains != null)
                                    {
                                        using (StreamWriter sw = new StreamWriter(File.Open(Path.Combine(mapParsedDir, "mountains.json"), FileMode.Create)))
                                        {
                                            sw.WriteLine("{");
                                            sw.WriteLine("  \"mountains\": [");
                                            for (int i = 0; i < oprw.Mountains.Length; i++)
                                            {
                                                var m = oprw.Mountains[i];
                                                sw.Write($"    {{ \"x\": {m.X.ToString(CultureInfo.InvariantCulture)}, \"z\": {m.Z.ToString(CultureInfo.InvariantCulture)} }}");
                                                if (i < oprw.Mountains.Length - 1) sw.WriteLine(",");
                                                else sw.WriteLine();
                                            }
                                            sw.WriteLine("  ]");
                                            sw.WriteLine("}");
                                        }
                                    }
                                    
                                    // 5.5 Roadnet
                                    if (oprw.Roadnet != null)
                                    {
                                        using (StreamWriter sw = new StreamWriter(File.Open(Path.Combine(mapParsedDir, "roadnet.json"), FileMode.Create)))
                                        {
                                            sw.WriteLine("{");
                                            sw.WriteLine("  \"road_links\": [");
                                            bool firstLink = true;
                                            for (int i = 0; i < oprw.Roadnet.Length; i++)
                                            {
                                                if (oprw.Roadnet[i] == null) continue;
                                                for(int j=0; j < oprw.Roadnet[i].Length; j++) 
                                                {
                                                    var rl = oprw.Roadnet[i][j];
                                                    if (!firstLink) sw.WriteLine(",");
                                                    firstLink = false;
                                                    
                                                    sw.Write($"    {{ \"p3d\": \"{rl.P3dPath?.Replace("\\", "\\\\")}\", \"obj_id\": {rl.ObjectID}, \"connections\": {rl.ConnectionCount}, \"positions\": [");
                                                    if(rl.Positions != null) {
                                                        for(int p=0; p<rl.Positions.Length; p++) {
                                                            var pos = rl.Positions[p];
                                                            sw.Write($"[{pos.X.ToString(CultureInfo.InvariantCulture)}, {pos.Y.ToString(CultureInfo.InvariantCulture)}, {pos.Z.ToString(CultureInfo.InvariantCulture)}]");
                                                            if(p < rl.Positions.Length - 1) sw.Write(", ");
                                                        }
                                                    }
                                                    sw.Write("]");
                                                    if (rl.ToWorld != null) {
                                                        float t_x = rl.ToWorld.Matrix.M41;
                                                        float t_y = rl.ToWorld.Matrix.M43;
                                                        float t_z = rl.ToWorld.Matrix.M42;
                                                        float t_yaw = (float)(Math.Atan2(rl.ToWorld.Matrix.M31, rl.ToWorld.Matrix.M33) * 180.0 / Math.PI);
                                                        if (t_yaw < 0) t_yaw += 360.0f;
                                                        sw.Write($", \"transform\": {{ \"x\": {t_x.ToString(CultureInfo.InvariantCulture)}, \"y\": {t_y.ToString(CultureInfo.InvariantCulture)}, \"z\": {t_z.ToString(CultureInfo.InvariantCulture)}, \"dir\": {t_yaw.ToString(CultureInfo.InvariantCulture)} }}");
                                                    }
                                                    sw.Write(" }");
                                                }
                                            }
                                            sw.WriteLine("\n  ]");
                                            sw.WriteLine("}");
                                        }
                                    }

                                    // 6. Export Objects JSON (Parsed + Webtool)
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
                                                if (yaw < 0) yaw += 360.0f;
                                                
                                                if (validCount > 0) sw.WriteLine(",");
                                                
                                                string modelBaseName = Path.GetFileName(obj.Model);
                                                
                                                sw.Write("    {\n");
                                                sw.Write($"      \"class\": \"{obj.Model.Replace("\\", "\\\\")}\",\n");
                                                sw.Write($"      \"model\": \"{modelBaseName}\",\n");
                                                sw.Write($"      \"x\": {x.ToString(CultureInfo.InvariantCulture)},\n");
                                                sw.Write($"      \"y\": {y.ToString(CultureInfo.InvariantCulture)},\n");
                                                sw.Write($"      \"z\": {z.ToString(CultureInfo.InvariantCulture)},\n");
                                                sw.Write($"      \"dir\": {yaw.ToString(CultureInfo.InvariantCulture)},\n");
                                                sw.Write($"      \"w\": 1,\n");
                                                sw.Write($"      \"l\": 1,\n");
                                                sw.Write($"      \"h\": 1\n");
                                                sw.Write("    }");
                                                
                                                validCount++;
                                            }
                                            
                                            sw.WriteLine("\n  ]");
                                            sw.WriteLine("}");
                                        }
                                        
                                        File.Copy(webObjPath, parsedObjPath, true);
                                    }
                                    
                                    // 7. Run Python Script for PNGs
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
                                    using (var process = Process.Start(psi))
                                    {
                                        process.WaitForExit();
                                    }
                                    
                                    // Copy heightmap PNG to web dir
                                    string hmPngSource = Path.Combine(mapParsedDir, "heightmap.png");
                                    string hmPngDest = Path.Combine(mapWebDir, "heightmap.png");
                                    if (File.Exists(hmPngSource)) {
                                        File.Copy(hmPngSource, hmPngDest, true);
                                    }
                                    
                                    Console.WriteLine($"Finished {mapName} successfully.");
                                }
                            }
                        }
                    }
                    
                    // Force GC to prevent OutOfMemory with gigabytes of WRP data
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
    }
}
