using System;
using System.Collections.Generic;
using System.IO;
using System.Numerics;
using SharpGLTF.Geometry;
using SharpGLTF.Geometry.VertexTypes;
using SharpGLTF.Materials;
using SharpGLTF.Scenes;
using BIS.P3D.ODOL;

namespace WrpAnalyzer
{
    public static class Voxelizer
    {
        private const float TARGET_VOXEL_SIZE = 0.5f;

        private static readonly Vector3[] FaceNormals = {
            new Vector3( 0,  0,  1), // Front  (+Z)
            new Vector3( 0,  0, -1), // Back   (-Z)
            new Vector3( 1,  0,  0), // Right  (+X)
            new Vector3(-1,  0,  0), // Left   (-X)
            new Vector3( 0,  1,  0), // Top    (+Y)
            new Vector3( 0, -1,  0), // Bottom (-Y)
        };

        private static readonly (int dx, int dy, int dz)[] NeighborOffsets = {
            ( 0,  0,  1), // Front
            ( 0,  0, -1), // Back
            ( 1,  0,  0), // Right
            (-1,  0,  0), // Left
            ( 0,  1,  0), // Top
            ( 0, -1,  0), // Bottom
        };

        /// <summary>
        /// For each face direction: (planeVoxelComponent, gridAComponent, gridBComponent, planeOffset).
        /// planeVoxelComponent: 0=x, 1=y, 2=z — which voxel tuple component is the face normal axis.
        /// gridA/gridB: which voxel tuple components are the 2D grid axes.
        /// planeOffset: 0 for negative normal, 1 for positive normal (which edge of the voxel).
        /// </summary>
        private static readonly (int planeComp, int gridAComp, int gridBComp, int plOffset)[] FaceLayout = {
            (2, 0, 1, 1), // Front  (+Z): plane=z, gridA=x, gridB=y, offset=1
            (2, 0, 1, 0), // Back   (-Z): plane=z, gridA=x, gridB=y, offset=0
            (0, 2, 1, 1), // Right  (+X): plane=x, gridA=z, gridB=y, offset=1
            (0, 2, 1, 0), // Left   (-X): plane=x, gridA=z, gridB=y, offset=0
            (1, 0, 2, 1), // Top    (+Y): plane=y, gridA=x, gridB=z, offset=1
            (1, 0, 2, 0), // Bottom (-Y): plane=y, gridA=x, gridB=z, offset=0
        };

        static int GetVoxelComponent((int, int, int) v, int comp)
        {
            return comp switch
            {
                0 => v.Item1,
                1 => v.Item2,
                2 => v.Item3,
                _ => 0
            };
        }

