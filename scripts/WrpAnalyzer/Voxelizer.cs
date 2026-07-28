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
        private static readonly Vector3[] FaceNormals = {
            new Vector3( 0,  0,  1), // Front
            new Vector3( 0,  0, -1), // Back
            new Vector3( 1,  0,  0), // Right
            new Vector3(-1,  0,  0), // Left
            new Vector3( 0,  1,  0), // Top
            new Vector3( 0, -1,  0), // Bottom
        };

        private static readonly (int dx, int dy, int dz)[] NeighborOffsets = {
            ( 0,  0,  1), // Front
            ( 0,  0, -1), // Back
            ( 1,  0,  0), // Right
            (-1,  0,  0), // Left
            ( 0,  1,  0), // Top
            ( 0, -1,  0), // Bottom
        };

        public static void ExportToGlb(ModelInfo modelInfo, LOD geometryLod, string outputPath)
        {
            if (geometryLod.Vertices == null || geometryLod.Vertices.Count == 0) return;
            
            float sizeX = modelInfo.BboxMax.X - modelInfo.BboxMin.X;
            float sizeY = modelInfo.BboxMax.Y - modelInfo.BboxMin.Y;
            float sizeZ = modelInfo.BboxMax.Z - modelInfo.BboxMin.Z;
            
            float maxExtent = Math.Max(sizeX, Math.Max(sizeY, sizeZ));
            // Doubled voxel resolution: divide by 40 instead of 20
            float voxelSize = Math.Max(0.05f, Math.Min(10.0f, maxExtent / 40.0f));
            
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
            
            // Build geometry with face culling and vertex deduplication
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
            
            foreach (var voxel in occupiedVoxels)
            {
                float cx = voxel.Item1 * voxelSize + (voxelSize / 2f);
                float cy = voxel.Item2 * voxelSize + (voxelSize / 2f);
                float cz = voxel.Item3 * voxelSize + (voxelSize / 2f);
                float hs = voxelSize / 2f;
                
                Vector3 center = new Vector3(cx, cy, cz);
                
                // Check all 6 faces — only emit if neighbor voxel is absent
                for (int fi = 0; fi < 6; fi++)
                {
                    var offset = NeighborOffsets[fi];
                    int nx = voxel.Item1 + offset.dx;
                    int ny = voxel.Item2 + offset.dy;
                    int nz = voxel.Item3 + offset.dz;
                    
                    if (occupiedVoxels.Contains((nx, ny, nz)))
                        continue;
                    
                    var normal = FaceNormals[fi];
                    float h = hs;
                    
                    Vector3 a, b, c, d;
                    switch (fi)
                    {
                        case 0: // Front (+Z)
                            a = center + new Vector3(-h, -h,  h);
                            b = center + new Vector3( h, -h,  h);
                            c = center + new Vector3( h,  h,  h);
                            d = center + new Vector3(-h,  h,  h);
                            break;
                        case 1: // Back (-Z)
                            a = center + new Vector3( h, -h, -h);
                            b = center + new Vector3(-h, -h, -h);
                            c = center + new Vector3(-h,  h, -h);
                            d = center + new Vector3( h,  h, -h);
                            break;
                        case 2: // Right (+X)
                            a = center + new Vector3( h, -h,  h);
                            b = center + new Vector3( h, -h, -h);
                            c = center + new Vector3( h,  h, -h);
                            d = center + new Vector3( h,  h,  h);
                            break;
                        case 3: // Left (-X)
                            a = center + new Vector3(-h, -h, -h);
                            b = center + new Vector3(-h, -h,  h);
                            c = center + new Vector3(-h,  h,  h);
                            d = center + new Vector3(-h,  h, -h);
                            break;
                        case 4: // Top (+Y)
                            a = center + new Vector3(-h,  h,  h);
                            b = center + new Vector3( h,  h,  h);
                            c = center + new Vector3( h,  h, -h);
                            d = center + new Vector3(-h,  h, -h);
                            break;
                        case 5: // Bottom (-Y)
                            a = center + new Vector3(-h, -h, -h);
                            b = center + new Vector3( h, -h, -h);
                            c = center + new Vector3( h, -h,  h);
                            d = center + new Vector3(-h, -h,  h);
                            break;
                        default:
                            continue;
                    }
                    
                    var va = GetOrAddVertex(a, normal);
                    var vb = GetOrAddVertex(b, normal);
                    var vc = GetOrAddVertex(c, normal);
                    var vd = GetOrAddVertex(d, normal);
                    
                    prim.AddTriangle(va, vb, vc);
                    prim.AddTriangle(va, vc, vd);
                }
            }
            
            var scene = new SceneBuilder();
            scene.AddRigidMesh(meshBuilder, Matrix4x4.Identity);
            var model = scene.ToGltf2();
            model.SaveGLB(outputPath);
        }
    }
}