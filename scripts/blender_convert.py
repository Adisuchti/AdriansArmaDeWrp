import bpy
import os
import sys
import addon_utils

# Enable Arma Toolbox extension explicitly for background execution
try:
    addon_utils.enable("bl_ext.user_default.ArmaToolbox")
    print("ArmaToolbox extension successfully enabled.")
except Exception as e:
    print(f"Warning enabling ArmaToolbox: {e}")

# Usage: blender --background --python blender_convert.py -- -i "input_dir" -o "output_dir"

def get_args():
    try:
        idx = sys.argv.index("--")
        args = sys.argv[idx+1:]
        input_dir = args[args.index("-i") + 1] if "-i" in args else "mlod_models"
        output_dir = args[args.index("-o") + 1] if "-o" in args else "converted_models"
        return input_dir, output_dir
    except (ValueError, IndexError):
        return "mlod_models", "converted_models"

def clear_scene():
    if bpy.context.object and bpy.context.object.mode != 'OBJECT':
        bpy.ops.object.mode_set(mode='OBJECT')
    bpy.ops.object.select_all(action='SELECT')
    bpy.ops.object.delete()

def process_file(p3d_path, glb_path):
    print(f"Processing: {p3d_path}")
    clear_scene()
    
    # 1. Import P3D using Arma Toolbox operator
    try:
        bpy.ops.armatoolbox.import_p3d(filepath=p3d_path)
    except Exception as e:
        print(f"Failed to import {p3d_path}: {e}")
        return

    # 2. Find LOD Collections (1, 2, 3... N)
    # The Arma Toolbox imports LODs as separate Collections named with their resolution/LOD number
    # Find the lowest detail visual LOD collection.
    # The user specifically requested the HIGHEST numeric LOD (e.g. "4").
    # We first look for collections with purely numeric names that are < 10000 (visual LODs).
    numeric_collections = []
    valid_fallback_collections = []
    
    ignore_keywords = ["shadow", "geometry", "memory", "hit points", "paths", "land contact", "fire", "wreckage", "view", "?", "edit"]
    
    for coll in bpy.data.collections:
        name_lower = coll.name.lower()
        if any(kw in name_lower for kw in ignore_keywords):
            continue
            
        # Count polygons just in case we need the fallback
        poly_count = 0
        has_mesh = False
        for obj in coll.all_objects:
            if obj.type == 'MESH':
                has_mesh = True
                poly_count += len(obj.data.polygons)
                
        if has_mesh:
            valid_fallback_collections.append((poly_count, coll))
            
            # Try to see if this is a numeric LOD (e.g., "1", "2", "3", "4")
            try:
                val = float(coll.name)
                if val < 10000:
                    numeric_collections.append((val, coll))
            except ValueError:
                pass

    target_coll = None

    if numeric_collections:
        # Highest numeric value means lowest detail LOD (e.g. "4" is lower detail than "1")
        numeric_collections.sort(key=lambda x: x[0], reverse=True)
        target_val, target_coll = numeric_collections[0]
        print(f"Selected numeric LOD collection '{target_coll.name}' (N={target_val})")
    elif valid_fallback_collections:
        # Fallback: Sort by polygon count ascending (lowest detail first)
        valid_fallback_collections.sort(key=lambda x: x[0])
        target_poly_count, target_coll = valid_fallback_collections[0]
        print(f"Fallback: Selected LOD collection '{target_coll.name}' with {target_poly_count} polygons")
        
    if target_coll:
        objects_to_keep = set(target_coll.all_objects)
        
        # Delete all meshes NOT in the target collection, keeping armatures/roots
        bpy.ops.object.select_all(action='DESELECT')
        for obj in bpy.context.scene.objects:
            if obj.type == 'MESH' and obj not in objects_to_keep:
                obj.select_set(True)
        bpy.ops.object.delete()
    else:
        print(f"No valid visual LOD collections found for {p3d_path}, exporting whole scene.")

    # 3. Export to GLB
    # Make sure output directory exists
    os.makedirs(os.path.dirname(glb_path), exist_ok=True)
    
    try:
        bpy.ops.export_scene.gltf(
            filepath=glb_path,
            export_format='GLB',
            use_selection=False, # Export everything left in scene
            export_apply=True,
            export_materials='PLACEHOLDER' # Materials won't carry perfectly from P3D anyway
        )
        print(f"Successfully exported to: {glb_path}")
    except Exception as e:
        print(f"Failed to export {glb_path}: {e}")

def main():
    input_path, output_dir = get_args()
    
    if not os.path.exists(input_path):
        print(f"Input path does not exist: {input_path}")
        sys.exit(1)
        
    if os.path.isfile(input_path):
        # Process a single file
        file_name = os.path.basename(input_path)
        glb_filename = os.path.splitext(file_name)[0] + ".glb"
        glb_path = os.path.join(output_dir, glb_filename)
        process_file(input_path, glb_path)
    else:
        # Process a directory
        for root, _, files in os.walk(input_path):
            for file in files:
                if file.lower().endswith(".p3d"):
                    p3d_path = os.path.join(root, file)
                    
                    # Replicate folder structure in output
                    rel_path = os.path.relpath(p3d_path, input_path)
                    glb_filename = os.path.splitext(rel_path)[0] + ".glb"
                    glb_path = os.path.join(output_dir, glb_filename)
                    
                    process_file(p3d_path, glb_path)

if __name__ == "__main__":
    main()