        public static void ExportToGlb(ModelInfo modelInfo, LOD geometryLod, string outputPath)
        {
            if (geometryLod.Vertices == null || geometryLod.Vertices.Count == 0) return;
            
            float sizeX = modelInfo.BboxMax.X - modelInfo.BboxMin.X;
            float sizeY = modelInfo.BboxMax.Y - modelInfo.BboxMin.Y;
            float sizeZ = modelInfo.BboxMax.Z - modelInfo.BboxMin.Z;
            
            float maxExtent = Math.Max(sizeX, Math.Max(sizeY, sizeZ));
            // Proportional voxel sizing: all voxels aim for ~0.5m in world space
            int divisions = Math.Max(1, (int)Math.Ceiling(maxExtent / TARGET_VOXEL_SIZE));
            float voxelSize = maxExtent / divisions;
            // Clamp extremes
            voxelSize = Math.Max(0.05f, Math.Min(10.0f, voxelSize));
            
            HashSet<(int, int, int)> occupiedVoxels = new HashSet<(int, int, int)>();
            
            void AddVoxel(float x, float y, float z)
            {
                int vx = (int)Math.Floor(x / voxelSize);
                int vy = (int)Math.Floor(y / voxelSize);
                int vz = (int)Math.Floor(z / voxelSize);
                occupiedVoxels.Add((vx, vy, vz));
            }
            
            // Voxelize vertices directly
            foreach (var v in geometryLod.Vertices)
            {
                AddVoxel(v.X, v.Y, v.Z);
            }
            
            // Voxelize triangle surfaces via barycentric sampling
            if (geometryLod.Polygons != null && geometryLod.Polygons.Faces != null)
            {
                foreach (var face in geometryLod.Polygons.Faces)
                {
                    if (face.VertexIndices.Length >= 3)
                    {
                        for (int i = 1; i < face.VertexIndices.Length - 1; i++)
                        {
                            var v0 = geometryLod.Vertices[face.VertexIndices[0]];
                            var v1 = geometryLod.Vertices[face.VertexIndices[i]];
                            var v2 = geometryLod.Vertices[face.VertexIndices[i + 1]];
                            
                            Vector3 p0 = new Vector3(v0.X, v0.Y, v0.Z);
                            Vector3 p1 = new Vector3(v1.X, v1.Y, v1.Z);
                            Vector3 p2 = new Vector3(v2.X, v2.Y, v2.Z);
                            
                            float step = voxelSize / 2.0f;
                            Vector3 v01 = p1 - p0;
                            Vector3 v02 = p2 - p0;
                            
                            float len01 = v01.Length();
                            float len02 = v02.Length();
                            
                            int steps01 = Math.Max(1, (int)Math.Ceiling(len01 / step));
                            int steps02 = Math.Max(1, (int)Math.Ceiling(len02 / step));
                            
                            for (int si = 0; si <= steps01; si++)
                            {
                                float u = (float)si / steps01;
                                for (int sj = 0; sj <= steps02; sj++)
                                {
                                    float vVal = (float)sj / steps02;
                                    if (u + vVal <= 1.0f)
                                    {
                                        Vector3 p = p0 + (u * v01) + (vVal * v02);
                                        AddVoxel(p.X, p.Y, p.Z);
                                    }
                                }
                            }
                        }
                    }
                }
            }
            
            // ---- Greedy mesh building with face culling and vertex deduplication ----
            var material = new MaterialBuilder("VoxelMat")
                .WithBaseColor(new Vector4(0.5f, 0.5f, 0.5f, 1.0f))
                .WithMetallicRoughness(0.5f, 0.5f);
                
            var meshBuilder = new MeshBuilder<VertexPositionNormal>("VoxelMesh");
            var prim = meshBuilder.UsePrimitive(material);
            
            var vertList = new List<VertexPositionNormal>();
            var uniqueVerts = new Dictionary<(Vector3 pos, Vector3 norm), int>();
            
            VertexPositionNormal GetOrAddVertex(Vector3 pos, Vector3 normal)
            {
                var key = (pos, normal);
                if (uniqueVerts.TryGetValue(key, out int idx))
                    return vertList[idx];
                var vert = new VertexPositionNormal(pos, normal);
                int newIdx = vertList.Count;
                uniqueVerts[key] = newIdx;
                vertList.Add(vert);
                return vert;
            }
            
            // Group external faces by (faceIndex, planeCoordinate) → set of 2D grid positions
            // planeFaces[fi][planeCoord] = HashSet<(gx, gy)>
            var planeFaces = new Dictionary<int, Dictionary<int, HashSet<(int, int)>>>();
            for (int fi = 0; fi < 6; fi++)
                planeFaces[fi] = new Dictionary<int, HashSet<(int, int)>>();
            
            foreach (var voxel in occupiedVoxels)
            {
                for (int fi = 0; fi < 6; fi++)
                {
                    var offset = NeighborOffsets[fi];
                    int nx = voxel.Item1 + offset.dx;
                    int ny = voxel.Item2 + offset.dy;
                    int nz = voxel.Item3 + offset.dz;
                    
                    // Face culling: skip if neighbor occupied
                    if (occupiedVoxels.Contains((nx, ny, nz)))
                        continue;
                    
                    var layout = FaceLayout[fi];
                    int planeCoord = GetVoxelComponent(voxel, layout.planeComp);
                    int gx = GetVoxelComponent(voxel, layout.gridAComp);
                    int gy = GetVoxelComponent(voxel, layout.gridBComp);
                    
                    var planes = planeFaces[fi];
                    if (!planes.TryGetValue(planeCoord, out var grid))
                    {
                        grid = new HashSet<(int, int)>();
                        planes[planeCoord] = grid;
                    }
                    grid.Add((gx, gy));
                }
            }
            
            // For each plane, run greedy mesh simplification
            for (int fi = 0; fi < 6; fi++)
            {
                var layout = FaceLayout[fi];
                var normal = FaceNormals[fi];
                
                foreach (var kvp in planeFaces[fi])
                {
                    int planeCoord = kvp.Key;
                    var gridSet = kvp.Value;
                    if (gridSet.Count == 0) continue;
                    
                    // Compute bounding box of the grid
                    int minGX = int.MaxValue, maxGX = int.MinValue;
                    int minGY = int.MaxValue, maxGY = int.MinValue;
                    foreach (var (gx, gy) in gridSet)
                    {
                        if (gx < minGX) minGX = gx;
                        if (gx > maxGX) maxGX = gx;
                        if (gy < minGY) minGY = gy;
                        if (gy > maxGY) maxGY = gy;
                    }
                    
                    int gridW = maxGX - minGX + 1;
                    int gridH = maxGY - minGY + 1;
                    
                    // visited[i, j] where i = gx - minGX, j = gy - minGY
                    bool[,] visited = new bool[gridW, gridH];
                    
                    // Greedy merge
                    for (int gy = minGY; gy <= maxGY; gy++)
                    {
                        for (int gx = minGX; gx <= maxGX; gx++)
                        {
                            int li = gx - minGX;
                            int lj = gy - minGY;
                            if (li < 0 || li >= gridW || lj < 0 || lj >= gridH) continue;
                            if (visited[li, lj]) continue;
                            if (!gridSet.Contains((gx, gy))) continue;
                            
                            // Expand right as far as possible
                            int w = 1;
                            while (gx + w <= maxGX)
                            {
                                int ni = (gx + w) - minGX;
                                if (ni >= gridW || visited[ni, lj] || !gridSet.Contains((gx + w, gy)))
                                    break;
                                w++;
                            }
                            
                            // Expand down as far as possible (all rows must have full width)
                            int h = 1;
                            bool canExpand = true;
                            while (gy + h <= maxGY && canExpand)
                            {
                                for (int dx = 0; dx < w; dx++)
                                {
                                    int ni = (gx + dx) - minGX;
                                    int nj = (gy + h) - minGY;
                                    if (ni < 0 || ni >= gridW || nj < 0 || nj >= gridH ||
                                        visited[ni, nj] || !gridSet.Contains((gx + dx, gy + h)))
                                    {
                                        canExpand = false;
                                        break;
                                    }
                                }
                                if (canExpand) h++;
                            }
                            
                            // Mark region as visited
                            for (int dy = 0; dy < h; dy++)
                            {
                                for (int dx = 0; dx < w; dx++)
                                {
                                    int ni = (gx + dx) - minGX;
                                    int nj = (gy + dy) - minGY;
                                    if (ni >= 0 && ni < gridW && nj >= 0 && nj < gridH)
                                        visited[ni, nj] = true;
                                }
                            }
                            
                            // Emit merged quad
                            EmitMergedQuad(fi, layout, normal, planeCoord, gx, gy, w, h, voxelSize, GetOrAddVertex, prim);
                        }
                    }
                }
            }
            
            var scene = new SceneBuilder();
            scene.AddRigidMesh(meshBuilder, Matrix4x4.Identity);
            var model = scene.ToGltf2();
            model.SaveGLB(outputPath);
        }
        
