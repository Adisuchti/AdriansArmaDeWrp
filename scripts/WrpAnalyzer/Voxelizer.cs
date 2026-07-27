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
        public static void ExportToGlb(ModelInfo modelInfo, LOD geometryLod, string outputPath)
        {
            if (geometryLod.Vertices == null || geometryLod.Vertices.Count == 0) return;
            
            float sizeX = modelInfo.BboxMax.X - modelInfo.BboxMin.X;
            float sizeY = modelInfo.BboxMax.Y - modelInfo.BboxMin.Y;
            float sizeZ = modelInfo.BboxMax.Z - modelInfo.BboxMin.Z;
            
            float maxExtent = Math.Max(sizeX, Math.Max(sizeY, sizeZ));
            float voxelSize = Math.Max(0.1f, Math.Min(10.0f, maxExtent / 20.0f));
            
            HashSet<(int, int, int)> occupiedVoxels = new HashSet<(int, int, int)>();
            
            void AddVoxel(float x, float y, float z)
            {
                int vx = (int)Math.Floor(x / voxelSize);
                int vy = (int)Math.Floor(y / voxelSize);
                int vz = (int)Math.Floor(z / voxelSize);
                occupiedVoxels.Add((vx, vy, vz));
            }
            
            foreach (var v in geometryLod.Vertices)
            {
                AddVoxel(v.X, v.Y, v.Z);
            }
            
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
                                    float v = (float)sj / steps02;
                                    if (u + v <= 1.0f)
                                    {
                                        Vector3 p = p0 + (u * v01) + (v * v02);
                                        AddVoxel(p.X, p.Y, p.Z);
                                    }
                                }
                            }
                        }
                    }
                }
            }
            
            var material = new MaterialBuilder("VoxelMat")
                .WithBaseColor(new Vector4(0.5f, 0.5f, 0.5f, 1.0f))
                .WithMetallicRoughness(0.5f, 0.5f);
                
            var meshBuilder = new MeshBuilder<VertexPositionNormal>("VoxelMesh");
            var prim = meshBuilder.UsePrimitive(material);
            
            void AddQuad(Vector3 a, Vector3 b, Vector3 c, Vector3 d, Vector3 normal)
            {
                var va = new VertexPositionNormal(a, normal);
                var vb = new VertexPositionNormal(b, normal);
                var vc = new VertexPositionNormal(c, normal);
                var vd = new VertexPositionNormal(d, normal);
                
                prim.AddTriangle(va, vb, vc);
                prim.AddTriangle(va, vc, vd);
            }
            
            void AddCube(Vector3 center, float size)
            {
                float hs = size / 2f;
                
                Vector3 v0 = center + new Vector3(-hs, -hs, -hs);
                Vector3 v1 = center + new Vector3( hs, -hs, -hs);
                Vector3 v2 = center + new Vector3( hs,  hs, -hs);
                Vector3 v3 = center + new Vector3(-hs,  hs, -hs);
                Vector3 v4 = center + new Vector3(-hs, -hs,  hs);
                Vector3 v5 = center + new Vector3( hs, -hs,  hs);
                Vector3 v6 = center + new Vector3( hs,  hs,  hs);
                Vector3 v7 = center + new Vector3(-hs,  hs,  hs);
                
                AddQuad(v4, v5, v6, v7, new Vector3(0, 0, 1));  // Front
                AddQuad(v1, v0, v3, v2, new Vector3(0, 0, -1)); // Back
                AddQuad(v5, v1, v2, v6, new Vector3(1, 0, 0));  // Right
                AddQuad(v0, v4, v7, v3, new Vector3(-1, 0, 0)); // Left
                AddQuad(v7, v6, v2, v3, new Vector3(0, 1, 0));  // Top
                AddQuad(v0, v1, v5, v4, new Vector3(0, -1, 0)); // Bottom
            }
            
            foreach (var voxel in occupiedVoxels)
            {
                float cx = voxel.Item1 * voxelSize + (voxelSize / 2f);
                float cy = voxel.Item2 * voxelSize + (voxelSize / 2f);
                float cz = voxel.Item3 * voxelSize + (voxelSize / 2f);
                
                AddCube(new Vector3(cx, cy, cz), voxelSize);
            }
            
            var scene = new SceneBuilder();
            scene.AddRigidMesh(meshBuilder, Matrix4x4.Identity);
            var model = scene.ToGltf2();
            model.SaveGLB(outputPath);
        }
    }
}
