#!/usr/bin/env python3
"""
Matches mission entity classnames to actual P3D filenames by searching
the PBO index that WrpAnalyzer has already built.

Usage: python match_models.py <exports_dir> <entities.json or classname_list>
"""

import sys
import os
import json
import struct
import re
from pathlib import Path


def index_pbos(arma_dirs: list) -> dict:
    """Index all P3D files from PBOs in the given directories."""
    # We'll parse the WrpAnalyzer output or do a quick scan
    # For simplicity, we use the PBO files directly
    all_p3ds = {}
    
    for arma_dir in arma_dirs:
        if not os.path.isdir(arma_dir):
            continue
        addons = os.path.join(arma_dir, "Addons")
        if not os.path.isdir(addons):
            continue
        
        pbo_files = list(Path(arma_dir).rglob("*.pbo"))
        for pbo_path in pbo_files:
            try:
                # Quick scan: read the PBO header to find file entries
                # PBO format: header + file entries + data
                with open(pbo_path, 'rb') as f:
                    data = f.read()
                
                # Find .p3d entries in the PBO
                # Simple string search for .p3d\0 patterns
                pos = 0
                while True:
                    idx = data.find(b'.p3d', pos)
                    if idx == -1:
                        break
                    # Go backwards to find start of filename
                    start = idx
                    while start > 0 and data[start - 1] != 0:
                        start -= 1
                    if start < idx:
                        filename = data[start:idx + 4].decode('ascii', errors='replace')
                        filename = filename.lstrip('\\/')
                        # Extract just the basename
                        basename = filename.replace('\\', '/').split('/')[-1]
                        if basename.endswith('.p3d'):
                            all_p3ds[basename.lower()] = basename
                    pos = idx + 4
                    if pos >= len(data):
                        break
            except Exception:
                continue
    
    return all_p3ds


def load_p3d_cache(cache_file: str) -> dict:
    """Load a previously built P3D cache, or build and save it."""
    if os.path.exists(cache_file):
        with open(cache_file, 'r') as f:
            return json.load(f)
    return None


def save_p3d_cache(cache_file: str, p3ds: dict):
    with open(cache_file, 'w') as f:
        json.dump(p3ds, f, indent=2)


def fuzzy_match(classname: str, p3d_index: dict) -> str:
    """Try to find the correct P3D filename for a given classname."""
    
    # Known direct mappings for common cases
    HARCODED = {
        # Characters (all use the same template)
        'B_Soldier_F': 'Male.p3d',
        'B_Soldier_SL_F': 'Male.p3d',
        'B_Soldier_TL_F': 'Male.p3d',
        'B_Soldier_AR_F': 'Male.p3d',
        'B_Soldier_A_F': 'Male.p3d',
        'B_Soldier_LAT_F': 'Male.p3d',
        'B_Soldier_M_F': 'Male.p3d',
        'B_soldier_AR_F': 'Male.p3d',
        'B_soldier_LAT_F': 'Male.p3d',
        'B_soldier_M_F': 'Male.p3d',
        'B_medic_F': 'Male.p3d',
        'B_crew_F': 'Male.p3d',
        'B_helicrew_F': 'Male.p3d',
        'B_Helipilot_F': 'Male.p3d',
        'B_Fighter_Pilot_F': 'Male.p3d',
        'O_Soldier_F': 'Male.p3d',
        'I_Soldier_F': 'Male.p3d',
    }
    
    if classname in HARCODED:
        return HARCODED[classname]
    
    # For character types (infantry), always use Male.p3d
    # Pattern: B_Soldier_, B_crew_, B_Helipilot_, B_helicrew_, B_medic_, B_Fighter_Pilot_
    if re.match(r'^[BOIC]_', classname):
        if any(x in classname for x in ['Soldier', 'crew', 'medic', 'Helipilot', 'helicrew', 'Fighter_Pilot', 'Pilot']):
            if '_F' in classname and not any(x in classname.split('_')[-1] for x in ['Transport', 'Heli', 'MBT', 'Plane', 'Tank']):
                return 'Male.p3d'
    
    # STRATEGY 1: Exact match with .p3d
    exact = classname + '.p3d'
    if exact.lower() in p3d_index:
        return p3d_index[exact.lower()]
    
    # STRATEGY 2: Strip faction prefix (B_, O_, I_, C_, Land_)
    stripped = re.sub(r'^(B_|O_|I_|C_|Land_)', '', classname) + '.p3d'
    if stripped.lower() in p3d_index:
        return p3d_index[stripped.lower()]
    
    # STRATEGY 3: Strip multiple prefixes (CUP_, TK_GUE_, CDF_, Base_, etc.)
    stripped2 = re.sub(r'^(CUP_|TK_GUE_|CDF_|Base_|rhs_|RHS_)', '', 
                       re.sub(r'^(B_|O_|I_|C_|Land_)', '', classname)) + '.p3d'
    if stripped2.lower() in p3d_index:
        return p3d_index[stripped2.lower()]
    
    # STRATEGY 4: Partial match — search for P3D containing the classname
    search_term = classname.lower().replace('_', '')
    candidates = []
    for p3d_lower, p3d_actual in p3d_index.items():
        p3d_stem = p3d_lower.replace('.p3d', '').replace('_', '')
        # Check if the classname is contained in the p3d name or vice versa
        if len(search_term) > 4 and search_term in p3d_stem:
            candidates.append((len(p3d_stem), p3d_actual))
        elif len(p3d_stem) > 4 and p3d_stem in search_term:
            candidates.append((len(p3d_stem), p3d_actual))
    
    if candidates:
        # Prefer the shortest (most direct) match
        candidates.sort()
        return candidates[0][1]
    
    # STRATEGY 5: Strip suffixes and try
    # e.g., Land_CratesShabby_F → CratesShabby_F.p3d
    #       CUP_hromada_beden_dekorativniX → hromada_beden_dekorativniX.p3d
    stripped3 = classname + '.p3d'
    # Try removing common prefixes piece by piece
    for prefix in ['Land_', 'B_', 'O_', 'I_', 'C_', 'CUP_', 'TK_GUE_', 'CDF_', 'Base_']:
        if classname.startswith(prefix):
            test = classname[len(prefix):] + '.p3d'
            if test.lower() in p3d_index:
                return p3d_index[test.lower()]
    
    # Not found
    return None