        private static void EmitMergedQuad(
            int fi,
            (int planeComp, int gridAComp, int gridBComp, int plOffset) layout,
            Vector3 normal,
            int planeCoord,
            int gx, int gy, int w, int h,
            float voxelSize,
            Func<Vector3, Vector3, VertexPositionNormal> getOrAddVertex,
            PrimitiveBuilder<MaterialBuilder, VertexPositionNormal, VertexEmpty, VertexEmpty> prim)
        {
            float vs = voxelSize;
            float planePos = (planeCoord + layout.plOffset) * vs;
            float gridAMin = gx * vs;
            float gridAMax = (gx + w) * vs;
            float gridBMin = gy * vs;
            float gridBMax = (gy + h) * vs;
            
            Vector3 a, b, c, d;
            
            // Build the 4 corners based on face direction, matching original winding order
            switch (fi)
            {
                case 0: // Front (+Z): plane=Z, gridA=X, gridB=Y
                    a = new Vector3(gridAMin, gridBMin, planePos);
                    b = new Vector3(gridAMax, gridBMin, planePos);
                    c = new Vector3(gridAMax, gridBMax, planePos);
                    d = new Vector3(gridAMin, gridBMax, planePos);
                    break;
                case 1: // Back (-Z): plane=Z, gridA=X, gridB=Y
                    a = new Vector3(gridAMax, gridBMin, planePos);
                    b = new Vector3(gridAMin, gridBMin, planePos);
                    c = new Vector3(gridAMin, gridBMax, planePos);
                    d = new Vector3(gridAMax, gridBMax, planePos);
                    break;
                case 2: // Right (+X): plane=X, gridA=Z, gridB=Y
                    a = new Vector3(planePos, gridBMin, gridAMax);
                    b = new Vector3(planePos, gridBMin, gridAMin);
                    c = new Vector3(planePos, gridBMax, gridAMin);
                    d = new Vector3(planePos, gridBMax, gridAMax);
                    break;
                case 3: // Left (-X): plane=X, gridA=Z, gridB=Y
                    a = new Vector3(planePos, gridBMin, gridAMin);
                    b = new Vector3(planePos, gridBMin, gridAMax);
                    c = new Vector3(planePos, gridBMax, gridAMax);
                    d = new Vector3(planePos, gridBMax, gridAMin);
                    break;
                case 4: // Top (+Y): plane=Y, gridA=X, gridB=Z
                    a = new Vector3(gridAMin, planePos, gridBMax);
                    b = new Vector3(gridAMax, planePos, gridBMax);
                    c = new Vector3(gridAMax, planePos, gridBMin);
                    d = new Vector3(gridAMin, planePos, gridBMin);
                    break;
                case 5: // Bottom (-Y): plane=Y, gridA=X, gridB=Z
                    a = new Vector3(gridAMin, planePos, gridBMin);
                    b = new Vector3(gridAMax, planePos, gridBMin);
                    c = new Vector3(gridAMax, planePos, gridBMax);
                    d = new Vector3(gridAMin, planePos, gridBMax);
                    break;
                default:
                    return;
            }
            
            var va = getOrAddVertex(a, normal);
            var vb = getOrAddVertex(b, normal);
            var vc = getOrAddVertex(c, normal);
            var vd = getOrAddVertex(d, normal);
            
            prim.AddTriangle(va, vb, vc);
            prim.AddTriangle(va, vc, vd);
        }
    }
}