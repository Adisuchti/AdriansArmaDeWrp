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
            new Vector3( 0,  0,  1),
            new Vector3( 0,  0, -1),
            new Vector3( 1,  0,  0),
            new Vector3(-1,  0,  0),
            new Vector3( 0,  1,  0),
            new Vector3( 0, -1,  0),
        };

        private static readonly (int dx, int dy, int dz)[] NeighborOffsets = {
            ( 0,  0,  1),
            ( 0,  0, -1),
            ( 1,  0,  0),
            (-1,  0,  0),
            ( 0,  1,  0),
            ( 0, -1,  0),
        };

        private static readonly (int planeComp, int gridAComp, int gridBComp, int plOffset)[] FaceLayout = {
            (2, 0, 1, 1),
            (2, 0, 1, 0),
            (0, 2, 1, 1),
            (0, 2, 1, 0),
            (1, 0, 2, 1),
            (1, 0, 2, 0),
        };

        static int GetVoxelComponent((int, int, int) v, int comp)
        {
            if (comp == 0) return v.Item1;
            if (comp == 1) return v.Item2;
            return v.Item3;
        }

        public static void ExportToGlb(ModelInfo modelInfo, LOD geometryLod, string outputPath)
        {
            if (geometryLod.Vertices == null || geometryLod.Vertices.Count == 0) return;
            
            float sizeX = modelInfo.BboxMax.X - modelInfo.BboxMin.X;
            float sizeY = modelInfo.BboxMax.Y - modelInfo.BboxMin.Y;
            float sizeZ = modelInfo.BboxMax.Z - modelInfo.BboxMin.Z;
            
            float maxExtent = Math.Max(sizeX, Math.Max(sizeY, sizeZ));
            int divisions = Math.Max(1, (int)Math.Ceiling(maxExtent / TARGET_VOXEL_SIZE));
            float voxelSize = maxExtent / divisions;
            voxelSize = Math.Max(0.05f, Math.Min(10.0f, voxelSize));
            
            var occupiedVoxels = new HashSet<(int, int, int)>();
            
            void AddVoxel(float wx, float wy, float wz)
            {
                int vx = (int)Math.Floor(wx / voxelSize);
                int vy = (int)Math.Floor(wy / voxelSize);
                int vz = (int)Math.Floor(wz / voxelSize);
                occupiedVoxels.Add((vx, vy, vz));
            }
            
            // Voxelize vertices
            foreach (var v in geometryLod.Vertices)
                AddVoxel(v.X, v.Y, v.Z);
            
            // Voxelize triangle surfaces — dense sampling for thin/curved surfaces
            if (geometryLod.Polygons != null && geometryLod.Polygons.Faces != null)
            {
                foreach (var face in geometryLod.Polygons.Faces)
                {
                    if (face.VertexIndices.Length >= 3)
                    {
                        for (int i = 1; i < face.VertexIndices.Length - 1; i++)
                        {
                            var tv0 = geometryLod.Vertices[face.VertexIndices[0]];
                            var tv1 = geometryLod.Vertices[face.VertexIndices[i]];
                            var tv2 = geometryLod.Vertices[face.VertexIndices[i + 1]];
                            
                            Vector3 p0 = new Vector3(tv0.X, tv0.Y, tv0.Z);
                            Vector3 p1 = new Vector3(tv1.X, tv1.Y, tv1.Z);
                            Vector3 p2 = new Vector3(tv2.X, tv2.Y, tv2.Z);
                            
                            float step = Math.Max(0.05f, voxelSize / 8.0f);
                            Vector3 v01 = p1 - p0;
                            Vector3 v02 = p2 - p0;
                            
                            int steps01 = Math.Max(1, (int)Math.Ceiling(v01.Length() / step));
                            int steps02 = Math.Max(1, (int)Math.Ceiling(v02.Length() / step));
                            
                            for (int si = 0; si <= steps01; si++)
                            {
                                float u = (float)si / steps01;
                                for (int sj = 0; sj <= steps02; sj++)
                                {
                                    float vv = (float)sj / steps02;
                                    if (u + vv <= 1.0f)
                                    {
                                        Vector3 p = p0 + (u * v01) + (vv * v02);
                                        AddVoxel(p.X, p.Y, p.Z);
                                    }
                                }
                            }
                        }
                    }
                }
            }
            
            // Greedy mesh building: only cull faces between adjacent occupied voxels
            var material = new MaterialBuilder("VoxelMat")
                .WithBaseColor(new Vector4(0.5f, 0.5f, 0.5f, 1.0f))
                .WithMetallicRoughness(0.5f, 0.5f);
            var meshBuilder = new MeshBuilder<VertexPositionNormal>("VoxelMesh");
            var prim = meshBuilder.UsePrimitive(material);
            
            var vertList = new List<VertexPositionNormal>();
            var uniqueVerts = new Dictionary<(Vector3 pos, Vector3 norm), int>();
            
            VertexPositionNormal GetOrAddVertex(Vector3 pos, Vector3 norm)
            {
                var key = (pos, norm);
                if (uniqueVerts.TryGetValue(key, out int idx))
                    return vertList[idx];
                var vert = new VertexPositionNormal(pos, norm);
                int newIdx = vertList.Count;
                uniqueVerts[key] = newIdx;
                vertList.Add(vert);
                return vert;
            }
            
            var planeFaces = new Dictionary<int, Dictionary<int, HashSet<(int, int)>>>();
            for (int fi = 0; fi < 6; fi++)
                planeFaces[fi] = new Dictionary<int, HashSet<(int, int)>>();
            
            foreach (var voxel in occupiedVoxels)
            {
                int vx = voxel.Item1, vy = voxel.Item2, vz = voxel.Item3;
                for (int fi = 0; fi < 6; fi++)
                {
                    var off = NeighborOffsets[fi];
                    var neighbor = (vx + off.dx, vy + off.dy, vz + off.dz);
                    
                    // Only cull face if neighbor voxel is also occupied
                    if (occupiedVoxels.Contains(neighbor))
                        continue;
                    
                    var layout = FaceLayout[fi];
                    int planeCoord = GetVoxelComponent(voxel, layout.planeComp);
                    int gx = GetVoxelComponent(voxel, layout.gridAComp);
                    int gy = GetVoxelComponent(voxel, layout.gridBComp);
                    
                    if (!planeFaces[fi].TryGetValue(planeCoord, out var grid))
                    {
                        grid = new HashSet<(int, int)>();
                        planeFaces[fi][planeCoord] = grid;
                    }
                    grid.Add((gx, gy));
                }
            }
            
            for (int fi = 0; fi < 6; fi++)
            {
                var normal = FaceNormals[fi];
                foreach (var kvp in planeFaces[fi])
                {
                    int planeCoord = kvp.Key;
                    var gridSet = kvp.Value;
                    if (gridSet.Count == 0) continue;
                    
                    int minGX = int.MaxValue, maxGX = int.MinValue;
                    int minGY = int.MaxValue, maxGY = int.MinValue;
                    foreach (var pt in gridSet)
                    {
                        if (pt.Item1 < minGX) minGX = pt.Item1;
                        if (pt.Item1 > maxGX) maxGX = pt.Item1;
                        if (pt.Item2 < minGY) minGY = pt.Item2;
                        if (pt.Item2 > maxGY) maxGY = pt.Item2;
                    }
                    
                    int gridW = maxGX - minGX + 1;
                    int gridH = maxGY - minGY + 1;
                    bool[,] visited = new bool[gridW, gridH];
                    
                    for (int gy = minGY; gy <= maxGY; gy++)
                    {
                        for (int gx = minGX; gx <= maxGX; gx++)
                        {
                            int li = gx - minGX, lj = gy - minGY;
                            if (li < 0 || li >= gridW || lj < 0 || lj >= gridH) continue;
                            if (visited[li, lj]) continue;
                            if (!gridSet.Contains((gx, gy))) continue;
                            
                            int w = 1;
                            while (gx + w <= maxGX)
                            {
                                int ni = (gx + w) - minGX;
                                if (ni >= gridW || visited[ni, lj] || !gridSet.Contains((gx + w, gy)))
                                    break;
                                w++;
                            }
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
                                    { canExpand = false; break; }
                                }
                                if (canExpand) h++;
                            }
                            
                            for (int dy = 0; dy < h; dy++)
                                for (int dx = 0; dx < w; dx++)
                                {
                                    int ni = (gx + dx) - minGX;
                                    int nj = (gy + dy) - minGY;
                                    if (ni >= 0 && ni < gridW && nj >= 0 && nj < gridH)
                                        visited[ni, nj] = true;
                                }
                            
                            EmitMergedQuad(fi, normal, planeCoord, gx, gy, w, h, voxelSize, GetOrAddVertex, prim);
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
            int fi, Vector3 normal, int planeCoord,
            int gx, int gy, int w, int h, float vs,
            Func<Vector3, Vector3, VertexPositionNormal> getOrAddVertex,
            PrimitiveBuilder<MaterialBuilder, VertexPositionNormal, VertexEmpty, VertexEmpty> prim)
        {
            float planePos = (planeCoord + (fi % 2 == 0 ? 1 : 0)) * vs;
            float gA0 = gx * vs, gA1 = (gx + w) * vs;
            float gB0 = gy * vs, gB1 = (gy + h) * vs;
            Vector3 a, b, c, d;
            
            switch (fi)
            {
                case 0: a = new Vector3(gA0, gB0, planePos); b = new Vector3(gA1, gB0, planePos); c = new Vector3(gA1, gB1, planePos); d = new Vector3(gA0, gB1, planePos); break;
                case 1: a = new Vector3(gA1, gB0, planePos); b = new Vector3(gA0, gB0, planePos); c = new Vector3(gA0, gB1, planePos); d = new Vector3(gA1, gB1, planePos); break;
                case 2: a = new Vector3(planePos, gB0, gA1); b = new Vector3(planePos, gB0, gA0); c = new Vector3(planePos, gB1, gA0); d = new Vector3(planePos, gB1, gA1); break;
                case 3: a = new Vector3(planePos, gB0, gA0); b = new Vector3(planePos, gB0, gA1); c = new Vector3(planePos, gB1, gA1); d = new Vector3(planePos, gB1, gA0); break;
                case 4: a = new Vector3(gA0, planePos, gB1); b = new Vector3(gA1, planePos, gB1); c = new Vector3(gA1, planePos, gB0); d = new Vector3(gA0, planePos, gB0); break;
                case 5: a = new Vector3(gA0, planePos, gB0); b = new Vector3(gA1, planePos, gB0); c = new Vector3(gA1, planePos, gB1); d = new Vector3(gA0, planePos, gB1); break;
                default: return;
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