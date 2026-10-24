import { useEffect, useRef } from "react";
import * as THREE from "three";
import { OrbitControls } from "three/examples/jsm/controls/OrbitControls.js";
import type { Cascade, CityBuilding, CityGraph, CitySnapshot, MapSelection } from "../types";

export type ViewMode = "before" | "present" | "whatif";

interface Props {
  graph: CityGraph | null;
  state: CitySnapshot | null;
  beforeState: CitySnapshot | null;
  whatIfState: CitySnapshot | null;
  cascade: Cascade | null;
  viewMode: ViewMode;
  onSelect?: (selection: MapSelection | null, additive?: boolean) => void;
  selectedId?: string | null;
  selectedIds?: string[];
  outageNodeIds?: string[];
  routeResult?: Record<string, unknown> | null;
  layers?: { power: boolean; traffic: boolean; emergency: boolean; reports: boolean };
}

interface Handles {
  edgeMeshes: Map<string, THREE.Mesh>;
  edgeBase: Map<string, number>;
  floodMeshes: Map<string, THREE.Mesh>;
  congestionMeshes: Map<string, THREE.Mesh>;
  nodeMeshes: Map<string, THREE.Mesh>;
  signalMeshes: Map<string, THREE.Mesh>;
  ambulance: THREE.Mesh | null;
}

const C = {
  bg: 0x0b0e14,
  ground: 0x111925,
  road: 0x263142,
  roadEdge: 0x415066,
  underpass: 0x3b4658,
  flooded: 0x1267d6,
  closed: 0x7c3aed,
  congested: 0xff9f1c,
  rerouted: 0x22d3ee,
  junction: 0x94a3b8,
  dark: 0x4a1520,
  hospital: 0x22c55e,
  substation: 0xf59e0b,
  depot: 0xe2e8f0,
  sigOn: 0x22c55e,
  sigOff: 0xef4444,
  cascade: 0xfacc15,
  ambulance: 0xffe066,
  lane: 0xcbd5e1,
  window: 0x8be9fd,
};

const toWorld = (x: number, y: number): [number, number] => [x, -y];

function addCity<T extends THREE.Object3D>(scene: THREE.Scene, object: T): T {
  (object as any).__city = true;
  scene.add(object);
  return object;
}

function makeFloodMaterial() {
  return new THREE.ShaderMaterial({
    uniforms: { time: { value: 0 }, color: { value: new THREE.Color(C.flooded) } },
    transparent: true,
    side: THREE.DoubleSide,
    vertexShader: `varying vec2 vUv; uniform float time; void main(){ vUv=uv; vec3 p=position; p.y += sin((p.x+p.z)*8.0+time*3.0)*0.012; gl_Position=projectionMatrix*modelViewMatrix*vec4(p,1.0); }`,
    fragmentShader: `varying vec2 vUv; uniform float time; uniform vec3 color; void main(){ float wave=0.55+0.2*sin((vUv.x+vUv.y)*18.0+time*4.0); gl_FragColor=vec4(color*wave,0.8); }`,
  });
}

function makeCongestionMaterial() {
  return new THREE.ShaderMaterial({
    uniforms: { time: { value: 0 }, color: { value: new THREE.Color(C.congested) } },
    transparent: true,
    depthWrite: false,
    vertexShader: `varying vec2 vUv; void main(){ vUv=uv; gl_Position=projectionMatrix*modelViewMatrix*vec4(position,1.0); }`,
    fragmentShader: `varying vec2 vUv; uniform float time; uniform vec3 color; void main(){ float pulse=0.55+0.35*sin(time*5.0+vUv.x*12.0); gl_FragColor=vec4(color,pulse); }`,
  });
}

function makePickable(object: THREE.Object3D, type: string, id: string, label: string) {
  object.userData.pickable = true;
  object.userData.entityType = type;
  object.userData.entityId = id;
  object.userData.entityLabel = label;
  return object;
}

