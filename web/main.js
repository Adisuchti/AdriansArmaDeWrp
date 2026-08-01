import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';
import * as BufferGeometryUtils from 'three/addons/utils/BufferGeometryUtils.js';

// DOM Elements
const view2d = document.getElementById('view-2d');
const view3d = document.getElementById('view-3d');
const mapCanvas = document.getElementById('map-canvas');
const selectionBox = document.getElementById('selection-box');
const canvasWrapper = document.querySelector('.canvas-wrapper');
const btnRender = document.getElementById('btn-render');
const btnBack = document.getElementById('btn-back');
const statusText = document.getElementById('status-text');
const webglContainer = document.getElementById('webgl-container');
const statObjects = document.getElementById('stat-objects');
const statArea = document.getElementById('stat-area');

// Configuration
let mapSizeMeters = 8192; // Default, will be updated via meta.json
let minHeight = 0;
let maxHeight = 300;

// State
let heightmapImage = null;
let heightmapData = null; // ImageData
let terrainTextureImage = null; // Image - terrain_class.png
let isDragging = false;
let startX, startY;
let currentSelection = null; // {x, y, w, h} in canvas CSS pixels
let objectData = null; // parsed JSON
let classificationData = {}; // parsed classification lookup
let placeNamesData = []; // array of place names
let threeScene, threeCamera, threeRenderer, threeControls;
let nameLabels = []; // DOM elements for place names

const mapSelect = document.getElementById('map-select');
const missionSelect = document.getElementById('mission-select');

let currentMissionData = null; // { meta, entities }

// Initialization
async function init() {
  statusText.innerText = "Fetching maps...";
  try {
    const urlParams = new URLSearchParams(window.location.search);
    const initialMap = urlParams.get('map');

    if (urlParams.has('x')) {
      const loader = document.getElementById('loading-overlay');
      if (loader) loader.classList.remove('hidden');
    }

    try {
      const classRes = await fetch('classification.json');
      if (classRes.ok) {
        classificationData = await classRes.json();
        console.log(`Loaded ${Object.keys(classificationData).length} classification rules.`);
      }
    } catch (e) {
      console.warn("Could not load classification.json", e);
    }

    const res = await fetch('api/maps.json');
    const data = await res.json();

    mapSelect.innerHTML = '';
    if (data.maps.length === 0) {
      mapSelect.innerHTML = '<option value="">No maps found</option>';
      statusText.innerText = "No exported maps found.";
      return;
    }

    data.maps.forEach(map => {
      const opt = document.createElement('option');
      opt.value = map;
      opt.innerText = map;
      if (initialMap === map) opt.selected = true;
      mapSelect.appendChild(opt);
    });

    mapSelect.addEventListener('change', () => {
      const urlParams = new URLSearchParams(window.location.search);
      urlParams.set('map', mapSelect.value);
      urlParams.delete('x');
      urlParams.delete('y');
      urlParams.delete('w');
      urlParams.delete('h');
      window.history.replaceState({}, '', `${window.location.pathname}?${urlParams.toString()}`);
      loadMap(mapSelect.value);
    });

    // Populate missions dropdown
    try {
      const missionRes = await fetch('api/missions.json');
      if (missionRes.ok) {
        const missionData = await missionRes.json();
        missionSelect.innerHTML = '<option value="">None</option>';
        (missionData.missions || []).forEach(m => {
          const opt = document.createElement('option');
          opt.value = m.name;
          opt.innerText = `${m.name.replace('_SQM', '')} (${m.entity_count} entities)`;
          if (m.map_name) opt.innerText += ` - ${m.map_name}`;
          missionSelect.appendChild(opt);
        });
      }
    } catch (e) {
      console.warn('Could not load missions', e);
    }

    missionSelect.addEventListener('change', () => {
      if (missionSelect.value) {
        loadMission(missionSelect.value);
      } else {
        currentMissionData = null;
      }
    });

    // Load the first map
    loadMap(mapSelect.value);
    setupSelectionEvents();

  } catch (error) {
    statusText.innerText = "Error connecting to API. Is server.py running?";
    console.error(error);
  }
}

