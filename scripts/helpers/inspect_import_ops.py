import bpy
import addon_utils

try:
    addon_utils.enable("bl_ext.user_default.ArmaToolbox", default_set=True)
    print("Enabled addon!")
except Exception as e:
    print("Error enabling:", e)

print("--- IMPORT OPERATORS ---")
for op in dir(bpy.ops.import_scene):
    print(f"import_scene.{op}")

print("--- ARMA OPERATORS ---")
for category in dir(bpy.ops):
    cat_obj = getattr(bpy.ops, category)
    for op in dir(cat_obj):
        if "arma" in op.lower() or "p3d" in op.lower():
            print(f"{category}.{op}")
print("--- END ---")
