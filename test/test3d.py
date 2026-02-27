import time
from e2b_code_interpreter import Sandbox
from dotenv import load_dotenv

load_dotenv()

INDEX_HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>3D Racer</title>
    <style>
        body { margin: 0; background-color: #87CEEB; overflow: hidden; font-family: monospace; }
        #ui { position: absolute; top: 20px; left: 20px; z-index: 10; color: white; text-shadow: 2px 2px 0 #000; }
        h1 { margin: 0; }
    </style>
    <script type="importmap">
        { "imports": { "three": "https://unpkg.com/three@0.160.0/build/three.module.js", "three/addons/": "https://unpkg.com/three@0.160.0/examples/jsm/" } }
    </script>
</head>
<body>
    <div id="ui">
        <h1>KENNEY RACER</h1>
        <p>ARROWS to Drive</p>
    </div>
    <script type="module" src="game.js"></script>
</body>
</html>
"""

GAME_JS = """
import * as THREE from 'three';
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';

// --- PATHS FROM YOUR FILE ---
const CAR_PATH = 'assets/3d/car_kit/Models/GLB format/race.glb';
const CONE_PATH = 'assets/3d/car_kit/Models/GLB format/cone.glb';

// --- SETUP ---
const scene = new THREE.Scene();
scene.background = new THREE.Color(0x87CEEB);
scene.fog = new THREE.Fog(0x87CEEB, 20, 100);

const camera = new THREE.PerspectiveCamera(75, window.innerWidth / window.innerHeight, 0.1, 1000);
camera.position.set(0, 5, -10);

const renderer = new THREE.WebGLRenderer({ antialias: true });
renderer.setSize(window.innerWidth, window.innerHeight);
renderer.shadowMap.enabled = true;
document.body.appendChild(renderer.domElement);

// --- LIGHTS ---
const dirLight = new THREE.DirectionalLight(0xffffff, 1.5);
dirLight.position.set(20, 50, 20);
dirLight.castShadow = true;
dirLight.shadow.mapSize.width = 2048;
dirLight.shadow.mapSize.height = 2048;
scene.add(dirLight);
scene.add(new THREE.AmbientLight(0xffffff, 0.5));

// --- GROUND ---
const ground = new THREE.Mesh(
    new THREE.PlaneGeometry(1000, 1000),
    new THREE.MeshStandardMaterial({ color: 0x555555, roughness: 0.8 })
);
ground.rotation.x = -Math.PI / 2;
ground.receiveShadow = true;
scene.add(ground);

// --- GAME OBJECTS ---
const loader = new GLTFLoader();
const carGroup = new THREE.Group();
scene.add(carGroup);
let car;

// Load Car
loader.load(CAR_PATH, (gltf) => {
    car = gltf.scene;
    // Fix: Kenney cars usually face +Z or -Z, we rotate to face forward (+Z)
    car.rotation.y = Math.PI; 
    car.traverse(c => { if(c.isMesh) c.castShadow = true; });
    carGroup.add(car);
}, undefined, console.error);

// Load Cones
loader.load(CONE_PATH, (gltf) => {
    const coneModel = gltf.scene;
    for(let i=0; i<30; i++) {
        const cone = coneModel.clone();
        const x = (Math.random() - 0.5) * 100;
        const z = (Math.random() - 0.5) * 100;
        if(Math.abs(x) < 5 && Math.abs(z) < 5) continue; // Safety zone
        
        cone.position.set(x, 0, z);
        cone.traverse(c => { if(c.isMesh) c.castShadow = true; });
        scene.add(cone);
    }
}, undefined, console.error);

// --- CONTROLS ---
let speed = 0, angle = 0;
const keys = { ArrowUp: false, ArrowDown: false, ArrowLeft: false, ArrowRight: false };
window.addEventListener('keydown', e => keys[e.code] = true);
window.addEventListener('keyup', e => keys[e.code] = false);

// --- LOOP ---
function animate() {
    requestAnimationFrame(animate);

    if (keys.ArrowUp) speed += 0.02;
    if (keys.ArrowDown) speed -= 0.02;
    speed *= 0.96; // Friction

    if (Math.abs(speed) > 0.01) {
        if (keys.ArrowLeft) angle += 0.05;
        if (keys.ArrowRight) angle -= 0.05;
    }

    carGroup.rotation.y = angle;
    carGroup.position.x += Math.sin(angle) * speed;
    carGroup.position.z += Math.cos(angle) * speed;

    // Camera follow
    const relativeOffset = new THREE.Vector3(0, 5, -10);
    const cameraOffset = relativeOffset.applyMatrix4(carGroup.matrixWorld);
    camera.position.lerp(cameraOffset, 0.1);
    camera.lookAt(carGroup.position);

    renderer.render(scene, camera);
}
animate();

window.addEventListener('resize', () => {
    camera.aspect = window.innerWidth / window.innerHeight;
    camera.updateProjectionMatrix();
    renderer.setSize(window.innerWidth, window.innerHeight);
});
"""

def test_3d_game():
    print("🚀 Building 3D Racer...")
    sbx = Sandbox.create(template="game-gen-pre-v1")
    try:
        sbx.files.write("/home/user/game/game.js", GAME_JS)
        sbx.files.write("/home/user/game/index.html", INDEX_HTML)
        host = sbx.get_host(3000)
        print(f"✅ 3D GAME READY: https://{host}")
        time.sleep(300)
    finally:
        sbx.kill()

if __name__ == "__main__":
    test_3d_game()
