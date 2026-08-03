# Arma 3 OPRW v25 (WRP) Format Specification

This document outlines the reverse-engineered structure of the Arma 3 `OPRW` version 25 (`.wrp`) map file format. The format relies heavily on sequential binary serialization and LZO1X compression for large data arrays.

## 1. File Header

The file begins with a 32-byte header containing fundamental map properties:

| Offset | Type     | Description | Example (Altis) |
|--------|----------|-------------|-----------------|
| 0x00   | `char[4]`| Magic Signature | `OPRW` |
| 0x04   | `Int32`  | Version | `25` |
| 0x08   | `Int32`  | Unknown/Padding | e.g., `107410` |
| 0x0C   | `Int32`  | Material Grid X | `1024` |
| 0x10   | `Int32`  | Material Grid Y | `1024` |
| 0x14   | `Int32`  | Heightmap Grid X | `4096` |
| 0x18   | `Int32`  | Heightmap Grid Y | `4096` |
| 0x1C   | `Float32`| Cell Size (meters) | `30.0` |

## 2. Serialized Data Segments

Immediately following the header, the file contains a sequential stream of serialized data segments. Large arrays are typically compressed using the LZO1X algorithm.

### 2.1. Elevation Data (Heightmap)
- **Format**: LZO-compressed array of `Float32` values.
- **Length**: `Heightmap Grid X * Heightmap Grid Y` (e.g., 16,777,216 floats for Altis).
- **Description**: Represents the true elevation map of the terrain in meters relative to sea level. Extracted as `heightmap.bin`.

### 2.2. Material Index (Surface Mask)
- **Format**: LZO-compressed array of `UInt16` values.
- **Length**: `Material Grid X * Material Grid Y`
- **Description**: An index map that assigns a surface material to each land grid cell. Extracted as `material_mask.bin`.

### 2.3. Primary Texture Index (PrimTexIndex)
- **Format**: Array of `Byte` values.
- **Length**: `Heightmap Grid X * Heightmap Grid Y`
- **Description**: A higher-resolution byte array mapping each heightmap cell to a material index from the Material Names table. Extracted as `prim_tex.bin`.

### 2.4. Material Names Table (MatNames)
- **Format**: Uncompressed array of ASCII strings.
- **Description**: A list of file paths pointing to the `.rvmat` materials. Extracted to `material_names.json`.

### 2.5. Geography
- **Format**: Originally a quad-tree structure in the binary, flattened to a 2D grid of flags.
- **Length**: `Material Grid X * Material Grid Y`
- **Description**: Represents surface features (e.g., forest, road, water flags) at the land grid resolution. Extracted as `geography.bin`.

### 2.6. Grass Approximation (GrassApprox)
- **Format**: Array of `Byte` values.
- **Length**: Typically matches Heightmap resolution.
- **Description**: Represents grass coverage and density per cell. Extracted as `grass_approx.bin`.

### 2.7. Persistent Map
- **Format**: Array of `Byte` values.
- **Length**: Typically matches Land Grid resolution.
- **Description**: A byte map tracking persistent environmental or terrain states. Extracted as `persistent.bin`.

### 2.8. Object Placement Table
- **Format**: Structured array of object definitions.
- **Description**: Contains the placement data for every static object on the map (e.g., trees, rocks, buildings). Each entry includes a model path and a transformation matrix. Extracted as `objects.json`.

### 2.9. Road Network (Roadnet)
- **Format**: Grid of cells containing arrays of road links.
- **Description**: Defines the vector-based road network across the map, including connection points, types (main road, track, bridge), and linked `.p3d` models. Extracted as `roadnet.json`.

#### Coordinate System & Rotation Matrix Details
The transformation matrix for each object is a row-major 4x3 matrix containing rotational vectors and the translation vector (position).

```
[ M11, M12, M13 ] (Right Vector)
[ M21, M22, M23 ] (Up Vector)
[ M31, M32, M33 ] (Forward Vector)
[ M41, M42, M43 ] (Translation / Position)
```

**Position & Scale:**
- `X, Y, Z` coordinates map to `M41, M43, M42` respectively (Note: Arma 3's engine uses Y as the vertical axis internally, but the map coordinates are often flipped such that Z is up in some tools).
- The map terrain is scaled by the Cell Size. The objects' translation coordinates are stored in **absolute meters**. Therefore, you do not need to multiply object coordinates by the cell size.
- A `meta.json` file is exported alongside objects to convey the global dimensions: `map_size = cell_size * heightmap_grid_x`. This helps correctly align the terrain heightmap rendering with the object coordinates.

**Calculating Rotation (Yaw):**
For 2D map viewers or simple 3D positioning, the object's Heading (Yaw) must be extracted correctly. A common mistake is using `Atan2(M13, M33)`. 
The correct extraction for Arma 3 WRP rotation in the XY plane is:
`Yaw = Atan2(M31, M33)`
This extracts the angle of the Forward Vector along the X and Z axes. Using `M13` instead of `M31` will result in objects being mis-rotated by up to 90 degrees or appearing mirrored.

## 3. Parsing Considerations

When writing parsers for the `OPRW` format, it is critical to read the file as a continuous, sequential binary stream. Tools that attempt to scan the file for LZO chunk headers without respecting the predefined segment sizes and serialization order will fail to properly reconstruct large datasets, such as the elevation array, due to LZO compression artifacts and chunking boundaries.