function makeStrip(
  scene: THREE.Scene,
  a: [number, number],
  b: [number, number],
  width: number,
  height: number,
  y: number,
  material: THREE.Material
) {
  const dx = b[0] - a[0];
  const dz = b[1] - a[1];
  const len = Math.hypot(dx, dz);
  const mesh = new THREE.Mesh(new THREE.BoxGeometry(len, height, width), material);
  mesh.position.set((a[0] + b[0]) / 2, y, (a[1] + b[1]) / 2);
  mesh.rotation.y = -Math.atan2(dz, dx);
  return addCity(scene, mesh);
}

function addTree(scene: THREE.Scene, x: number, z: number, scale: number) {
  const trunk = new THREE.Mesh(
    new THREE.CylinderGeometry(0.045 * scale, 0.06 * scale, 0.28 * scale, 8),
    new THREE.MeshStandardMaterial({ color: 0x6b4423, roughness: 1 })
  );
  trunk.position.set(x, 0.14 * scale, z);
  addCity(scene, trunk);

  const crown = new THREE.Mesh(
    new THREE.SphereGeometry(0.2 * scale, 10, 8),
    new THREE.MeshStandardMaterial({ color: 0x15803d, roughness: 0.95 })
  );
  crown.position.set(x, 0.4 * scale, z);
  addCity(scene, crown);
}

function addBuilding(
  scene: THREE.Scene,
  x: number,
  z: number,
  width: number,
  depth: number,
  height: number,
  color: number,
  seed: number
) {
  const body = new THREE.Mesh(
    new THREE.BoxGeometry(width, height, depth),
    new THREE.MeshStandardMaterial({ color, roughness: 0.84, metalness: 0.05 })
  );
  body.position.set(x, height / 2, z);
  addCity(scene, body);

  const roof = new THREE.Mesh(
    new THREE.BoxGeometry(width * 1.04, 0.045, depth * 1.04),
    new THREE.MeshStandardMaterial({ color: 0x111827, roughness: 0.75 })
  );
  roof.position.set(x, height + 0.025, z);
  addCity(scene, roof);

  // A few lit facade bands give the skyline a readable, inhabited look without textures.
  if (height > 0.85) {
    const rows = Math.max(1, Math.floor(height / 0.55));
    for (let row = 0; row < rows; row += 1) {
      const window = new THREE.Mesh(
        new THREE.BoxGeometry(width * 0.58, 0.035, 0.012),
        new THREE.MeshStandardMaterial({
          color: C.window,
          emissive: C.window,
          emissiveIntensity: 0.35 + ((seed + row) % 3) * 0.12,
          roughness: 0.4,
        })
      );
      window.position.set(x, 0.28 + row * 0.47, z - depth / 2 - 0.008);
      addCity(scene, window);
    }
  }
}

function addImportedBuilding(scene: THREE.Scene, building: CityBuilding) {
  if (building.footprint.length < 3) return;
  const shape = new THREE.Shape();
  building.footprint.forEach(([x, y], index) => {
    if (index === 0) shape.moveTo(x, y);
    else shape.lineTo(x, y);
  });
  shape.closePath();
  const height = Math.max(0.12, building.height_m / 75);
  const geometry = new THREE.ExtrudeGeometry(shape, { depth: height, bevelEnabled: false });
  geometry.rotateX(-Math.PI / 2);
  const kind = building.kind.toLowerCase();
  const color = kind.includes("industrial") ? 0x475569 : kind.includes("commercial") ? 0x294b63 : 0x25364a;
  const mesh = new THREE.Mesh(
    geometry,
    new THREE.MeshStandardMaterial({ color, roughness: 0.88, metalness: 0.04 })
  );
  mesh.position.y = 0.02;
  mesh.castShadow = true;
  mesh.receiveShadow = true;
  makePickable(mesh, "building", building.id, building.name || building.id);
  addCity(scene, mesh);
}

function addPark(scene: THREE.Scene, x: number, z: number, width: number, depth: number) {
  const park = new THREE.Mesh(
    new THREE.BoxGeometry(width, 0.035, depth),
    new THREE.MeshStandardMaterial({ color: 0x14532d, roughness: 1 })
  );
  park.position.set(x, 0.02, z);
  addCity(scene, park);
  addTree(scene, x - width * 0.25, z - depth * 0.12, 0.8);
  addTree(scene, x + width * 0.2, z + depth * 0.15, 0.65);
  addTree(scene, x + width * 0.05, z - depth * 0.32, 0.55);
}