async function loadMap(mapName) {
  statusText.innerText = `Loading ${mapName} data...`;
  btnRender.disabled = true;
  selectionBox.style.display = 'none';
  currentSelection = null;

  try {
    // 1. Load Meta
    try {
      const metaRes = await fetch(`map/${mapName}/meta.json`);
      if (metaRes.ok) {
        const meta = await metaRes.json();
        if (meta.mapSize) mapSizeMeters = meta.mapSize;
        if (meta.minHeight !== undefined) minHeight = meta.minHeight;
        if (meta.maxHeight !== undefined) maxHeight = meta.maxHeight;
      } else {
        mapSizeMeters = 8192; // fallback
      }
    } catch (e) { mapSizeMeters = 8192; }

    // 2. Load Heightmap
    heightmapImage = new Image();
    await new Promise((resolve, reject) => {
      heightmapImage.onload = resolve;
      heightmapImage.onerror = reject;
      heightmapImage.src = `map/${mapName}/heightmap.png`;
    });

    const ctx = mapCanvas.getContext('2d');
    mapCanvas.width = heightmapImage.width;
    mapCanvas.height = heightmapImage.height;
    ctx.drawImage(heightmapImage, 0, 0);
    heightmapData = ctx.getImageData(0, 0, mapCanvas.width, mapCanvas.height);
    
    // Convert 24-bit encoded heightmap data into a visual grayscale image for the 2D view
    const visualData = ctx.createImageData(mapCanvas.width, mapCanvas.height);
    for (let i = 0; i < heightmapData.data.length; i += 4) {
      const r = heightmapData.data[i];
      const g = heightmapData.data[i+1];
      const b = heightmapData.data[i+2];
      
      let normalized = 0;
      if (r === g && g === b) {
          normalized = r / 255.0;
      } else {
          const val_24 = (r << 16) | (g << 8) | b;
          normalized = val_24 / 16777215.0;
      }
      
      const intensity = Math.floor(normalized * 255);
      visualData.data[i] = intensity;
      visualData.data[i+1] = intensity;
      visualData.data[i+2] = intensity;
      visualData.data[i+3] = 255; // Alpha
    }
    ctx.putImageData(visualData, 0, 0);

    // Overlay roads if available
    try {
      const roadsImage = new Image();
      await new Promise((resolve, reject) => {
        roadsImage.onload = resolve;
        roadsImage.onerror = reject;
        roadsImage.src = `map/${mapName}/roads.png`;
      });
      ctx.drawImage(roadsImage, 0, 0, mapCanvas.width, mapCanvas.height);
    } catch (e) {
      console.log(`No roads.png found for ${mapName}, skipping roadmap overlay.`);
    }

    // 3. Load terrain class texture (painted onto the 3D terrain)
    terrainTextureImage = new Image();
    try {
      await new Promise((resolve, reject) => {
        terrainTextureImage.onload = resolve;
        terrainTextureImage.onerror = () => {
          console.log("No terrain_class.png for " + mapName + ", falling back to solid colour.");
          terrainTextureImage = null;
          resolve(); // don't reject, just skip
        };
        terrainTextureImage.src = `map/${mapName}/terrain_class.png`;
      });
    } catch (e) {
      terrainTextureImage = null;
    }

    // 4. Load place names
    try {
      const namesRes = await fetch(`map/${mapName}/names.json`);
      if (namesRes.ok) {
        placeNamesData = await namesRes.json();
      } else {
        placeNamesData = [];
      }
    } catch (e) {
      placeNamesData = [];
    }

    // 5. No longer loading all objects upfront — they will be fetched per-region in render3D()
    // Just mark the map as loaded with a dummy array so the selection logic works
    objectData = []; // placeholder; real data fetched in render3D

    statusText.innerText = `Ready. Size: ${mapSizeMeters}m. Select a region to render.`;
    if (currentSelection && currentSelection.width > 10 && currentSelection.height > 10) {
      btnRender.disabled = false;
    }

    const urlParams = new URLSearchParams(window.location.search);
    const px = parseFloat(urlParams.get('x'));
    const py = parseFloat(urlParams.get('y'));
    const pw = parseFloat(urlParams.get('w'));
    const ph = parseFloat(urlParams.get('h'));

    if (!isNaN(px) && !isNaN(py) && !isNaN(pw) && !isNaN(ph) && pw > 0 && ph > 0) {
      const rect = canvasWrapper.getBoundingClientRect();
      currentSelection = {
        left: px * rect.width,
        top: py * rect.height,
        width: pw * rect.width,
        height: ph * rect.height,
        wrapperWidth: rect.width,
        wrapperHeight: rect.height
      };
      selectionBox.style.display = 'block';
      selectionBox.style.left = currentSelection.left + 'px';
      selectionBox.style.top = currentSelection.top + 'px';
      selectionBox.style.width = currentSelection.width + 'px';
      selectionBox.style.height = currentSelection.height + 'px';
      btnRender.disabled = false;
      
      // Auto render if it was directly linked
      if (urlParams.has('x')) {
        render3D();
      } else {
        const loader = document.getElementById('loading-overlay');
        if (loader) loader.classList.add('hidden');
      }
    } else {
      const loader = document.getElementById('loading-overlay');
      if (loader) loader.classList.add('hidden');
    }

  } catch (error) {
    statusText.innerText = `Error loading map ${mapName}.`;
    console.error(error);
    const loader = document.getElementById('loading-overlay');
    if (loader) loader.classList.add('hidden');
  }
}

// 2D Selection Logic
function setupSelectionEvents() {
  canvasWrapper.addEventListener('mousedown', (e) => {
    isDragging = true;
    const rect = canvasWrapper.getBoundingClientRect();
    startX = e.clientX - rect.left;
    startY = e.clientY - rect.top;

    selectionBox.style.display = 'block';
    selectionBox.style.left = startX + 'px';
    selectionBox.style.top = startY + 'px';
    selectionBox.style.width = '0px';
    selectionBox.style.height = '0px';
    currentSelection = null;
    btnRender.disabled = true;
  });

  window.addEventListener('mousemove', (e) => {
    if (!isDragging) return;
    const rect = canvasWrapper.getBoundingClientRect();
    let currentX = e.clientX - rect.left;
    let currentY = e.clientY - rect.top;

    // Clamp to canvas wrapper
    currentX = Math.max(0, Math.min(currentX, rect.width));
    currentY = Math.max(0, Math.min(currentY, rect.height));

    const left = Math.min(startX, currentX);
    const top = Math.min(startY, currentY);
    const width = Math.abs(currentX - startX);
    const height = Math.abs(currentY - startY);

    selectionBox.style.left = left + 'px';
    selectionBox.style.top = top + 'px';
    selectionBox.style.width = width + 'px';
    selectionBox.style.height = height + 'px';

    currentSelection = { left, top, width, height, wrapperWidth: rect.width, wrapperHeight: rect.height };
  });

  window.addEventListener('mouseup', () => {
    if (isDragging) {
      isDragging = false;
      if (currentSelection && currentSelection.width > 10 && currentSelection.height > 10) {
        if (objectData !== null) {
          btnRender.disabled = false;
        }
      } else {
        selectionBox.style.display = 'none';
        currentSelection = null;
      }
    }
  });

  btnRender.addEventListener('click', render3D);
  // btnBack is handled inside render3D to clean up the specific scene
}

