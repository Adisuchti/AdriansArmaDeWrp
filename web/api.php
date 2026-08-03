<?php
// api.php
header('Access-Control-Allow-Origin: *');

$action = $_GET['action'] ?? '';

if (!$action) {
    http_response_code(400);
    header('Content-Type: application/json');
    die(json_encode(["error" => "Missing action parameter"]));
}

if ($action === 'maps') {
    $mapDir = __DIR__ . '/map';
    $maps = [];
    if (is_dir($mapDir)) {
        $files = scandir($mapDir);
        foreach ($files as $file) {
            if ($file !== '.' && $file !== '..' && is_dir($mapDir . '/' . $file)) {
                $maps[] = $file;
            }
        }
    }
    header('Content-Type: application/json');
    echo json_encode(['maps' => array_values($maps)]);
    exit;
}

if ($action === 'missions') {
    $missionsFile = __DIR__ . '/missions/missions.json';
    header('Content-Type: application/json');
    if (file_exists($missionsFile)) {
        echo file_get_contents($missionsFile);
    } else {
        echo json_encode(['missions' => []]);
    }
    exit;
}

$map = $_GET['map'] ?? '';
if (!$map) {
    http_response_code(400);
    header('Content-Type: application/json');
    die(json_encode(["error" => "Missing map parameter"]));
}

$minX = isset($_GET['minX']) ? (float)$_GET['minX'] : null;
$maxX = isset($_GET['maxX']) ? (float)$_GET['maxX'] : null;
$minY = isset($_GET['minY']) ? (float)$_GET['minY'] : null;
$maxY = isset($_GET['maxY']) ? (float)$_GET['maxY'] : null;

if ($minX === null || $maxX === null || $minY === null || $maxY === null) {
    http_response_code(400);
    header('Content-Type: application/json');
    die(json_encode(["error" => "Missing bounding box parameters"]));
}

// Adjust this path if your map folders are placed somewhere else
$mapFolder = __DIR__ . "/map/" . basename($map);

if ($action === 'objects_in_region') {
    $objectsFile = $mapFolder . "/objects.json";
    if (!file_exists($objectsFile)) {
        http_response_code(404);
        header('Content-Type: application/json');
        die(json_encode(["error" => "objects.json not found"]));
    }
    
    // Output NDJSON directly
    header('Content-type: application/x-ndjson');
    
    $handle = fopen($objectsFile, "r");
    if ($handle) {
        $buffer = "";
        
        // Find the start of the objects array
        while (!feof($handle)) {
            $chunk = fread($handle, 65536);
            if ($chunk === false) break;
            $buffer .= $chunk;
            
            $pos = strpos($buffer, '"objects"');
            if ($pos !== false) {
                $bracketPos = strpos($buffer, '[', $pos);
                if ($bracketPos !== false) {
                    $buffer = substr($buffer, $bracketPos + 1);
                    break;
                }
            }
            // Failsafe to prevent unbounded memory growth if not found quickly
            if (strlen($buffer) > 1024 * 1024) {
                break;
            }
        }
        
        // Now parse objects one by one
        $braceCount = 0;
        $objStr = "";
        $inString = false;
        $escape = false;
        
        while (!feof($handle) || $buffer !== "") {
            if ($buffer === "" && !feof($handle)) {
                $buffer = fread($handle, 65536);
            }
            
            for ($i = 0; $i < strlen($buffer); $i++) {
                $char = $buffer[$i];
                
                if ($braceCount > 0) {
                    $objStr .= $char;
                    
                    if ($inString) {
                        if ($escape) {
                            $escape = false;
                        } elseif ($char === '\\') {
                            $escape = true;
                        } elseif ($char === '"') {
                            $inString = false;
                        }
                    } else {
                        if ($char === '"') {
                            $inString = true;
                        } elseif ($char === '{') {
                            $braceCount++;
                        } elseif ($char === '}') {
                            $braceCount--;
                            if ($braceCount === 0) {
                                $obj = json_decode($objStr, true);
                                if ($obj && isset($obj['x']) && isset($obj['y'])) {
                                    if ($obj['x'] >= $minX && $obj['x'] <= $maxX && $obj['y'] >= $minY && $obj['y'] <= $maxY) {
                                        echo json_encode($obj, JSON_UNESCAPED_SLASHES) . "\n";
                                        flush(); // Important to push NDJSON immediately
                                    }
                                }
                                $objStr = "";
                            }
                        }
                    }
                } else {
                    if ($char === '{') {
                        $braceCount = 1;
                        $objStr = "{";
                    } elseif ($char === ']') {
                        break 2;
                    }
                }
            }
            $buffer = ""; // consumed
        }
        fclose($handle);
    }
    exit;
} elseif ($action === 'roads_in_region') {
    $roadsFile = $mapFolder . "/roadnet.json";
    if (!file_exists($roadsFile)) {
        http_response_code(404);
        header('Content-Type: application/json');
        die(json_encode(["error" => "roadnet.json not found"]));
    }
    
    header('Content-Type: application/json');
    $data = file_get_contents($roadsFile);
    $roadnet = json_decode($data, true);
    $matchingRoads = [];
    
    if (isset($roadnet['roads']) && is_array($roadnet['roads'])) {
        foreach ($roadnet['roads'] as $road) {
            if (!isset($road['pts']) || count($road['pts']) < 2) continue;
            
            $intersects = false;
            for ($i = 0; $i < count($road['pts']) - 1; $i++) {
                $p1 = $road['pts'][$i];
                $p2 = $road['pts'][$i+1];
                
                if (($minX <= $p1[0] && $p1[0] <= $maxX && $minY <= $p1[1] && $p1[1] <= $maxY) ||
                    ($minX <= $p2[0] && $p2[0] <= $maxX && $minY <= $p2[1] && $p2[1] <= $maxY)) {
                    $intersects = true;
                    break;
                }
                
                $segMinX = min($p1[0], $p2[0]);
                $segMaxX = max($p1[0], $p2[0]);
                $segMinY = min($p1[1], $p2[1]);
                $segMaxY = max($p1[1], $p2[1]);
                
                if ($segMaxX < $minX || $segMinX > $maxX || $segMaxY < $minY || $segMinY > $maxY) {
                    continue; 
                }
                
                $intersects = true;
                break;
            }
            
            if ($intersects) {
                $matchingRoads[] = [
                    'type' => $road['type'] ?? 'road',
                    'width' => $road['width'] ?? 10.0,
                    'pts' => $road['pts']
                ];
            }
        }
    }
    
    echo json_encode(["roads" => $matchingRoads]);
    exit;
} else {
    http_response_code(400);
    header('Content-Type: application/json');
    die(json_encode(["error" => "Invalid action"]));
}
