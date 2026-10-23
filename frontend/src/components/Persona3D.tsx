import { useEffect, useRef } from 'react'
import * as THREE from 'three'
import { GLTFLoader } from 'three/examples/jsm/loaders/GLTFLoader.js'
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js'
import { RoomEnvironment } from 'three/examples/jsm/environments/RoomEnvironment.js'

import css from './PersonaStage.module.css'

/**
 * One persona's 3D figure: transparent background, drag to turn it around
 * (arrow keys too), a slow idle spin that stops while you hold it. Loaded
 * lazily by PersonaStage, so three.js only downloads where a model exists.
 */
export default function Persona3D({ src, label, onFail }: { src: string; label: string; onFail: () => void }) {
  const host = useRef<HTMLDivElement>(null)
  const turntable = useRef<THREE.Group | null>(null)

  useEffect(() => {
    const el = host.current
    if (!el) return
    const reduceMotion = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches ?? false

    const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true })
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2))
    renderer.setClearColor(0x000000, 0)
    renderer.outputColorSpace = THREE.SRGBColorSpace
    renderer.toneMapping = THREE.ACESFilmicToneMapping
    renderer.toneMappingExposure = 1.15
    el.appendChild(renderer.domElement)

    const scene = new THREE.Scene()
    // The generated models use physically based materials: they need something
    // to reflect, or they render dark. A soft studio environment plus a key light.
    const pmrem = new THREE.PMREMGenerator(renderer)
    const studio = pmrem.fromScene(new RoomEnvironment(), 0.04).texture
    scene.environment = studio
    pmrem.dispose()
    const key = new THREE.DirectionalLight(0xffffff, 1.6)
    key.position.set(2, 4, 3)
    scene.add(key)
    const rim = new THREE.DirectionalLight(0xffd2b8, 0.9)
    rim.position.set(-3, 2, -2)
    scene.add(rim)

    const camera = new THREE.PerspectiveCamera(28, 1, 0.1, 100)
    const controls = new OrbitControls(camera, renderer.domElement)
    controls.enableZoom = false
    controls.enablePan = false
    controls.enableDamping = true
    // Keep the figure upright: turn around it freely, tilt only a little.
    controls.minPolarAngle = Math.PI / 2.6
    controls.maxPolarAngle = Math.PI / 1.85
    controls.autoRotate = !reduceMotion
    controls.autoRotateSpeed = 1.6

    // Idle spin pauses while held and resumes a few seconds after letting go.
    let resume = 0
    controls.addEventListener('start', () => {
      controls.autoRotate = false
      window.clearTimeout(resume)
    })
    controls.addEventListener('end', () => {
      if (!reduceMotion) resume = window.setTimeout(() => (controls.autoRotate = true), 4000)
    })

    // Keyboard turning rotates this group; dragging orbits the camera.
    const table = new THREE.Group()
    scene.add(table)
    turntable.current = table
    new GLTFLoader().load(
      src,
      (gltf) => {
        const model = gltf.scene
        // Normalise: 1.8 units tall, centred, feet on the floor, framed by the camera.
        const box = new THREE.Box3().setFromObject(model)
        const size = box.getSize(new THREE.Vector3())
        model.scale.setScalar(1.8 / (size.y || 1))
        const fitted = new THREE.Box3().setFromObject(model)
        const centre = fitted.getCenter(new THREE.Vector3())
        model.position.sub(new THREE.Vector3(centre.x, fitted.min.y, centre.z))
        table.add(model)
        controls.target.set(0, 0.9, 0)
        camera.position.set(0, 1.05, 4.1)
        controls.update()
        el.dataset.ready = 'true'
      },
      undefined,
      () => onFail(),
    )

    const resize = () => {
      const { width, height } = el.getBoundingClientRect()
      if (!width || !height) return
      renderer.setSize(width, height, false)
      camera.aspect = width / height
      camera.updateProjectionMatrix()
    }
    resize()
    const ro = new ResizeObserver(resize)
    ro.observe(el)

    // Only draw while on screen.
    let visible = true
    const io = new IntersectionObserver(([entry]) => (visible = entry.isIntersecting))
    io.observe(el)
    renderer.setAnimationLoop(() => {
      if (!visible) return
      controls.update()
      renderer.render(scene, camera)
    })

    return () => {
      window.clearTimeout(resume)
      turntable.current = null
      renderer.setAnimationLoop(null)
      ro.disconnect()
      io.disconnect()
      controls.dispose()
      scene.traverse((obj) => {
        const mesh = obj as THREE.Mesh
        mesh.geometry?.dispose()
        const materials = Array.isArray(mesh.material) ? mesh.material : mesh.material ? [mesh.material] : []
        materials.forEach((m) => {
          Object.values(m).forEach((v) => v instanceof THREE.Texture && v.dispose())
          m.dispose()
        })
      })
      studio.dispose()
      renderer.dispose()
      renderer.domElement.remove()
    }
  }, [src, onFail])

  return (
    <div
      ref={host}
      className={css.canvas}
      role="img"
      aria-label={label}
      tabIndex={0}
      onKeyDown={(e) => {
        if (e.key !== 'ArrowLeft' && e.key !== 'ArrowRight') return
        e.preventDefault()
        if (turntable.current) turntable.current.rotation.y += e.key === 'ArrowLeft' ? -0.35 : 0.35
      }}
    />
  )
}