// 3D Rendering Logic
async function render3D() {
  if (!objectData) {
    alert("Map data is still loading or failed to load. Please wait.");
    return;
  }

  mapSelect.disabled = true;

  if (currentSelection && currentSelection.wrapperWidth) {
    const px = currentSelection.left / currentSelection.wrapperWidth;
    const py = currentSelection.top / currentSelection.wrapperHeight;
    const pw = currentSelection.width / currentSelection.wrapperWidth;
    const ph = currentSelection.height / currentSelection.wrapperHeight;
    
    const urlParams = new URLSearchParams(window.location.search);
    urlParams.set('map', mapSelect.value);
    urlParams.set('x', px.toFixed(4));
    urlParams.set('y', py.toFixed(4));
    urlParams.set('w', pw.toFixed(4));
    urlParams.set('h', ph.toFixed(4));
    window.history.replaceState({}, '', `${window.location.pathname}?${urlParams.toString()}`);
  }

  view2d.classList.add('hidden');
  view3d.classList.remove('hidden');

  // 1. Calculate World Coordinates
  // We need to map the CSS pixel selection to the actual Image pixels, and then to Arma Meters.
  const scaleX = mapCanvas.width / currentSelection.wrapperWidth;
  const scaleY = mapCanvas.height / currentSelection.wrapperHeight;

  const imgLeft = Math.floor(currentSelection.left * scaleX);
  const imgTop = Math.floor(currentSelection.top * scaleY);
  const imgWidth = Math.floor(currentSelection.width * scaleX);
  const imgHeight = Math.floor(currentSelection.height * scaleY);

  const metersPerPixel = mapSizeMeters / mapCanvas.width;

  // Arma Y is bottom-up. Image Y is top-down.
  // bottom edge of selection in image = top edge in Arma
  const armaMinX = imgLeft * metersPerPixel;
  const armaMaxX = (imgLeft + imgWidth) * metersPerPixel;

  const armaMinY = (mapCanvas.height - (imgTop + imgHeight)) * metersPerPixel;
  const armaMaxY = (mapCanvas.height - imgTop) * metersPerPixel;

  const selMetersWidth = armaMaxX - armaMinX;
  const selMetersHeight = armaMaxY - armaMinY;

  statArea.innerText = Math.round(selMetersWidth * selMetersHeight).toLocaleString();

  // 2. Setup Three.js
  threeScene = new THREE.Scene();
  threeScene.background = new THREE.Color(0x0f172a); // Match dark theme

  threeCamera = new THREE.PerspectiveCamera(60, window.innerWidth / window.innerHeight, 1, 20000);
  // Position camera slightly above and looking at center
  threeCamera.position.set(0, Math.max(selMetersWidth, selMetersHeight) * 0.8, Math.max(selMetersWidth, selMetersHeight) * 0.8);

  threeRenderer = new THREE.WebGLRenderer({ antialias: true });
  threeRenderer.setSize(window.innerWidth, window.innerHeight);
  threeRenderer.shadowMap.enabled = true;
  threeRenderer.shadowMap.type = THREE.PCFSoftShadowMap;
  webglContainer.appendChild(threeRenderer.domElement);

  threeControls = new OrbitControls(threeCamera, threeRenderer.domElement);
  threeControls.target.set(0, 0, 0);
  threeControls.maxPolarAngle = Math.PI / 2 - 0.05; // Don't go below ground

  // Lighting
  const ambientLight = new THREE.AmbientLight(0xffffff, 0.4);
  threeScene.add(ambientLight);

  const dirLight = new THREE.DirectionalLight(0xffedd5, 1.5);
  dirLight.position.set(1000, 2000, 1000);
  dirLight.castShadow = true;
  dirLight.shadow.mapSize.width = 2048;
  dirLight.shadow.mapSize.height = 2048;
  dirLight.shadow.camera.near = 0.5;
  dirLight.shadow.camera.far = 5000;
  const d = Math.max(selMetersWidth, selMetersHeight);
  dirLight.shadow.camera.left = -d;
  dirLight.shadow.camera.right = d;
  dirLight.shadow.camera.top = d;
  dirLight.shadow.camera.bottom = -d;
  threeScene.add(dirLight);

  // 3. Generate Terrain Mesh
  // To avoid millions of vertices, we limit the geometry segments to max 256
  const maxSegments = 256;
  const segX = Math.min(imgWidth, maxSegments);
  const segY = Math.min(imgHeight, maxSegments);

  // Three.js PlaneGeometry is created on X,Y plane, we rotate it to X,Z
  const terrainGeo = new THREE.PlaneGeometry(selMetersWidth, selMetersHeight, segX, segY);
  terrainGeo.rotateX(-Math.PI / 2); // Make it flat on the ground

  // Displace vertices based on heightmap
  const positions = terrainGeo.attributes.position.array;
  for (let i = 0; i < positions.length; i += 3) {
    // The vertex position in local coordinates (-width/2 to +width/2)
    const vx = positions[i];
    const vz = positions[i + 2]; // Z represents the Arma Y axis

    // Map vertex back to the selected image rect
    // vx is [-selMetersWidth/2, selMetersWidth/2]
    const percentX = (vx + selMetersWidth / 2) / selMetersWidth;
    // vz is [-selMetersHeight/2, selMetersHeight/2]
    // Note: PlaneGeometry top edge is -Z, bottom edge is +Z. 
    // In our image, top is imgTop, bottom is imgTop + imgHeight.
    const percentY = (vz + selMetersHeight / 2) / selMetersHeight;

    const px = Math.floor(imgLeft + percentX * imgWidth);
    const py = Math.floor(imgTop + percentY * imgHeight);

    // Safe clamp
    const safePx = Math.max(0, Math.min(px, mapCanvas.width - 1));
    const safePy = Math.max(0, Math.min(py, mapCanvas.height - 1));

    // Get pixel color
    const idx = (safePy * mapCanvas.width + safePx) * 4;
    const r = heightmapData.data[idx];
    const g = heightmapData.data[idx + 1];
    const b = heightmapData.data[idx + 2];

    // Decode 24-bit height from RGB, or fallback to 8-bit if it's a legacy grayscale image
    let height = 0;
    let normalized = 0;
    if (r === g && g === b) {
        // Legacy 8-bit grayscale
        normalized = r / 255.0;
    } else {
        // 24-bit RGB precision
        const val_24 = (r << 16) | (g << 8) | b;
        normalized = val_24 / 16777215.0;
    }
    height = minHeight + (normalized * (maxHeight - minHeight));

    positions[i + 1] = height; // Y axis is up in Three.js
  }

  terrainGeo.computeVertexNormals();

  // Terrain material with terrain_class.png texture if available
  const terrainMatOptions = {
    roughness: 0.9,
    metalness: 0.0,
    flatShading: false
  };

  if (terrainTextureImage) {
    const terrainTex = new THREE.CanvasTexture(terrainTextureImage);
    terrainTex.wrapS = THREE.ClampToEdgeWrapping;
    terrainTex.wrapT = THREE.ClampToEdgeWrapping;
    terrainTex.colorSpace = THREE.SRGBColorSpace;

    // Map the texture sub-region to the plane UVs (0→1)
    terrainTex.repeat.set(
      selMetersWidth / mapSizeMeters,
      selMetersHeight / mapSizeMeters
    );
    terrainTex.offset.set(
      armaMinX / mapSizeMeters,
      armaMinY / mapSizeMeters
    );

    terrainMatOptions.map = terrainTex;
    // With texture, don't need a separate color tint
    terrainMatOptions.color = 0xffffff;
    statusText.innerText = 'Terrain coloured with classification map.';
  } else {
    terrainMatOptions.color = 0x3f4e4f;
  }

  const terrainMat = new THREE.MeshStandardMaterial(terrainMatOptions);
  // Store the terrain class texture so the toggle can restore it
  if (terrainMatOptions.map) {
    terrainMat.userData._terrainClassTex = terrainMatOptions.map;
  }
  const terrainMesh = new THREE.Mesh(terrainGeo, terrainMat);
  terrainMesh.receiveShadow = true;
  threeScene.add(terrainMesh);

  // 4. Fetch Objects for this region from the server
  // Center of our Arma world selection box
  const armaCenterX = armaMinX + selMetersWidth / 2;
  const armaCenterY = armaMinY + selMetersHeight / 2;

  statusText.innerText = 'Fetching objects for selected region...';
  let validObjects = [];
  try {
    const regionRes = await fetch(
      `map/${mapSelect.value}/objects_in_region?minX=${armaMinX}&maxX=${armaMaxX}&minY=${armaMinY}&maxY=${armaMaxY}`
    );
    if (regionRes.ok) {
      // Stream NDJSON response line-by-line — never holds the full payload in memory
      const reader = regionRes.body.getReader();
      const decoder = new TextDecoder('utf-8');
      let buffer = '';
      let done = false;

      while (!done) {
        const { value, done: streamDone } = await reader.read();
        if (value) {
          buffer += decoder.decode(value, { stream: !streamDone });
        }

        // Process complete lines
        let newlineIdx;
        while ((newlineIdx = buffer.indexOf('\n')) !== -1) {
          const line = buffer.substring(0, newlineIdx).trim();
          buffer = buffer.substring(newlineIdx + 1);
          if (line) {
            try {
              validObjects.push(JSON.parse(line));
            } catch (e) {
              // Skip malformed lines
            }
          }
        }

        done = streamDone;
      }

      // Process any remaining data after stream ends (last line without trailing newline)
      if (buffer.trim()) {
        try {
          validObjects.push(JSON.parse(buffer.trim()));
        } catch (e) {
          // Skip malformed trailing data
        }
      }
    } else {
      console.warn(`Region API returned ${regionRes.status}, using empty set.`);
    }
  } catch (e) {
    console.error('Failed to fetch objects for region:', e);
    alert('Failed to load objects for this region. The objects.json file may be too large for the current approach. Try a smaller region.');
    validObjects = [];
  }
  statusText.innerText = `Loaded ${validObjects.length.toLocaleString()} objects in region.`;

  statObjects.innerText = validObjects.length.toLocaleString();

  // Categories definition for fallback colors
  const categoryColors = {
    buildings: 0x38bdf8,
    nature: 0x22c55e,
    clutter: 0x78716c,
    roads: 0x334155,
    structures: 0x64748b,
    lamps: 0xfacc15
  };

  // Group objects by their model name to use InstancedMesh efficiently
  const modelGroups = {};

  validObjects.forEach(obj => {
    // Determine category
    let cat = "clutter";
    const cls = obj.class.toLowerCase();
    
    if (classificationData[cls]) {
      cat = classificationData[cls];
    } else if (cls.startsWith('t_') || cls.startsWith('b_')) {
      cat = "nature";
    } else if (cls.startsWith('c_')) {
      cat = "clutter";
    } else if (obj.category && categoryColors[obj.category]) {
      cat = obj.category;
    } else {
      if (cls.includes('tree') || cls.includes('bush')) cat = "nature";
      else if (cls.includes('road') || cls.includes('track')) cat = "roads";
      else if (cls.includes('wall') || cls.includes('fence') || cls.includes('hide')) cat = "structures";
      else if (cls.includes('house') || cls.includes('building') || cls.includes('office') || cls.includes('shop')) cat = "buildings";
      else if (cls.includes('lamp') || cls.includes('light')) cat = "lamps";
    }

    // Determine model filename
    let modelFile = obj.model;
    if (!modelFile || modelFile === "unknown") {
      modelFile = obj.class.toLowerCase() + ".p3d"; // Fallback if SQF didn't export
    }
    const glbFile = modelFile.toLowerCase().replace(".p3d", ".glb");

    if (!modelGroups[glbFile]) {
      modelGroups[glbFile] = { category: cat, objects: [], mesh: null };
    }
    modelGroups[glbFile].objects.push(obj);
  });

  const boxGeo = new THREE.BoxGeometry(1, 1, 1);
  const dummy = new THREE.Object3D();

  // Get exact terrain height at specific Arma coordinates
  function getTerrainHeightAt(armaX, armaY) {
    const px = Math.floor(armaX / metersPerPixel);
    const py = Math.floor((mapSizeMeters - armaY) / metersPerPixel);
    const safePx = Math.max(0, Math.min(px, mapCanvas.width - 1));
    const safePy = Math.max(0, Math.min(py, mapCanvas.height - 1));
    const idx = (safePy * mapCanvas.width + safePx) * 4;
    const r = heightmapData.data[idx];
    const g = heightmapData.data[idx + 1];
    const b = heightmapData.data[idx + 2];
    
    let normalized = 0;
    if (r === g && g === b) {
        normalized = r / 255.0;
    } else {
        const val_24 = (r << 16) | (g << 8) | b;
        normalized = val_24 / 16777215.0;
    }
    return minHeight + (normalized * (maxHeight - minHeight));
  }

  function getTerrainNormalAt(armaX, armaY) {
    const delta = metersPerPixel * 2; // sample a bit wider to average out pixels
    const hL = getTerrainHeightAt(armaX - delta, armaY);
    const hR = getTerrainHeightAt(armaX + delta, armaY);
    const hD = getTerrainHeightAt(armaX, armaY - delta); // South
    const hU = getTerrainHeightAt(armaX, armaY + delta); // North
    
    // Normal = (hL - hR, 2 * delta, hU - hD)
    return new THREE.Vector3(hL - hR, 2 * delta, hU - hD).normalize();
  }

  const gltfLoader = new GLTFLoader();

  // Track all InstancedMeshes by category so UI filters can toggle them
  const categoryMeshes = {
    buildings: [], nature: [], clutter: [], roads: [], structures: [], lamps: []
  };
  const allInstancedMeshes = [];
  let nameLabels = [];
  const labelsContainer = document.getElementById('labels-container');
  
  // Start Animation Loop early so models stream in
  let isRendering = true;
  function animate() {
    requestAnimationFrame(animate);

    if (threeControls) {
      threeControls.update();
    }

    // Update labels position
    const filterNames = document.getElementById('filter-names').checked;
    const labelsContainer = document.getElementById('labels-container');
    labelsContainer.style.display = filterNames ? 'block' : 'none';

    if (filterNames) {
      const halfWidth = window.innerWidth / 2;
      const halfHeight = window.innerHeight / 2;
      const vec = new THREE.Vector3();

      nameLabels.forEach(labelObj => {
        vec.copy(labelObj.pos);
        vec.project(threeCamera);

        // Check if behind camera
        if (vec.z > 1) {
          labelObj.element.style.display = 'none';
        } else {
          labelObj.element.style.display = 'block';
          const x = (vec.x * halfWidth) + halfWidth;
          const y = -(vec.y * halfHeight) + halfHeight;
          labelObj.element.style.left = `${x}px`;
          labelObj.element.style.top = `${y}px`;
        }
      });
    }

    if (threeRenderer && threeScene && threeCamera) {
      threeRenderer.render(threeScene, threeCamera);
    }
  }

  // 7. Create DOM labels for place names inside the selected region
  placeNamesData.forEach(place => {
    if (place.x >= armaMinX && place.x <= armaMaxX && place.y >= armaMinY && place.y <= armaMaxY) {
      const label = document.createElement('div');
      label.className = 'place-name-label';
      label.textContent = place.name;
      
      let fontSize = '14px';
      let fontWeight = 'bold';
      if (place.type === 'NameCityCapital') fontSize = '24px';
      else if (place.type === 'NameCity') fontSize = '20px';
      else if (place.type === 'NameVillage') fontSize = '16px';
      else if (place.type === 'Hill') {
          fontSize = '12px';
          fontWeight = 'normal';
          label.style.fontStyle = 'italic';
          label.style.color = '#cbd5e1';
      }

      label.style.position = 'absolute';
      label.style.color = '#ffffff';
      label.style.fontSize = fontSize;
      label.style.fontWeight = fontWeight;
      label.style.textShadow = '1px 1px 2px black, -1px -1px 2px black, 1px -1px 2px black, -1px 1px 2px black';
      label.style.transform = 'translate(-50%, -50%)';
      label.style.pointerEvents = 'none';
      label.style.fontFamily = '"Segoe UI", Arial, sans-serif';
      
      labelsContainer.appendChild(label);
      
      const h = getTerrainHeightAt(place.x, place.y);
      nameLabels.push({
        element: label,
        pos: new THREE.Vector3(place.x - armaCenterX, h + 20, armaCenterY - place.y) // float above terrain
      });
    }
  });

  animate();

  // Load models asynchronously
  for (const [glbFile, group] of Object.entries(modelGroups)) {
    if (group.objects.length === 0) continue;

    const count = group.objects.length;
    let geo = boxGeo;
    let mat = new THREE.MeshStandardMaterial({ color: categoryColors[group.category] });
    let isModelLoaded = false;
    const isRoad = group.category === 'roads' || glbFile.includes('procedural_road');

    if (isRoad) {
      // Roads are now handled via roadnet.json polylines — skip old WRP road objects
      continue;
    } else {
      try {
        // Attempt to load GLTF
        const gltf = await gltfLoader.loadAsync(`models/${glbFile}`);

        // Find the first mesh in the GLTF scene
        let loadedMesh = null;
        gltf.scene.traverse((child) => {
          if (child.isMesh && !loadedMesh) {
            loadedMesh = child;
          }
        });

        if (loadedMesh) {
          geo = loadedMesh.geometry;
          mat = new THREE.MeshStandardMaterial({ 
              color: categoryColors[group.category],
              roughness: 0.7,
              metalness: 0.1,
              flatShading: true
          });
          isModelLoaded = true;
        }
      } catch (e) {
        console.warn(`Could not load model ${glbFile}, using bounding box fallback.`);
      }
    }

    const instancedMesh = new THREE.InstancedMesh(geo, mat, count);
    instancedMesh.castShadow = false; 
    instancedMesh.receiveShadow = true;
    instancedMesh.userData.isBoundingBox = !isModelLoaded;

    group.objects.forEach((obj, index) => {
      // Position relative to the center of the selection
      const posX = obj.x - armaCenterX;
      const posZ = -(obj.y - armaCenterY);

      let posY = obj.z !== undefined ? obj.z : getTerrainHeightAt(obj.x, obj.y);

      // Physical Dimensions
      const w = obj.w || 1;
      const h = obj.h || 1;
      const l = obj.l || 1;
      
      // Placement Scale
      const sX = (obj.scaleX !== undefined ? obj.scaleX : 1);
      const sY = (obj.scaleY !== undefined ? obj.scaleY : 1);
      const sZ = (obj.scaleZ !== undefined ? obj.scaleZ : 1);

      const pitch = obj.pitch ? THREE.MathUtils.degToRad(-obj.pitch) : 0;
      const yaw = THREE.MathUtils.degToRad(-obj.dir);
      const roll = obj.roll ? THREE.MathUtils.degToRad(-obj.roll) : 0;

      if (isModelLoaded) {
        // Usually models pivot on the bottom
        dummy.scale.set(1, 1, 1);
        dummy.position.set(posX, posY, posZ);
        dummy.rotation.set(pitch, yaw, roll, 'YXZ');
      } else {
        // Box needs to be scaled up and shifted by half height
        dummy.scale.set(w * sX, h * sY, l * sZ);
        dummy.position.set(posX, posY, posZ);
        dummy.rotation.set(pitch, yaw, roll, 'YXZ');
      }

      dummy.updateMatrix();
      instancedMesh.setMatrixAt(index, dummy.matrix);
    });

    instancedMesh.instanceMatrix.needsUpdate = true;
    instancedMesh.userData.objects = group.objects;
    threeScene.add(instancedMesh);
    categoryMeshes[group.category].push(instancedMesh);
    allInstancedMeshes.push(instancedMesh);
  }

  // 5. Fetch and render road network from roadnet.json polylines
  // Road colors match the roads.png convention:
  //   Track: #D6C2A6, Road: #B2B2B2, Main Road: #E6804C
  statusText.innerText = 'Loading road network...';
  try {
    const roadsRes = await fetch(
      `map/${mapSelect.value}/roads_in_region?minX=${armaMinX}&maxX=${armaMaxX}&minY=${armaMinY}&maxY=${armaMaxY}`
    );
    if (roadsRes.ok) {
      const roadsJson = await roadsRes.json();
      const regionRoads = roadsJson.roads || [];

      if (regionRoads.length > 0) {
        const roadColors = {
          track:    { color: 0xD6C2A6, roughness: 0.9, metalness: 0.0 },
          road:     { color: 0xB2B2B2, roughness: 0.85, metalness: 0.05 },
          mainRoad: { color: 0xE6804C, roughness: 0.8, metalness: 0.1 },
        };

        const roadGeosByType = { track: [], road: [], mainRoad: [] };

        regionRoads.forEach(road => {
          const pts = road.pts;
          if (!pts || pts.length < 2) return;

          const roadType = road.type || 'road';
          const roadWidth = (road.width && road.width > 0.5) ? road.width : 10.0;
           const roadThickness = 0.5;
           const heightOffset = 0.35; // Safe clearance above terrain

          // Build a strip geometry along the polyline
          const verts = [];
          const indices = [];
          const uvs = [];

           for (let i = 0; i < pts.length; i++) {
             const pt = pts[i];
             const armaX = pt[0];
             const armaY = pt[1];

             // Direction of the segment at this point
             let dirX = 0, dirY = 0;
             if (i === 0 && pts.length > 1) {
               dirX = pts[1][0] - pts[0][0];
               dirY = pts[1][1] - pts[0][1];
             } else if (i === pts.length - 1 && pts.length > 1) {
               dirX = pts[i][0] - pts[i-1][0];
               dirY = pts[i][1] - pts[i-1][1];
             } else if (pts.length > 2) {
               dirX = pts[i+1][0] - pts[i-1][0];
               dirY = pts[i+1][1] - pts[i-1][1];
             }

             const segLen = Math.sqrt(dirX * dirX + dirY * dirY) || 1;
             const perpX = (-dirY / segLen) * (roadWidth / 2);
             const perpY = (dirX / segLen) * (roadWidth / 2);

             // Sample terrain at left and right edges so the road tilts with cross-slope
             const leftArmaX  = armaX + perpX;
             const leftArmaY  = armaY + perpY;
             const rightArmaX = armaX - perpX;
             const rightArmaY = armaY - perpY;

             const terrainHLeft  = getTerrainHeightAt(leftArmaX, leftArmaY);
             const terrainHRight = getTerrainHeightAt(rightArmaX, rightArmaY);

             // Top vertices (road surface) — each edge at its own sampled height
             const tLeftX = leftArmaX - armaCenterX;
             const tLeftY = armaCenterY - leftArmaY;
             verts.push(tLeftX, terrainHLeft + heightOffset, tLeftY);
             uvs.push(0, i / (pts.length - 1));

             const tRightX = rightArmaX - armaCenterX;
             const tRightY = armaCenterY - rightArmaY;
             verts.push(tRightX, terrainHRight + heightOffset, tRightY);
             uvs.push(1, i / (pts.length - 1));

             // Bottom vertices (below road surface for thickness)
             verts.push(tLeftX, terrainHLeft + heightOffset - roadThickness, tLeftY);
             uvs.push(0, i / (pts.length - 1));

             verts.push(tRightX, terrainHRight + heightOffset - roadThickness, tRightY);
             uvs.push(1, i / (pts.length - 1));
           }

          // Build indices for quads along the strip (each step = 4 vertices)
          const numPts = pts.length;
          for (let i = 0; i < numPts - 1; i++) {
            const base = i * 4;
            // Top face (two triangles)
            indices.push(base, base + 1, base + 4);
            indices.push(base + 1, base + 5, base + 4);
            // Bottom face
            indices.push(base + 2, base + 6, base + 3);
            indices.push(base + 3, base + 6, base + 7);
            // Left side
            indices.push(base, base + 4, base + 2);
            indices.push(base + 2, base + 4, base + 6);
            // Right side
            indices.push(base + 1, base + 3, base + 5);
            indices.push(base + 3, base + 7, base + 5);
          }

          const geo = new THREE.BufferGeometry();
          geo.setAttribute('position', new THREE.Float32BufferAttribute(verts, 3));
          geo.setAttribute('uv', new THREE.Float32BufferAttribute(uvs, 2));
          geo.setIndex(indices);
          geo.computeVertexNormals();

          if (!roadGeosByType[roadType]) {
            roadGeosByType[roadType] = [];
          }
          roadGeosByType[roadType].push(geo);
        });

        // Merge and create one mesh per road type (matching PNG colors)
        for (const [roadType, geos] of Object.entries(roadGeosByType)) {
          if (geos.length === 0) continue;

          const mergedGeo = BufferGeometryUtils.mergeGeometries(geos, false);
          const typeColors = roadColors[roadType] || roadColors['road'];

          const roadMat = new THREE.MeshStandardMaterial({
            color: typeColors.color,
            roughness: typeColors.roughness,
            metalness: typeColors.metalness,
            side: THREE.DoubleSide,
            flatShading: true,
            polygonOffset: true,
            polygonOffsetFactor: -1,
            polygonOffsetUnits: -1,
          });

          const roadMesh = new THREE.Mesh(mergedGeo, roadMat);
          roadMesh.receiveShadow = true;
          roadMesh.castShadow = true;
          threeScene.add(roadMesh);
          categoryMeshes['roads'].push(roadMesh);
        }

        statusText.innerText = `Loaded ${validObjects.length.toLocaleString()} objects + ${regionRoads.length} road segments in region.`;
      }
    } else {
      console.warn(`Roads API returned ${roadsRes.status}, no road overlay.`);
    }
  } catch (e) {
    console.error('Failed to fetch roads for region:', e);
  }

  // 6. Render Mission Entities (if a mission is selected)
  if (currentMissionData && currentMissionData.entities) {
    const sideColors = {
      'West': 0x3388ff,
      'Blufor': 0x3388ff,
      'East': 0xff3333,
      'Opfor': 0xff3333,
      'Independent': 0x33cc33,
      'Resistance': 0x33cc33,
      'Civilian': 0xcc88ff,
      'Empty': 0x888888,
      'Unknown': 0xffffff
    };

    // Character type pattern: infantry/crew/pilots only — NOT vehicles ending with _F
    const isCharacter = (type) => {
      const t = type || '';
      // Explicit soldier/crew/pilot patterns
      if (/^(B_|O_|I_|C_)(Soldier|medic|crew|Helipilot|helicrew|Fighter_Pilot|Pilot)/i.test(t)) return true;
      // Specific role suffixes for soldiers
      if (/_(SL|TL|AR|LAT|AT|AA|M|Grenadier|Sharpshooter|Marksman|Engineer|Sniper|Spotter|Recon|Scout|Survivor|Story|CombatLifeSaver|Repair|Explosive|UAV|JTAC|HeliCrew)_F$/i.test(t)) return true;
      // Generic soldier/medic/crew/pilot suffixes
      if (/_(Soldier|medic|crew|Pilot|Helipilot|helicrew|fighter_Pilot)_F$/i.test(t)) return true;
      return false;
    };

    // Filter mission entities to region
    const missionEntities = currentMissionData.entities.filter(e => {
      const ex = e.x || 0;
      const ez = e.z || 0;
      return ex >= armaMinX && ex <= armaMaxX && ez >= armaMinY && ez <= armaMaxY;
    });

    const characterModelName = 'characters_f_templatertm_male.glb';
    let characterGlbGeo = null;
    let characterGlbMat = null;

    // Try load the character template model
    try {
      const charGltf = await gltfLoader.loadAsync(`models/${characterModelName}`);
      charGltf.scene.traverse((child) => {
        if (child.isMesh && !characterGlbGeo) {
          characterGlbGeo = child.geometry;
          characterGlbMat = new THREE.MeshStandardMaterial({
            color: 0x3388ff,
            roughness: 0.5,
            metalness: 0.2,
            flatShading: true
          });
        }
      });
      if (characterGlbGeo) {
        console.log('Loaded character template model for mission units.');
      }
    } catch (e) {
      console.warn('Character template model not available, using spheres:', e.message);
    }

    // Pre-load GLB model cache for mission entity types
    const missionModelCache = {};
    if (characterGlbGeo) {
      missionModelCache['CHARACTER'] = { geo: characterGlbGeo, mat: characterGlbMat };
    }

    // Load class_to_glb.json for correct model filenames
    let classToGlb = {};
    try {
      const glbRes = await fetch(`mission/${missionSelect.value}/class_to_glb.json`);
      if (glbRes.ok) classToGlb = await glbRes.json();
    } catch (e) {}

    // Try to load GLB models for each unique non-character type
    const uniqueTypes = [...new Set(missionEntities.map(e => e.type || 'Unknown'))];
    const loadPromises = uniqueTypes.map(async (type) => {
      if (isCharacter(type)) return; // Already handled
      // Use the mapping if available, otherwise fall back to lowercased type
      const glbName = classToGlb[type] || (type.toLowerCase() + '.glb');
      try {
        const gltf = await gltfLoader.loadAsync(`models/${glbName}`);
        let loadedGeo = null;
        gltf.scene.traverse((child) => {
          if (child.isMesh && !loadedGeo) loadedGeo = child.geometry;
        });
        if (loadedGeo) {
          missionModelCache[type] = { geo: loadedGeo, mat: new THREE.MeshStandardMaterial({
            color: sideColors['Empty'],
            roughness: 0.5,
            metalness: 0.2,
            flatShading: true
          })};
          console.log(`Loaded GLB model for mission entity: ${type}`);
        }
      } catch (e) {
        // GLB not available, will use fallback shapes
      }
    });
    await Promise.all(loadPromises);

    // Group by type for instanced rendering
    const missionByType = {};
    missionEntities.forEach(e => {
      const type = e.type || 'Unknown';
      const modelKey = isCharacter(type) ? 'CHARACTER' : type;
      if (!missionByType[modelKey]) {
        missionByType[modelKey] = [];
      }
      missionByType[modelKey].push(e);
    });

    const sphereGeo = new THREE.SphereGeometry(2, 8, 8);
    const smallBoxGeo = new THREE.BoxGeometry(3, 3, 3);

    for (const [modelKey, entities] of Object.entries(missionByType)) {
      const side = entities[0]?.side || 'Empty';
      const type = entities[0]?.type || modelKey;
      const color = sideColors[side] || sideColors['Empty'];
      const isChar = isCharacter(type);
      
      let geo, mat, modelLoaded = false, usedModelName = null;

      // Check if we have a cached GLB model for this type
      if (missionModelCache[modelKey]) {
        const cached = missionModelCache[modelKey];
        geo = cached.geo;
        mat = cached.mat.clone();
        mat.color.set(color);
        mat.emissive = new THREE.Color(color);
        mat.emissiveIntensity = 0.3;
        modelLoaded = true;
        usedModelName = isChar ? 'characters_f_templateRTM_Male.glb' : `${type}.glb`;
      } else {
        // Fallback shapes
        const isVehicle = type.includes('Heli_') || type.includes('MBT_') || type.includes('Plane_') 
          || type.includes('Tank') || type.includes('Car') || type.includes('Transport')
          || type.includes('Warfare') || type.includes('Radar') || type.includes('Crate');
        geo = isVehicle ? smallBoxGeo : sphereGeo;
        mat = new THREE.MeshStandardMaterial({
          color: color,
          roughness: 0.5,
          metalness: 0.3,
          emissive: color,
          emissiveIntensity: 0.4
        });
      }

      const count = entities.length;
      const instancedMesh = new THREE.InstancedMesh(geo, mat, count);
      instancedMesh.castShadow = true;
      instancedMesh.receiveShadow = true;

      const dummyMission = new THREE.Object3D();
      entities.forEach((entity, index) => {
        const posX = entity.x - armaCenterX;
        const posZ = -(entity.z - armaCenterY);
        const terrainH = getTerrainHeightAt(entity.x, entity.z);
        const posY = Math.max(entity.y || terrainH, terrainH) + (isChar && modelLoaded ? 0.0 : 2.0);

        dummyMission.position.set(posX, posY, posZ);
        dummyMission.scale.set(1, 1, 1);
        if (entity.azimuth) {
          // SQM azimuth is already in radians; negate for Three.js Y rotation direction
          dummyMission.rotation.set(0, -(entity.azimuth), 0, 'YXZ');
        } else {
          dummyMission.rotation.set(0, 0, 0);
        }
        dummyMission.updateMatrix();
        instancedMesh.setMatrixAt(index, dummyMission.matrix);
      });

      instancedMesh.instanceMatrix.needsUpdate = true;
      instancedMesh.userData.isMissionEntity = true;
      instancedMesh.userData.entityType = type;
      instancedMesh.userData.entitySide = side;
      instancedMesh.userData.entityModelName = usedModelName || `${type}.glb`;
      instancedMesh.userData.missionObjects = entities;
      instancedMesh.userData.isBoundingBox = !modelLoaded;
      threeScene.add(instancedMesh);

      if (!categoryMeshes['buildings']) categoryMeshes['buildings'] = [];
      categoryMeshes['buildings'].push(instancedMesh);
      allInstancedMeshes.push(instancedMesh);
    }

    const missionCount = missionEntities.length;
    statObjects.innerText = `${validObjects.length + missionCount} (${missionCount} mission)`;
    statusText.innerText = `Loaded ${validObjects.length.toLocaleString()} map objects + ${missionCount} mission entities.`;
  }

  // 7. Connect UI Filters
  const filters = {
    buildings: document.getElementById('filter-buildings'),
    nature: document.getElementById('filter-nature'),
    clutter: document.getElementById('filter-clutter'),
    roads: document.getElementById('filter-roads'),
    structures: document.getElementById('filter-structures'),
    lamps: document.getElementById('filter-lamps')
  };

  const filterModelsOnly = document.getElementById('filter-models-only');
  const filterTerrainTexture = document.getElementById('filter-terrain-texture');

  function updateVisibility() {
    for (const [key, checkbox] of Object.entries(filters)) {
      if (!checkbox) continue;
      const isCategoryVisible = checkbox.checked;
      const hideBboxes = filterModelsOnly.checked;

      categoryMeshes[key].forEach(mesh => {
        // Visible if the category is checked AND (it's a model OR we aren't hiding bboxes)
        mesh.visible = isCategoryVisible && !(hideBboxes && mesh.userData.isBoundingBox);
      });
    }

    // Toggle terrain texture on/off
    if (terrainMat && terrainTextureImage && filterTerrainTexture) {
      if (filterTerrainTexture.checked) {
        terrainMat.color.set(0xffffff);
        terrainMat.map = terrainMat.userData._terrainClassTex || null;
        terrainMat.needsUpdate = true;
      } else {
        terrainMat.color.set(0x3f4e4f);  // old gray
        terrainMat.map = null;
        terrainMat.needsUpdate = true;
      }
    }
  }

  for (const checkbox of Object.values(filters)) {
    if (checkbox) checkbox.addEventListener('change', updateVisibility);
  }
  if (filterModelsOnly) filterModelsOnly.addEventListener('change', updateVisibility);
  if (filterTerrainTexture) filterTerrainTexture.addEventListener('change', updateVisibility);

  // Set initial visibility
  updateVisibility();

  // Cleanup handler for back button
  btnBack.onclick = () => {
    mapSelect.disabled = false;
    const urlParams = new URLSearchParams(window.location.search);
    urlParams.delete('x');
    urlParams.delete('y');
    urlParams.delete('w');
    urlParams.delete('h');
    window.history.replaceState({}, '', `${window.location.pathname}?${urlParams.toString()}`);

    isRendering = false;
    const btnFps = document.getElementById('btn-fps');
    if (btnFps) {
      btnFps.style.background = '';
      btnFps.innerText = 'First Person (1.7m)';
    }
    view3d.classList.add('hidden');
    view2d.classList.remove('hidden');
    document.getElementById('object-info-panel').classList.add('hidden');
    const labelsContainer = document.getElementById('labels-container');
    labelsContainer.innerHTML = '';
    nameLabels = [];
    if (threeRenderer) {
      webglContainer.removeChild(threeRenderer.domElement);
      threeRenderer.dispose();
      threeRenderer = null;
    }
  };

  // Interaction / Selection
  let isFpsPlacementMode = false;
  const btnFps = document.getElementById('btn-fps');
  if (btnFps) {
    btnFps.onclick = () => {
      isFpsPlacementMode = !isFpsPlacementMode;
      btnFps.style.background = isFpsPlacementMode ? 'rgba(56, 189, 248, 0.5)' : '';
      btnFps.innerText = isFpsPlacementMode ? 'Cancel First Person' : 'First Person (1.7m)';
    };
  }

  const raycaster = new THREE.Raycaster();
  const mouse = new THREE.Vector2();
  const highlightMat = new THREE.MeshBasicMaterial({ color: 0xff0000, wireframe: true, depthTest: false });
  const highlightMesh = new THREE.Mesh(new THREE.BufferGeometry(), highlightMat);
  highlightMesh.visible = false;
  threeScene.add(highlightMesh);

  webglContainer.addEventListener('click', (e) => {
    if (!isRendering) return;
    const rect = webglContainer.getBoundingClientRect();
    mouse.x = ((e.clientX - rect.left) / rect.width) * 2 - 1;
    mouse.y = -((e.clientY - rect.top) / rect.height) * 2 + 1;

    raycaster.setFromCamera(mouse, threeCamera);

    if (isFpsPlacementMode) {
      const terrainIntersects = raycaster.intersectObject(terrainMesh);
      if (terrainIntersects.length > 0) {
        const hit = terrainIntersects[0].point;
        threeCamera.position.set(hit.x, hit.y + 1.7, hit.z);
        const dir = new THREE.Vector3(0, 0, -1).applyQuaternion(threeCamera.quaternion);
        threeControls.target.set(hit.x + dir.x * 0.1, hit.y + 1.7 + dir.y * 0.1, hit.z + dir.z * 0.1);
        threeControls.maxPolarAngle = Math.PI; // Allow looking up
        threeControls.update();
        
        isFpsPlacementMode = false;
        if (btnFps) {
          btnFps.style.background = '';
          btnFps.innerText = 'First Person (1.7m)';
        }
      }
      return;
    }

    // Calculate objects intersecting the picking ray
    const intersects = raycaster.intersectObjects(allInstancedMeshes, false);

    if (intersects.length > 0) {
      // Find the first visible intersection
      const hit = intersects.find(i => i.object.visible);
      if (hit && hit.instanceId !== undefined) {
        // Check if it's a mission entity
        if (hit.object.userData.isMissionEntity) {
          const missionData = hit.object.userData.missionObjects[hit.instanceId];
          document.getElementById('object-info-panel').classList.remove('hidden');
          document.getElementById('info-class').innerText = missionData.type || "Unknown";
          // Show the model name that was used for this entity type
          const modelName = hit.object.userData.entityModelName || `${missionData.type}.p3d`;
          document.getElementById('info-model').innerText = `${missionData.side || ''} | Model: ${modelName}`;
        } else {
          const objData = hit.object.userData.objects[hit.instanceId];
          document.getElementById('object-info-panel').classList.remove('hidden');
          document.getElementById('info-class').innerText = objData.class || "Unknown";
          document.getElementById('info-model').innerText = objData.model || "Unknown";
        }

        // Apply geometry and transform to highlightMesh
        highlightMesh.geometry = hit.object.geometry;
        hit.object.getMatrixAt(hit.instanceId, dummy.matrix);
        dummy.matrix.decompose(highlightMesh.position, highlightMesh.quaternion, highlightMesh.scale);
        highlightMesh.visible = true;
      }
    } else {
      document.getElementById('object-info-panel').classList.add('hidden');
      highlightMesh.visible = false;
    }
  });

  // Handle Resize
  window.onresize = () => {
    if (!threeRenderer) return;
    threeCamera.aspect = window.innerWidth / window.innerHeight;
    threeCamera.updateProjectionMatrix();
    threeRenderer.setSize(window.innerWidth, window.innerHeight);
  };
  
  // Hide loading screen when done setting up
  const loader = document.getElementById('loading-overlay');
  if (loader) loader.classList.add('hidden');
}

async function loadMission(missionName) {
  statusText.innerText = `Loading mission ${missionName}...`;
  try {
    const metaRes = await fetch(`mission/${missionName}/meta.json`);
    const entitiesRes = await fetch(`mission/${missionName}/entities.json`);
    
    if (metaRes.ok && entitiesRes.ok) {
      const meta = await metaRes.json();
      const entities = await entitiesRes.json();
      currentMissionData = { meta, entities };
      
      statusText.innerText = `Mission loaded: ${meta.name || missionName} - ${entities.length} entities.`;
      
      // Auto-select matching map if available
      if (meta.map_name) {
        const mapOptions = mapSelect.options;
        for (let i = 0; i < mapOptions.length; i++) {
          if (mapOptions[i].text.toLowerCase().includes(meta.map_name.toLowerCase())) {
            mapSelect.value = mapOptions[i].value;
            loadMap(mapOptions[i].value);
            break;
          }
        }
      }
    } else {
      currentMissionData = null;
      statusText.innerText = `Failed to load mission data.`;
    }
  } catch (e) {
    console.error('Error loading mission:', e);
    currentMissionData = null;
  }
}

// Start
init();
