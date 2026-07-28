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
let isDragging = false;
let startX, startY;
let currentSelection = null; // {x, y, w, h} in canvas CSS pixels
let objectData = null; // parsed JSON
let classificationData = {}; // parsed classification lookup
let threeScene, threeCamera, threeRenderer, threeControls;

const mapSelect = document.getElementById('map-select');

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

    // 3. No longer loading all objects upfront — they will be fetched per-region in render3D()
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

  const terrainMat = new THREE.MeshStandardMaterial({
    color: 0x3f4e4f,
    roughness: 0.8,
    flatShading: true
  });
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
      const regionJson = await regionRes.json();
      validObjects = regionJson.objects || [];
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
  
  const roadGeometries = [];
  const roadMaterial = new THREE.MeshStandardMaterial({
    color: 0x2b2d31, // Dark asphalt color
    roughness: 0.95,
    metalness: 0.05,
    side: THREE.DoubleSide
  });

  // Start Animation Loop early so models stream in
  let isRendering = true;
  function animate() {
    if (!threeRenderer || !isRendering) return;
    requestAnimationFrame(animate);
    threeControls.update();
    threeRenderer.render(threeScene, threeCamera);
  }
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
      group.objects.forEach(obj => {
        const posX = obj.x - armaCenterX;
        const posZ = -(obj.y - armaCenterY);

        const w = obj.w || 1;
        const l = obj.l || 1;
        const sX = (obj.scaleX !== undefined ? obj.scaleX : 1);
        const sZ = (obj.scaleZ !== undefined ? obj.scaleZ : 1);
        
        const roadWidth = (w * sX > 0.5) ? (w * sX) : 6;
        const roadLength = (l * sZ > 0.5) ? (l * sZ) : 10;

        const segX = Math.max(1, Math.ceil(roadWidth / 2));
        const segY = Math.max(1, Math.ceil(roadLength / 2));

        const roadGeo = new THREE.PlaneGeometry(roadWidth, roadLength, segX, segY);
        roadGeo.rotateX(-Math.PI / 2);
        roadGeo.rotateY(THREE.MathUtils.degToRad(-obj.dir));
        roadGeo.translate(posX, 0, posZ);

        const positions = roadGeo.attributes.position;
        for (let i = 0; i < positions.count; i++) {
          const vx = positions.getX(i);
          const vz = positions.getZ(i);
          const armaX = vx + armaCenterX;
          const armaY = armaCenterY - vz;
          const vy = getTerrainHeightAt(armaX, armaY) + 0.25;
          positions.setY(i, vy);
        }

        roadGeo.computeVertexNormals();
        roadGeometries.push(roadGeo);
      });
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

  if (roadGeometries.length > 0) {
    const mergedRoadGeo = BufferGeometryUtils.mergeGeometries(roadGeometries, false);
    const roadMesh = new THREE.Mesh(mergedRoadGeo, roadMaterial);
    roadMesh.receiveShadow = true;
    threeScene.add(roadMesh);
    categoryMeshes['roads'].push(roadMesh);
  }

  // 5. Connect UI Filters
  const filters = {
    buildings: document.getElementById('filter-buildings'),
    nature: document.getElementById('filter-nature'),
    clutter: document.getElementById('filter-clutter'),
    roads: document.getElementById('filter-roads'),
    structures: document.getElementById('filter-structures'),
    lamps: document.getElementById('filter-lamps')
  };

  const filterModelsOnly = document.getElementById('filter-models-only');

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
  }

  for (const checkbox of Object.values(filters)) {
    if (checkbox) checkbox.addEventListener('change', updateVisibility);
  }
  if (filterModelsOnly) filterModelsOnly.addEventListener('change', updateVisibility);

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
    view3d.classList.add('hidden');
    view2d.classList.remove('hidden');
    document.getElementById('object-info-panel').classList.add('hidden');
    if (threeRenderer) {
      webglContainer.removeChild(threeRenderer.domElement);
      threeRenderer.dispose();
      threeRenderer = null;
    }
  };

  // Interaction / Selection
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

    // Calculate objects intersecting the picking ray
    const intersects = raycaster.intersectObjects(allInstancedMeshes, false);

    if (intersects.length > 0) {
      // Find the first visible intersection
      const hit = intersects.find(i => i.object.visible);
      if (hit && hit.instanceId !== undefined) {
        const objData = hit.object.userData.objects[hit.instanceId];

        document.getElementById('object-info-panel').classList.remove('hidden');
        document.getElementById('info-class').innerText = objData.class || "Unknown";
        document.getElementById('info-model').innerText = objData.model || "Unknown";

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
  document.getElementById('loading-overlay').classList.add('hidden');
}

// Start
init();