export default function TwinScene({ graph, state, beforeState, whatIfState, cascade, viewMode, onSelect, selectedId, selectedIds = [], outageNodeIds = [], routeResult, layers = { power: true, traffic: true, emergency: true, reports: true } }: Props) {
  const hostRef = useRef<HTMLDivElement>(null);
  const onSelectRef = useRef(onSelect);
  onSelectRef.current = onSelect;
  const handles = useRef<Handles>({
    edgeMeshes: new Map(),
    edgeBase: new Map(),
    floodMeshes: new Map(),
    nodeMeshes: new Map(),
    signalMeshes: new Map(),
    congestionMeshes: new Map(),
    ambulance: null,
  });

  const snapshot: CitySnapshot | null =
    viewMode === "before" ? beforeState ?? state : viewMode === "whatif" ? whatIfState ?? state : state;

  // ---------- scene setup (once) ----------
  useEffect(() => {
    const host = hostRef.current;
    if (!host) return;

    const scene = new THREE.Scene();
    scene.background = new THREE.Color(C.bg);
    scene.fog = new THREE.Fog(C.bg, 20, 48);

    const camera = new THREE.PerspectiveCamera(42, 1, 0.1, 200);
    camera.position.set(5.6, 8.2, 8.4);

    const renderer = new THREE.WebGLRenderer({ antialias: true, powerPreference: "high-performance" });
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    renderer.outputColorSpace = THREE.SRGBColorSpace;
    renderer.toneMapping = THREE.ACESFilmicToneMapping;
    renderer.toneMappingExposure = 1.1;
    renderer.shadowMap.enabled = true;
    renderer.shadowMap.type = THREE.PCFSoftShadowMap;
    host.appendChild(renderer.domElement);

    const controls = new OrbitControls(camera, renderer.domElement);
    controls.enableDamping = true;
    controls.maxPolarAngle = Math.PI / 2.08;
    controls.minDistance = 4.5;
    controls.maxDistance = 28;
    controls.target.set(2.5, 0, -1.4);

    scene.add(new THREE.HemisphereLight(0x9fb9d5, 0x0b1020, 1.2));
    const sun = new THREE.DirectionalLight(0xffffff, 1.25);
    sun.position.set(7, 13, 7);
    sun.castShadow = true;
    sun.shadow.mapSize.set(1024, 1024);
    sun.shadow.camera.left = -12;
    sun.shadow.camera.right = 12;
    sun.shadow.camera.top = 12;
    sun.shadow.camera.bottom = -12;
    scene.add(sun);

    const ground = new THREE.Mesh(
      new THREE.PlaneGeometry(42, 34),
      new THREE.MeshStandardMaterial({ color: C.ground, roughness: 0.98, metalness: 0 })
    );
    ground.rotation.x = -Math.PI / 2;
    ground.position.set(2.5, -0.04, -1.4);
    ground.receiveShadow = true;
    addCity(scene, ground);

    const grid = new THREE.GridHelper(42, 42, 0x263446, 0x17202d);
    grid.position.set(2.5, -0.015, -1.4);
    (grid.material as THREE.Material).opacity = 0.32;
    (grid.material as THREE.Material).transparent = true;
    addCity(scene, grid);

    const resize = () => {
      const w = host.clientWidth || 1;
      const h = host.clientHeight || 1;
      renderer.setSize(w, h);
      camera.aspect = w / h;
      camera.updateProjectionMatrix();
    };
    resize();
    const ro = new ResizeObserver(resize);
    ro.observe(host);

    const raycaster = new THREE.Raycaster();
    const pointer = new THREE.Vector2();
    const pick = (event: PointerEvent) => {
      const rect = renderer.domElement.getBoundingClientRect();
      pointer.x = ((event.clientX - rect.left) / rect.width) * 2 - 1;
      pointer.y = -((event.clientY - rect.top) / rect.height) * 2 + 1;
      raycaster.setFromCamera(pointer, camera);
      const hit = raycaster.intersectObjects(scene.children, true).find((item) => item.object.userData.pickable);
      if (!hit) {
        onSelectRef.current?.(null);
        return;
      }
      const object = hit.object;
      onSelectRef.current?.({
        id: String(object.userData.entityId),
        type: String(object.userData.entityType),
        label: String(object.userData.entityLabel),
      }, event.shiftKey);
    };
    renderer.domElement.addEventListener("pointerdown", pick);

    let raf = 0;
    const clock = new THREE.Clock();
    const tick = () => {
      const t = clock.getElapsedTime();
      controls.update();
      for (const water of handles.current.floodMeshes.values()) {
        const mat = water.material as THREE.ShaderMaterial;
        if (mat.uniforms?.time) mat.uniforms.time.value = t;
        water.position.y = 0.16;
      }
      for (const glow of handles.current.congestionMeshes.values()) {
        const mat = glow.material as THREE.ShaderMaterial;
        if (mat.uniforms?.time) mat.uniforms.time.value = t;
      }
      renderer.render(scene, camera);
      raf = requestAnimationFrame(tick);
    };
    tick();

    (host as any).__chrono = { scene, camera, renderer, controls };

    return () => {
      cancelAnimationFrame(raf);
      ro.disconnect();
      renderer.domElement.removeEventListener("pointerdown", pick);
      controls.dispose();
      renderer.dispose();
      if (renderer.domElement.parentNode === host) host.removeChild(renderer.domElement);
      scene.traverse((o) => {
        const m = o as THREE.Mesh;
        if (m.geometry) m.geometry.dispose();
        const mat = m.material as THREE.Material | THREE.Material[] | undefined;
        if (Array.isArray(mat)) mat.forEach((x) => x.dispose());
        else mat?.dispose();
      });
    };
  }, []);

  // ---------- build the city whenever the graph arrives ----------
  useEffect(() => {
    const host = hostRef.current as any;
    if (!host?.__chrono || !graph) return;
    const { scene, camera, controls } = host.__chrono as {
      scene: THREE.Scene;
      camera: THREE.PerspectiveCamera;
      controls: OrbitControls;
    };

    const stale: THREE.Object3D[] = [];
    scene.traverse((o) => {
      if ((o as any).__city) stale.push(o);
    });
    stale.forEach((o) => scene.remove(o));
    handles.current = {
      edgeMeshes: new Map(),
      edgeBase: new Map(),
      floodMeshes: new Map(),
      congestionMeshes: new Map(),
      nodeMeshes: new Map(),
      signalMeshes: new Map(),
      ambulance: null,
    };

    const nodePos = new Map<string, [number, number]>();
    graph.nodes.forEach((n) => nodePos.set(n.id, toWorld(n.x, n.y)));

    // Road corridors: carriageway, sidewalks, and lane dashes make the network read as streets.
    for (const e of graph.edges) {
      const a = nodePos.get(e.src);
      const b = nodePos.get(e.dst);
      if (!a || !b) continue;
      const dx = b[0] - a[0];
      const dz = b[1] - a[1];
      const len = Math.hypot(dx, dz);
      const dir: [number, number] = [dx / len, dz / len];
      const normal: [number, number] = [-dir[1], dir[0]];
      const roadWidth = e.kind === "underpass" ? 0.78 : 0.62;
      const road = makeStrip(
        scene,
        a,
        b,
        roadWidth,
        0.08,
        0.06,
        new THREE.MeshStandardMaterial({
          color: e.kind === "underpass" ? C.underpass : C.road,
          roughness: 0.88,
        })
      );
      road.castShadow = true;
      road.receiveShadow = true;
      makePickable(road, "edge", e.id, e.name || e.id);
      handles.current.edgeMeshes.set(e.id, road);
      handles.current.edgeBase.set(e.id, e.length_m / (Math.max(e.free_flow_kph, 1) / 3.6));

      for (const side of [-1, 1]) {
        const offset = roadWidth / 2 + 0.09;
        const sidewalkA: [number, number] = [a[0] + normal[0] * offset * side, a[1] + normal[1] * offset * side];
        const sidewalkB: [number, number] = [b[0] + normal[0] * offset * side, b[1] + normal[1] * offset * side];
        makeStrip(
          scene,
          sidewalkA,
          sidewalkB,
          0.1,
          0.045,
          0.095,
          new THREE.MeshStandardMaterial({ color: C.roadEdge, roughness: 0.95 })
        );
      }

      if (e.kind !== "underpass") {
        const dashLength = Math.min(0.34, len / 6);
        for (let d = 0.42; d < len - 0.25; d += 0.72) {
          const center: [number, number] = [a[0] + dir[0] * d, a[1] + dir[1] * d];
          const dashA: [number, number] = [center[0] - dir[0] * dashLength / 2, center[1] - dir[1] * dashLength / 2];
          const dashB: [number, number] = [center[0] + dir[0] * dashLength / 2, center[1] + dir[1] * dashLength / 2];
          makeStrip(
            scene,
            dashA,
            dashB,
            0.035,
            0.012,
            0.112,
            new THREE.MeshStandardMaterial({ color: C.lane, emissive: C.lane, emissiveIntensity: 0.18 })
          );
        }
      }

      // Water sits above the underpass carriageway and is toggled by the snapshot.
      const water = makeStrip(scene, a, b, roadWidth * 0.86, 0.035, 0.16, makeFloodMaterial());
      water.visible = false;
      handles.current.floodMeshes.set(e.id, water);
      const congestion = makeStrip(scene, a, b, roadWidth * 0.78, 0.018, 0.125, makeCongestionMaterial());
      congestion.visible = false;
      handles.current.congestionMeshes.set(e.id, congestion);

      if (e.kind === "underpass") {
        const portalMaterial = new THREE.MeshStandardMaterial({ color: 0x182235, roughness: 0.92 });
        for (const end of [a, b]) {
          const portal = new THREE.Mesh(new THREE.BoxGeometry(0.12, 0.55, 1.05), portalMaterial.clone());
          portal.position.set(end[0], 0.31, end[1]);
          portal.rotation.y = -Math.atan2(dz, dx);
          addCity(scene, portal);
        }
      }
    }

    for (const asset of graph.infrastructure ?? []) {
      if (asset.kind === "power_line" && !layers.power) continue;
      if (asset.kind !== "power_line" && !layers.traffic) continue;
      const color = asset.kind === "power_line" ? 0xf59e0b : asset.kind === "waterway" ? 0x38bdf8 : 0x60a5fa;
      const points = asset.geometry.map(([x, y]) => toWorld(x, y));
      for (let index = 0; index < points.length - 1; index += 1) {
        const assetMesh = makeStrip(
          scene,
          points[index],
          points[index + 1],
          asset.kind === "power_line" ? 0.06 : 0.11,
          0.045,
          0.2,
          new THREE.MeshStandardMaterial({ color, emissive: color, emissiveIntensity: 0.18, roughness: 0.55 })
        );
        makePickable(assetMesh, asset.kind, asset.id, asset.name || asset.id);
      }
    }

    // Imported OSM footprints are the primary 3D city geometry. The procedural
    // skyline remains as a fallback for the built-in demo graph.
    if (graph.buildings?.length) {
      graph.buildings.forEach((building) => addImportedBuilding(scene, building));
    }

    const buildingColors = [0x1d2a3a, 0x243449, 0x2c3a4d, 0x1b3445, 0x334155];
    const blocks = [
      [-0.55, -2.45, 1.0, 0.72, 6],
      [0.8, 1.42, 1.15, 0.58, 6],
      [2.85, 1.5, 1.18, 0.62, 6],
      [5.15, 1.52, 1.15, 0.62, 6],
      [5.35, -2.45, 1.1, 0.7, 6],
      [3.0, -0.55, 0.72, 0.48, 4],
    ];
    if (!graph.buildings?.length) {
      let seed = 17;
      const rnd = () => {
        seed = (seed * 1664525 + 1013904223) % 4294967296;
        return seed / 4294967296;
      };
      for (const [cx, cz, width, depth, count] of blocks) {
        for (let i = 0; i < count; i += 1) {
          const w = 0.24 + rnd() * 0.24;
          const d = 0.24 + rnd() * 0.24;
          const h = 0.55 + rnd() * 1.55;
          const x = cx + (rnd() - 0.5) * width;
          const z = cz + (rnd() - 0.5) * depth;
          addBuilding(scene, x, z, w, d, h, buildingColors[Math.floor(rnd() * buildingColors.length)], i + Math.floor(cx * 10));
        }
      }
      addPark(scene, -0.55, -0.45, 0.82, 0.58);
      addPark(scene, 4.9, -0.45, 0.78, 0.58);
      addTree(scene, 6.45, -1.7, 0.9);
      addTree(scene, -1.35, -1.0, 0.72);
    }

    // Nodes and recognizable city services.
    for (const n of graph.nodes) {
      if ((n.kind === "hospital" || n.kind === "depot" || n.kind === "shelter") && !layers.emergency) continue;
      if (n.kind === "substation" && !layers.power) continue;
      const [x, z] = toWorld(n.x, n.y);
      let mesh: THREE.Mesh;
      if (n.kind === "hospital") {
        mesh = new THREE.Mesh(
          new THREE.BoxGeometry(0.78, 1.28, 0.78),
          new THREE.MeshStandardMaterial({ color: C.hospital, emissive: 0x0a3d1e, roughness: 0.5 })
        );
        mesh.position.set(x, 0.64, z);
        const roof = new THREE.Mesh(
          new THREE.BoxGeometry(0.92, 0.08, 0.92),
          new THREE.MeshStandardMaterial({ color: 0xe2e8f0, roughness: 0.55 })
        );
        roof.position.set(x, 1.3, z);
        addCity(scene, roof);
      } else if (n.kind === "substation") {
        mesh = new THREE.Mesh(
          new THREE.CylinderGeometry(0.34, 0.42, 0.86, 12),
          new THREE.MeshStandardMaterial({ color: C.substation, emissive: 0x3d2a05, roughness: 0.6 })
        );
        mesh.position.set(x, 0.43, z);
      } else if (n.kind === "depot") {
        mesh = new THREE.Mesh(
          new THREE.BoxGeometry(0.72, 0.42, 0.68),
          new THREE.MeshStandardMaterial({ color: C.depot, roughness: 0.7 })
        );
        mesh.position.set(x, 0.21, z);
      } else {
        mesh = new THREE.Mesh(
          new THREE.CylinderGeometry(0.17, 0.2, 0.16, 10),
          new THREE.MeshStandardMaterial({ color: C.junction, roughness: 0.7 })
        );
        mesh.position.set(x, 0.08, z);
      }
      mesh.castShadow = true;
      const hospital = graph.hospitals.find((item) => item.node_id === n.id);
      const entityType = n.kind === "hospital" ? "hospital" : n.kind === "substation" ? "substation" : n.kind;
      const entityId = hospital?.id ?? graph.substations.find((item) => item.node_id === n.id)?.id ?? n.id;
      makePickable(mesh, entityType, entityId, n.name || entityId);
      addCity(scene, mesh);
      handles.current.nodeMeshes.set(n.id, mesh);

      const sig = graph.signals.find((s) => s.node_id === n.id);
      if (sig) {
        const pole = new THREE.Mesh(
          new THREE.CylinderGeometry(0.025, 0.025, 0.5, 6),
          new THREE.MeshStandardMaterial({ color: 0x64748b, roughness: 0.8 })
        );
        pole.position.set(x, 0.3, z);
        addCity(scene, pole);
        const lamp = new THREE.Mesh(
          new THREE.SphereGeometry(0.105, 10, 8),
          new THREE.MeshStandardMaterial({ color: C.sigOn, emissive: C.sigOn, emissiveIntensity: 0.9 })
        );
        lamp.position.set(x, 0.57, z);
        addCity(scene, lamp);
        handles.current.signalMeshes.set(sig.id, lamp);
      }
    }

    const depot = graph.nodes.find((n) => n.kind === "depot");
    if (depot) {
      const [x, z] = toWorld(depot.x, depot.y);
      const amb = new THREE.Mesh(
        new THREE.BoxGeometry(0.38, 0.22, 0.58),
        new THREE.MeshStandardMaterial({ color: C.ambulance, emissive: 0x4a4208, roughness: 0.4 })
      );
      amb.position.set(x + 0.42, 0.13, z);
      amb.castShadow = true;
      addCity(scene, amb);
      const stripe = new THREE.Mesh(
        new THREE.BoxGeometry(0.39, 0.045, 0.03),
        new THREE.MeshStandardMaterial({ color: 0xef4444, emissive: 0x450a0a, emissiveIntensity: 0.25 })
      );
      stripe.position.set(x + 0.42, 0.16, z - 0.3);
      addCity(scene, stripe);
      handles.current.ambulance = amb;
    }

    const xs = graph.nodes.map((node) => toWorld(node.x, node.y)[0]);
    const zs = graph.nodes.map((node) => toWorld(node.x, node.y)[1]);
    const minX = Math.min(...xs, -2);
    const maxX = Math.max(...xs, 2);
    const minZ = Math.min(...zs, -2);
    const maxZ = Math.max(...zs, 2);
    const centerX = (minX + maxX) / 2;
    const centerZ = (minZ + maxZ) / 2;
    const span = Math.max(maxX - minX, maxZ - minZ, 4);
    controls.target.set(centerX, 0, centerZ);
    camera.position.set(centerX + span * 1.2, Math.max(5.5, span * 1.45), centerZ + span * 1.2);
    controls.minDistance = Math.max(3.5, span * 0.55);
    controls.maxDistance = Math.max(18, span * 5);
    controls.update();
  }, [graph, layers.emergency, layers.power, layers.traffic]);

  // ---------- repaint on state / cascade / view-mode change ----------
  useEffect(() => {
    const h = handles.current;
    if (!graph || !snapshot) return;

    const darkNodes = new Set<string>();
    for (const s of graph.signals) {
      const ok = snapshot.signals_ok[s.id] !== false;
      if (!ok) darkNodes.add(s.node_id);
    }
    const affected = new Set(cascade?.affected ?? []);
    const route = routeResult?.route as { edges?: string[] } | undefined;
    const routeEdges = new Set(layers.emergency ? route?.edges ?? [] : []);
    const selected = new Set(selectedIds);

    for (const e of graph.edges) {
      const mesh = h.edgeMeshes.get(e.id);
      if (!mesh) continue;
      const mat = mesh.material as THREE.MeshStandardMaterial;
      const flooded = e.id in snapshot.flooded_edges;
      const closed = snapshot.closed_edges?.[e.id] === true;
      const factor = snapshot.edge_factor?.[e.id] ?? 1;
      const free = h.edgeBase.get(e.id) ?? 1;
      const travel = snapshot.edge_travel_s[e.id] ?? free;
      const darkEnd = darkNodes.has(e.src) || darkNodes.has(e.dst);

      let color = e.kind === "underpass" ? C.underpass : C.road;
      if (viewMode === "whatif" && factor < 1) color = C.rerouted;
      else if (travel > free * 1.4 && !flooded && !closed) color = C.congested;
       if (closed) color = C.closed;
       if (flooded) color = C.flooded;
       if (routeEdges.has(e.id) && !flooded && !closed) color = C.ambulance;
       mat.color.setHex(color);
       const selectedEdge = selected.has(mesh.userData.entityId) || selectedId === mesh.userData.entityId;
       mat.emissive.setHex(routeEdges.has(e.id) ? 0x8a5a00 : selectedEdge ? 0x075985 : flooded ? 0x0a2a66 : darkEnd ? 0x1a0508 : 0x000000);
       mesh.position.y = flooded ? 0.075 : 0.06;

       const water = h.floodMeshes.get(e.id);
       if (water) water.visible = flooded;
       const congestion = h.congestionMeshes.get(e.id);
       if (congestion) congestion.visible = layers.traffic && travel > free * 1.4 && !flooded && !closed;
    }

    for (const n of graph.nodes) {
      const mesh = h.nodeMeshes.get(n.id);
      if (!mesh) continue;
      const mat = mesh.material as THREE.MeshStandardMaterial;
      const isDark = darkNodes.has(n.id);
      if (n.kind === "junction") {
        mat.color.setHex(isDark ? C.dark : C.junction);
        mat.emissive.setHex(affected.has(n.id) ? 0x4d3c06 : isDark ? 0x2a0508 : 0x000000);
        const s = (affected.has(n.id) ? 1.35 : 1) * (selected.has(mesh.userData.entityId) || selectedId === mesh.userData.entityId ? 1.3 : 1);
        mesh.scale.set(s, 1, s);
      } else if (n.kind === "hospital") {
        mat.emissive.setHex(affected.has(n.id) ? 0x4d3c06 : 0x0a3d1e);
      } else if (n.kind === "substation") {
        const sub = graph.substations.find((item) => item.node_id === n.id);
        const offline = sub && sub.feeders.length > 0 && sub.feeders.every((fid) => !snapshot.powered[fid]);
        mat.color.setHex(offline ? 0xef4444 : C.substation);
      }
    }

    for (const s of graph.signals) {
      const lamp = h.signalMeshes.get(s.id);
      if (!lamp) continue;
      const ok = snapshot.signals_ok[s.id] !== false;
      const mat = lamp.material as THREE.MeshStandardMaterial;
      mat.color.setHex(ok ? C.sigOn : C.sigOff);
      mat.emissive.setHex(ok ? C.sigOn : C.sigOff);
    }

    const dispatched = snapshot.ambulances?.["A1"]?.status === "dispatched";
    if (h.ambulance) {
      const mat = h.ambulance.material as THREE.MeshStandardMaterial;
      mat.emissive.setHex(dispatched ? 0xffb302 : 0x4a4208);
    }
  }, [graph, snapshot, cascade, viewMode, selectedId, selectedIds, routeResult, layers.traffic, layers.power, layers.emergency]);

  const outageKey = JSON.stringify(outageNodeIds);
  const routeNodes = (routeResult?.route as { nodes?: string[] } | undefined)?.nodes ?? [];
  const routeKey = JSON.stringify(routeNodes);
  useEffect(() => {
    const scene = (hostRef.current as any)?.__chrono?.scene as THREE.Scene | undefined;
    if (!scene || !graph) return;
    const overlay = new THREE.Group();
    scene.add(overlay);
    const nodes = new Map(graph.nodes.map((node) => [node.id, node]));
    if (layers.power) {
      for (const id of JSON.parse(outageKey) as string[]) {
        const node = nodes.get(id);
        if (!node) continue;
        const ring = new THREE.Mesh(new THREE.RingGeometry(0.4, 0.65, 32), new THREE.MeshBasicMaterial({
          color: 0xff3344, side: THREE.DoubleSide, transparent: true, opacity: 0.7, depthWrite: false,
        }));
        ring.rotation.x = -Math.PI / 2;
        ring.position.set(node.x, 0.2, -node.y);
        overlay.add(ring);
      }
    }
    if (layers.emergency) {
      const path = JSON.parse(routeKey) as string[];
      for (let i = 1; i < path.length; i++) {
        const a = nodes.get(path[i - 1]);
        const b = nodes.get(path[i]);
        if (!a || !b) continue;
        const dx = b.x - a.x, dz = a.y - b.y;
        const strip = new THREE.Mesh(new THREE.BoxGeometry(Math.hypot(dx, dz), 0.04, 0.09),
          new THREE.MeshBasicMaterial({ color: C.ambulance }));
        strip.position.set((a.x + b.x) / 2, 0.28, -(a.y + b.y) / 2);
        strip.rotation.y = -Math.atan2(dz, dx);
        overlay.add(strip);
      }
    }
    return () => {
      scene.remove(overlay);
      overlay.traverse((object) => {
        if (object instanceof THREE.Mesh) {
          object.geometry.dispose();
          (object.material as THREE.Material).dispose();
        }
      });
    };
  }, [graph, outageKey, routeKey, layers.power, layers.emergency]);

  return (
    <div className="twin-host" ref={hostRef}>
      <div className="map-legend">Yellow: emergency route · Blue: flood · Purple: closed · Red rings: power outage</div>
      {graph?.source === "osm" && (
        <div className="city-attribution">
          {graph.name ?? "Imported city"} · {graph.attribution ?? "© OpenStreetMap contributors · ODbL"}
        </div>
      )}
    </div>
  );
}
