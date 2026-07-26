import addon_utils

addons = [mod.__name__ for mod in addon_utils.modules()]
print("--- INSTALLED ADDONS ---")
for a in addons:
    if "arma" in a.lower() or "p3d" in a.lower():
        print(f"FOUND MATCH: {a}")
print("--- END ADDONS ---")