def main():
    if len(sys.argv) < 3:
        print("Usage: python match_models.py <exports_dir> <input_json_or_classnames> [--armadir <dir> ...]")
        sys.exit(1)
    
    exports_dir = sys.argv[1]
    input_path = sys.argv[2]
    arma_dirs = []
    
    # Parse optional --armadir args
    i = 3
    while i < len(sys.argv):
        if sys.argv[i] == '--armadir' and i + 1 < len(sys.argv):
            arma_dirs.append(sys.argv[i + 1])
            i += 2
        else:
            i += 1
    
    models_dir = os.path.join(exports_dir, "models")
    cache_file = os.path.join(exports_dir, "p3d_index_cache.json")
    
    # Read classnames from input
    classnames = set()
    if input_path.endswith('.json'):
        with open(input_path, 'r') as f:
            data = json.load(f)
        for e in (data if isinstance(data, list) else data.get('entities', data.get('mission', {}).get('entities', []))):
            t = e.get('type', '')
            if t:
                classnames.add(t)
    else:
        with open(input_path, 'r') as f:
            for line in f:
                t = line.strip()
                if t:
                    classnames.add(t)
    
    print(f"Found {len(classnames)} unique classnames.")
    
    # Load or build P3D index
    p3d_index = load_p3d_cache(cache_file)
    if p3d_index is None or not arma_dirs:
        if p3d_index and not arma_dirs:
            print(f"Using cached P3D index ({len(p3d_index)} entries) from: {cache_file}")
        else:
            print("Building P3D index (this may take a few minutes)...")
            if not arma_dirs:
                # Try to find Arma dir from config
                config_path = os.path.join(os.path.dirname(exports_dir), '..', 'config.json')
                if os.path.exists(config_path):
                    with open(config_path) as f:
                        cfg = json.load(f)
                    if cfg.get('arma3_dir'):
                        arma_dirs.append(cfg['arma3_dir'])
                    if cfg.get('workshop_dir'):
                        arma_dirs.append(cfg['workshop_dir'])
            
            p3d_index = index_pbos(arma_dirs)
            save_p3d_cache(cache_file, p3d_index)
    
    print(f"P3D index has {len(p3d_index)} entries.")
    
    # Match each classname
    mapping = {}
    missing = []
    for cn in sorted(classnames):
        p3d = fuzzy_match(cn, p3d_index)
        if p3d:
            mapping[cn] = p3d
            print(f"  {cn:40s} → {p3d}")
        else:
            missing.append(cn)
            print(f"  {cn:40s} → NOT FOUND (using fallback)")
            # Fallback: strip prefix and create .p3d name
            fallback = re.sub(r'^(B_|O_|I_|C_|Land_|CUP_|CDF_|TK_GUE_|Base_)', '', cn) + '.p3d'
            mapping[cn] = fallback
    
    # Output
    output = {
        "mapping": mapping,
        "missing": missing,
    }
    output_path = os.path.join(exports_dir, "classname_to_model.json")
    with open(output_path, 'w') as f:
        json.dump(output, f, indent=2)
    
    print(f"\nResults: {len(mapping) - len(missing)} matched, {len(missing)} not found")
    print(f"Saved to: {output_path}")


if __name__ == '__main__':
    main()