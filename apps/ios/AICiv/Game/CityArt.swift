import SceneKit
import UIKit
import simd

/// The home city's look (V6.53–V6.67): physically based materials, organic islands with layered colour, trees and
/// rocks, glass-and-metal towers with lit windows, paved roads with lamps, hover cars, 3D agents built from their looks,
/// the plaza monument, water, light motes and drones. CityScene (CityRender.swift) places and animates them.
@MainActor
enum CityArt {
    typealias V = SIMD3<Float>

    // MARK: materials

    /// A physically based surface: rock, soil, paint, metal.
    static func pbr(_ c: UInt32, rough: CGFloat = 0.75, metal: CGFloat = 0) -> SCNMaterial {
        let m = SCNMaterial()
        m.lightingModel = .physicallyBased
        m.diffuse.contents = UIColor(hex: c)
        m.roughness.contents = NSNumber(value: Double(rough))
        m.metalness.contents = NSNumber(value: Double(metal))
        return m
    }

    /// Tinted glass that reflects the sky.
    static func glass(_ tint: UInt32, alpha: CGFloat = 0.35, glow: CGFloat = 0) -> SCNMaterial {
        let m = SCNMaterial()
        m.lightingModel = .physicallyBased
        let c = UIColor(hex: tint)
        m.diffuse.contents = c
        m.metalness.contents = NSNumber(value: 0.9)
        m.roughness.contents = NSNumber(value: 0.06)
        if glow > 0 { m.emission.contents = c.withAlphaComponent(glow) }
        m.transparency = alpha
        m.transparencyMode = .dualLayer
        m.blendMode = .alpha
        m.isDoubleSided = true
        m.writesToDepthBuffer = false
        return m
    }

    /// A surface coloured per vertex (islands and rock), lit physically.
    static func vertexColored(rough: CGFloat = 0.9) -> SCNMaterial {
        let m = SCNMaterial()
        m.lightingModel = .physicallyBased
        m.diffuse.contents = UIColor.white
        m.roughness.contents = NSNumber(value: Double(rough))
        m.metalness.contents = NSNumber(value: 0)
        return m
    }

    /// Additive light (trails, light pools, motes): never darkens what's behind it.
    static func light(_ c: UInt32, image: UIImage? = nil, alpha: CGFloat = 1) -> SCNMaterial {
        let m = SCNMaterial()
        m.lightingModel = .constant
        let col = UIColor(hex: c)
        m.diffuse.contents = image ?? col
        m.multiply.contents = image == nil ? UIColor.white : col
        m.emission.contents = image ?? col
        m.blendMode = .add
        m.writesToDepthBuffer = false
        m.isDoubleSided = true
        m.transparency = alpha
        return m
    }

    private static var windowCache: [UInt32: UIImage] = [:]

    /// A façade: dark glass with a scatter of lit windows (warm, cool and the district's colour) and floor lines.
    static func windows(_ c: UInt32) -> UIImage {
        if let img = windowCache[c] { return img }
        var rng = WorldMap.Rng("windows\(c)")
        let accent = UIColor(hex: c)
        let img = UIGraphicsImageRenderer(size: CGSize(width: 64, height: 128), format: .pixel).image { ctx in
            UIColor(hex: 0x0B1120).setFill()
            ctx.fill(CGRect(x: 0, y: 0, width: 64, height: 128))
            for row in 0..<16 {
                UIColor(hex: 0x1A2236).setFill()
                ctx.fill(CGRect(x: 0, y: row * 8, width: 64, height: 1))  // floor lines
                for col in 0..<8 {
                    let v = rng.next()
                    let color: UIColor
                    if v > 0.78 { color = UIColor(hex: 0xFFD9A0) }
                    else if v > 0.66 { color = UIColor(hex: 0xA8E4FF) }
                    else if v > 0.6 { color = accent }
                    else { color = UIColor(hex: 0x141C30) }
                    color.setFill()
                    ctx.fill(CGRect(x: col * 8 + 1, y: row * 8 + 2, width: 6, height: 5))
                }
            }
        }
        windowCache[c] = img
        return img
    }

    /// Glass-and-metal façade material, repeated `rx` × `ry` times across a face.
    static func facade(_ c: UInt32, rx: Float, ry: Float) -> SCNMaterial {
        let m = SCNMaterial()
        m.lightingModel = .physicallyBased
        let img = windows(c)
        m.diffuse.contents = img
        m.emission.contents = img
        m.emission.intensity = 1.4
        m.metalness.contents = NSNumber(value: 0.65)
        m.roughness.contents = NSNumber(value: 0.22)
        for p in [m.diffuse, m.emission] {
            p.wrapS = .repeat
            p.wrapT = .repeat
            p.contentsTransform = SCNMatrix4MakeScale(max(1, rx), max(1, ry), 1)
            p.mipFilter = .linear
        }
        return m
    }

    static let dot: UIImage = radial(size: 64, inner: UIColor.white, outer: UIColor.white.withAlphaComponent(0))
    static let shadowBlob: UIImage = radial(size: 64, inner: UIColor.black.withAlphaComponent(0.55), outer: UIColor.black.withAlphaComponent(0))

    static func radial(size: Int, inner: UIColor, outer: UIColor) -> UIImage {
        UIGraphicsImageRenderer(size: CGSize(width: size, height: size)).image { ctx in
            let cs = CGColorSpaceCreateDeviceRGB()
            guard let g = CGGradient(colorsSpace: cs, colors: [inner.cgColor, outer.cgColor] as CFArray, locations: [0, 1]) else { return }
            let c = CGPoint(x: size / 2, y: size / 2)
            ctx.cgContext.drawRadialGradient(g, startCenter: c, startRadius: 0, endCenter: c, endRadius: CGFloat(size) / 2, options: [])
        }
    }

    /// A soft fade from opaque to clear along its length (car light trails).
    static let fade: UIImage = UIGraphicsImageRenderer(size: CGSize(width: 8, height: 64)).image { ctx in
        let cs = CGColorSpaceCreateDeviceRGB()
        guard let g = CGGradient(colorsSpace: cs, colors: [UIColor.white.cgColor, UIColor.white.withAlphaComponent(0).cgColor] as CFArray,
                                 locations: [0, 1]) else { return }
        ctx.cgContext.drawLinearGradient(g, start: CGPoint(x: 4, y: 0), end: CGPoint(x: 4, y: 64), options: [])
    }

    // MARK: geometry helpers

    struct Tri { var a: V; var b: V; var c: V; var color: SIMD3<Float> }

    /// Flat-shaded triangles with a colour per face (low-poly, but coloured like the ground it is).
    static func mesh(_ tris: [Tri]) -> SCNGeometry {
        var v: [SCNVector3] = [], n: [SCNVector3] = [], col: [SIMD4<Float>] = []
        v.reserveCapacity(tris.count * 3)
        for t in tris {
            var nn = simd_cross(t.b - t.a, t.c - t.a)
            nn = simd_length(nn) > 0 ? simd_normalize(nn) : V(0, 1, 0)
            for p in [t.a, t.b, t.c] {
                v.append(SCNVector3(p))
                n.append(SCNVector3(nn))
                col.append(SIMD4<Float>(t.color.x, t.color.y, t.color.z, 1))
            }
        }
        let colorData = col.withUnsafeBufferPointer { Data(buffer: $0) }
        let colors = SCNGeometrySource(data: colorData, semantic: .color, vectorCount: col.count, usesFloatComponents: true,
                                       componentsPerVector: 4, bytesPerComponent: MemoryLayout<Float>.size, dataOffset: 0,
                                       dataStride: MemoryLayout<SIMD4<Float>>.stride)
        let idx = (0..<Int32(v.count)).map { $0 }
        return SCNGeometry(sources: [SCNGeometrySource(vertices: v), SCNGeometrySource(normals: n), colors],
                           elements: [SCNGeometryElement(indices: idx, primitiveType: .triangles)])
    }

    static func rgb(_ c: UInt32) -> SIMD3<Float> {
        SIMD3<Float>(Float((c >> 16) & 0xFF), Float((c >> 8) & 0xFF), Float(c & 0xFF)) / 255
    }

    /// Repeatable noise in -1…1 from a position and a seed.
    static func noise(_ x: Float, _ y: Float, _ seed: Float) -> Float {
        let s = sin(x * 12.9898 + y * 78.233 + seed * 37.719) * 43758.5453
        return (s - floor(s)) * 2 - 1
    }

    // MARK: V6.57 islands

    /// A floating island: a domed meadow on rock that narrows to a point, coloured in layers (grass, soil, stone,
    /// shadowed base), with irregular edges. Top at y = 0, tip at y = -depth.
    static func island(radius r: Float, depth: Float, seed: Float) -> SCNNode {
        let radial = 18, rows = 6
        var ring: [[V]] = []
        for iy in 0...rows {
            let t = Float(iy) / Float(rows)
            let y = -0.35 - depth * pow(t, 1.15)
            var row: [V] = []
            for ix in 0..<radial {
                let a = Float(ix) / Float(radial) * 2 * .pi
                let wobble = 1 + noise(Float(ix), Float(iy), seed) * (iy == 0 ? 0.04 : 0.16)
                let rr = r * pow(1 - t, 0.75) * wobble + (iy == rows ? 0 : 0.0)
                let drift = V(noise(Float(iy), 3, seed), 0, noise(Float(iy), 7, seed)) * (t * r * 0.12)
                row.append(V(sin(a) * rr, y, cos(a) * rr) + drift)
            }
            ring.append(row)
        }
        let grass = rgb(0x3F8F58), soil = rgb(0x6B4E3A), stone = rgb(0x5A5170), deep = rgb(0x2B2540)
        func shade(_ t: Float, _ k: Float) -> SIMD3<Float> {
            let base: SIMD3<Float>
            if t < 0.12 { base = soil } else if t < 0.55 { base = simd_mix(stone, soil, SIMD3<Float>(repeating: max(0, 0.4 - t))) }
            else { base = simd_mix(stone, deep, SIMD3<Float>(repeating: min(1, (t - 0.55) * 2.2))) }
            return base * (0.86 + 0.14 * k)
        }
        var tris: [Tri] = []
        let tip = ring[rows].reduce(V(0, 0, 0), +) / Float(radial) - V(0, depth * 0.08, 0)
        for iy in 0..<rows {
            for ix in 0..<radial {
                let j = (ix + 1) % radial
                let a = ring[iy][ix], b = ring[iy + 1][ix], c = ring[iy + 1][j], d = ring[iy][j]
                let t = (Float(iy) + 0.5) / Float(rows)
                let k = noise(Float(ix), Float(iy) + 0.5, seed)
                if iy == rows - 1 {
                    tris.append(Tri(a: a, b: tip, c: d, color: shade(t, k)))
                } else {
                    tris.append(Tri(a: a, b: b, c: d, color: shade(t, k)))
                    tris.append(Tri(a: b, b: c, c: d, color: shade(t, k * 0.8)))
                }
            }
        }
        // the meadow: a gentle dome over the rim, two rings of colour variation
        let top = ring[0]
        let mid = top.map { V($0.x * 0.55, 0.18, $0.z * 0.55) }
        let peak = V(0, 0.32, 0)
        for ix in 0..<radial {
            let j = (ix + 1) % radial
            let k = noise(Float(ix), 11, seed)
            let edge = simd_mix(grass, rgb(0x55A35E), SIMD3<Float>(repeating: 0.5 + 0.5 * k))
            tris.append(Tri(a: V(top[ix].x, 0.02, top[ix].z), b: mid[ix], c: V(top[j].x, 0.02, top[j].z), color: edge * 0.95))
            tris.append(Tri(a: mid[ix], b: mid[j], c: V(top[j].x, 0.02, top[j].z), color: edge))
            tris.append(Tri(a: mid[ix], b: peak, c: mid[j], color: simd_mix(grass, rgb(0x6DBA6A), SIMD3<Float>(repeating: 0.4 + 0.3 * k))))
        }
        let geo = mesh(tris)
        geo.firstMaterial = vertexColored()
        let node = SCNNode(geometry: geo)
        node.castsShadow = true
        return node
    }

    // MARK: V6.58 nature

    /// A tree: a layered pine, a round broadleaf, or (now and then) a softly glowing futuristic tree.
    static func tree(_ rng: inout WorldMap.Rng, scale s: Float) -> SCNNode {
        let n = SCNNode()
        let kind = rng.next()
        let trunk = SCNNode(geometry: SCNCylinder(radius: CGFloat(0.16 * s), height: CGFloat(1.4 * s)))
        trunk.geometry?.firstMaterial = pbr(0x5A3B2A, rough: 0.9)
        trunk.position.y = 0.7 * s
        n.addChildNode(trunk)
        let greens: [UInt32] = [0x2E7D4F, 0x3A8F55, 0x2F6E48, 0x4C9A5A, 0x356F3E]
        let g = greens[Int(rng.next() * Double(greens.count)) % greens.count]
        if kind < 0.45 {  // pine
            for (i, (r, h)) in [(Float(1.05), Float(1.6)), (0.8, 1.35), (0.55, 1.1)].enumerated() {
                let cone = SCNNode(geometry: SCNCone(topRadius: 0, bottomRadius: CGFloat(r * s), height: CGFloat(h * s)))
                cone.geometry?.firstMaterial = pbr(Self.shift(g, Float(i) * 0.06), rough: 0.85)
                (cone.geometry as? SCNCone)?.radialSegmentCount = 9
                cone.position.y = (1.5 + Float(i) * 0.75) * s
                n.addChildNode(cone)
            }
        } else if kind < 0.9 {  // broadleaf: a few overlapping blobs
            let blobs = 2 + Int(rng.next() * 2)
            for i in 0..<blobs {
                let r = Float(0.75 + rng.next() * 0.35) * s
                let sp = SCNSphere(radius: CGFloat(r))
                sp.segmentCount = 10
                sp.firstMaterial = pbr(Self.shift(g, Float(i) * 0.05), rough: 0.8)
                let b = SCNNode(geometry: sp)
                b.position = SCNVector3(Float(rng.next() - 0.5) * 0.7 * s, (2.0 + Float(i) * 0.35) * s, Float(rng.next() - 0.5) * 0.7 * s)
                b.scale = SCNVector3(1, 0.85, 1)
                n.addChildNode(b)
            }
        } else {  // a glow tree: teal or pink crown that lights up at dusk
            let col: UInt32 = rng.next() > 0.5 ? 0x5EEAD4 : 0xFF7AB8
            let sp = SCNSphere(radius: CGFloat(0.95 * s))
            sp.segmentCount = 12
            let m = pbr(col, rough: 0.4)
            m.emission.contents = UIColor(hex: col)
            m.emission.intensity = 0.6
            sp.firstMaterial = m
            let b = SCNNode(geometry: sp)
            b.position.y = 2.2 * s
            b.scale = SCNVector3(1, 1.15, 1)
            n.addChildNode(b)
        }
        n.eulerAngles.y = Float(rng.next()) * 6.28
        return n
    }

    static func bush(_ rng: inout WorldMap.Rng, scale s: Float) -> SCNNode {
        let sp = SCNSphere(radius: CGFloat(0.55 * s))
        sp.segmentCount = 8
        sp.firstMaterial = pbr(Self.shift(0x3F8F4F, Float(rng.next()) * 0.12), rough: 0.85)
        let n = SCNNode(geometry: sp)
        n.position.y = 0.3 * s
        n.scale = SCNVector3(1.2, 0.7, 1)
        return n
    }

    static func boulder(_ rng: inout WorldMap.Rng, scale s: Float) -> SCNNode {
        let sp = SCNSphere(radius: CGFloat(0.6 * s))
        sp.segmentCount = 6
        sp.firstMaterial = pbr(0x5C566E, rough: 0.95)
        let n = SCNNode(geometry: sp)
        n.scale = SCNVector3(1.3, 0.75, 1)
        n.position.y = 0.2 * s
        n.eulerAngles = SCNVector3(Float(rng.next()), Float(rng.next()) * 6.28, 0)
        return n
    }

    /// Trees, bushes and rocks scattered over an island, kept off the deck (half-size `clear`) and off the road
    /// leaving in direction `road` (radians, or nil). Returned flattened, so it draws as one object.
    static func flora(radius r: Float, clear: Float, road: Float?, seed: String, density: Float = 1) -> SCNNode {
        var rng = WorldMap.Rng("flora" + seed)
        let group = SCNNode()
        let count = Int(r * 1.4 * density)
        var placed = 0, tries = 0
        while placed < count && tries < count * 8 {
            tries += 1
            let a = Float(rng.next()) * 2 * .pi
            let d = r * Float(0.35 + rng.next() * 0.58)
            let x = sin(a) * d, z = cos(a) * d
            if clear > 0 && abs(x) < clear + 0.9 && abs(z) < clear + 0.9 { continue }
            if let road {
                var diff = abs(a - road).truncatingRemainder(dividingBy: 2 * .pi)
                if diff > .pi { diff = 2 * .pi - diff }
                if diff < 0.32 { continue }
            }
            let kind = rng.next()
            let s = Float(0.7 + rng.next() * 0.6)
            let item: SCNNode
            if kind < 0.55 { item = tree(&rng, scale: s) } else if kind < 0.85 { item = bush(&rng, scale: s) } else { item = boulder(&rng, scale: s) }
            item.position = SCNVector3(x, item.position.y, z)
            group.addChildNode(item)
            placed += 1
        }
        let flat = group.flattenedClone()
        flat.castsShadow = true
        return flat
    }

    static func shift(_ c: UInt32, _ amount: Float) -> UInt32 {
        let v = rgb(c) * (1 + amount)
        let r = UInt32(min(255, max(0, v.x * 255))), g = UInt32(min(255, max(0, v.y * 255))), b = UInt32(min(255, max(0, v.z * 255)))
        return (r << 16) | (g << 8) | b
    }

    // MARK: V6.59 buildings

    /// A tower: glass-and-metal body with lit windows, rounded corners, softer neon trim, a roof cap, and on tall
    /// ones an antenna with a blinking light (named "blink").
    static func tower(_ t: WorldMap.Tower, color c: UInt32, warm: Bool) -> SCNNode {
        let n = SCNNode()
        let sx = Float(t.size.x), sy = Float(t.size.y), sz = Float(t.size.z)
        let body: SCNGeometry
        switch t.kind {
        case .box:
            body = SCNBox(width: CGFloat(sx), height: CGFloat(sy), length: CGFloat(sz), chamferRadius: CGFloat(min(0.35, min(sx, sz) * 0.08)))
            body.firstMaterial = facade(warm ? 0xF4D58D : c, rx: sx / 3, ry: sy / 3)
        case .cyl:
            let cy = SCNCylinder(radius: CGFloat(sx / 2), height: CGFloat(sy))
            cy.radialSegmentCount = 28
            body = cy
            body.firstMaterial = facade(c, rx: sx * 1.0, ry: sy / 3)
        case .cone:
            let co = SCNCone(topRadius: 0.2, bottomRadius: CGFloat(sx / 2), height: CGFloat(sy))
            co.radialSegmentCount = 24
            body = co
            body.firstMaterial = facade(c, rx: sx, ry: sy / 3)
        case .dome:
            let sp = SCNSphere(radius: CGFloat(sx))
            sp.segmentCount = 40
            body = sp
            body.firstMaterial = glass(c, alpha: 0.5, glow: 0.18)
        }
        let bn = SCNNode(geometry: body)
        bn.castsShadow = true
        if t.kind == .dome {  // only the top half shows above the deck
            bn.position.y = 0
        }
        n.addChildNode(bn)
        // neon trim: thin rings at the base and top (kept from the website's edges, quieter)
        if t.kind != .dome {
            for y in (t.kind == .cone ? [-sy / 2 + 0.15] : [-sy / 2 + 0.15, sy / 2 - 0.1]) {
                let w = sx / 2 + 0.06
                let shape: SCNGeometry
                if t.kind == .box {
                    shape = SCNBox(width: CGFloat(sx + 0.12), height: 0.1, length: CGFloat(sz + 0.12), chamferRadius: 0.05)
                } else {
                    shape = SCNTube(innerRadius: CGFloat(w - 0.08), outerRadius: CGFloat(w), height: 0.1)
                }
                let trim = SCNNode(geometry: shape)
                trim.geometry?.firstMaterial = CityScene.glow(c, alpha: 0.75)
                trim.position.y = y
                trim.castsShadow = false
                n.addChildNode(trim)
            }
        }
        if t.kind == .box && sy > 5 {  // roof cap and plant
            let cap = SCNNode(geometry: SCNBox(width: CGFloat(sx * 0.82), height: 0.45, length: CGFloat(sz * 0.82), chamferRadius: 0.12))
            cap.geometry?.firstMaterial = pbr(0x252B3A, rough: 0.5, metal: 0.6)
            cap.position.y = sy / 2 + 0.22
            n.addChildNode(cap)
        }
        if sy > 14 && t.kind != .dome {  // antenna with an aircraft light
            let mast = SCNNode(geometry: SCNCylinder(radius: 0.06, height: 3.2))
            mast.geometry?.firstMaterial = pbr(0x9AA3B8, rough: 0.3, metal: 0.9)
            mast.position.y = sy / 2 + 1.8
            n.addChildNode(mast)
            let bulb = SCNNode(geometry: SCNSphere(radius: 0.16))
            bulb.geometry?.firstMaterial = CityScene.glow(0xFF4D5E)
            bulb.position.y = sy / 2 + 3.45
            bulb.name = "blink"
            bulb.castsShadow = false
            n.addChildNode(bulb)
        }
        return n
    }

    // MARK: V6.60 roads

    /// A paved road along +z, `length` long: asphalt, a dashed centre line, glowing curbs and lamps either side.
    static func road(length L: Float, color c: UInt32) -> SCNNode {
        let n = SCNNode()
        let deck = SCNNode(geometry: SCNBox(width: 3.6, height: 0.3, length: CGFloat(L), chamferRadius: 0.06))
        deck.geometry?.firstMaterial = pbr(0x1B1F2A, rough: 0.85, metal: 0.05)
        n.addChildNode(deck)
        let dashes = Int(L / 1.6)
        for i in 0..<max(0, dashes) {
            let d = SCNNode(geometry: SCNBox(width: 0.1, height: 0.02, length: 0.7, chamferRadius: 0))
            d.geometry?.firstMaterial = CityScene.glow(0xE8EEFF, alpha: 0.55)
            d.position = SCNVector3(0, 0.16, -L / 2 + 0.8 + Float(i) * 1.6)
            d.castsShadow = false
            n.addChildNode(d)
        }
        for x in [-1.85, 1.85] as [Float] {
            let curb = SCNNode(geometry: SCNBox(width: 0.12, height: 0.12, length: CGFloat(L), chamferRadius: 0))
            curb.geometry?.firstMaterial = CityScene.glow(c, alpha: 0.8)
            curb.position = SCNVector3(x, 0.2, 0)
            curb.castsShadow = false
            n.addChildNode(curb)
        }
        var z = -L / 2 + 2
        var side: Float = 1
        while z < L / 2 - 1 {
            n.addChildNode(lamp(at: V(side * 2.25, 0.15, z), facing: -side))
            z += 7
            side = -side
        }
        let flat = n.flattenedClone()
        flat.castsShadow = true
        return flat
    }

    /// A slim street lamp leaning over the road, its head and a pool of light on the ground.
    static func lamp(at p: V, facing: Float) -> SCNNode {
        let n = SCNNode()
        n.simdPosition = p
        let pole = SCNNode(geometry: SCNCylinder(radius: 0.05, height: 2.8))
        pole.geometry?.firstMaterial = pbr(0x8C96AA, rough: 0.35, metal: 0.9)
        pole.position.y = 1.4
        n.addChildNode(pole)
        let arm = SCNNode(geometry: SCNBox(width: 0.7, height: 0.06, length: 0.06, chamferRadius: 0.02))
        arm.geometry?.firstMaterial = pole.geometry?.firstMaterial
        arm.position = SCNVector3(facing * 0.32, 2.78, 0)
        n.addChildNode(arm)
        let head = SCNNode(geometry: SCNCapsule(capRadius: 0.08, height: 0.4))
        head.geometry?.firstMaterial = CityScene.glow(0xFFE6B0)
        head.eulerAngles.z = .pi / 2
        head.position = SCNVector3(facing * 0.62, 2.72, 0)
        n.addChildNode(head)
        let pool = SCNNode(geometry: SCNPlane(width: 2.2, height: 2.2))
        pool.geometry?.firstMaterial = light(0xFFD9A0, image: dot, alpha: 0.35)
        pool.eulerAngles.x = -.pi / 2
        pool.position = SCNVector3(facing * 0.8, 0.18, 0)
        n.addChildNode(pool)
        return n
    }

    // MARK: V6.61 cars

    /// A hover car, nose along +z: a sleek body, a glass canopy, headlights, tail lights, underglow and a light trail.
    static func hoverCar(paint: UInt32, glow: UInt32) -> SCNNode {
        let n = SCNNode()
        let body = SCNNode(geometry: SCNCapsule(capRadius: 0.42, height: 2.3))
        body.geometry?.firstMaterial = pbr(paint, rough: 0.25, metal: 0.7)
        body.eulerAngles.x = .pi / 2
        body.scale = SCNVector3(1, 1, 0.55)
        n.addChildNode(body)
        let canopy = SCNNode(geometry: SCNSphere(radius: 0.42))
        canopy.geometry?.firstMaterial = glass(0x9FD8FF, alpha: 0.6, glow: 0.15)
        canopy.scale = SCNVector3(0.75, 0.55, 1.25)
        canopy.position = SCNVector3(0, 0.2, 0.15)
        n.addChildNode(canopy)
        for x in [-0.22, 0.22] as [Float] {
            let head = SCNNode(geometry: SCNSphere(radius: 0.07))
            head.geometry?.firstMaterial = CityScene.glow(0xFFF6DC)
            head.position = SCNVector3(x, 0, 1.12)
            n.addChildNode(head)
        }
        let tail = SCNNode(geometry: SCNBox(width: 0.55, height: 0.08, length: 0.05, chamferRadius: 0.02))
        tail.geometry?.firstMaterial = CityScene.glow(0xFF3D5A)
        tail.position = SCNVector3(0, 0.02, -1.14)
        n.addChildNode(tail)
        let under = SCNNode(geometry: SCNPlane(width: 1.1, height: 2.4))
        under.geometry?.firstMaterial = light(glow, image: dot, alpha: 0.6)
        under.eulerAngles.x = .pi / 2
        under.position.y = -0.3
        n.addChildNode(under)
        let trail = SCNNode(geometry: SCNPlane(width: 0.32, height: 3.4))
        trail.geometry?.firstMaterial = light(glow, image: fade, alpha: 0.55)
        trail.eulerAngles.x = -.pi / 2
        trail.position = SCNVector3(0, 0, -2.9)
        n.addChildNode(trail)
        n.castsShadow = false
        return n
    }

    // MARK: V6.62 agents

    /// A 3D agent built from its look: shoes, trousers, top with an accent stripe, arms, head, hair and a glowing
    /// visor. Limb pivots are named legL, legR, armL, armR; the upper body is "torso" (for the bob). Faces +z.
    static func figure(_ look: Agent.Look?, fallback: String, visor: UInt32) -> SCNNode {
        func hx(_ s: String?, _ d: UInt32) -> UInt32 { s.map { CityScene.hex($0) } ?? d }
        let skin = hx(look?.skin, 0xE8B48A), hair = hx(look?.hair.color, 0x2A2230)
        let top = hx(look?.top.color ?? fallback, 0x5B8CFF), accent = hx(look?.top.accent, 0xEAF2FF)
        let pants = hx(look?.bottom.color, 0x2A2E3E)
        let shoes = look.map { $0.shoes.hasPrefix("#") ? CityScene.hex($0.shoes) : 0x2A2230 } ?? 0x2A2230
        let rig = SCNNode()
        rig.name = "rig"
        func part(_ g: SCNGeometry, _ c: UInt32, rough: CGFloat = 0.6) -> SCNNode {
            g.firstMaterial = pbr(c, rough: rough)
            let p = SCNNode(geometry: g)
            p.castsShadow = true
            return p
        }
        for (name, x) in [("legL", Float(-0.17)), ("legR", 0.17)] {
            let pivot = SCNNode()
            pivot.name = name
            pivot.position = SCNVector3(x, 1.0, 0)
            let leg = part(SCNCapsule(capRadius: 0.15, height: 1.0), pants)
            leg.position.y = -0.5
            pivot.addChildNode(leg)
            let shoe = part(SCNBox(width: 0.26, height: 0.16, length: 0.42, chamferRadius: 0.07), shoes, rough: 0.4)
            shoe.position = SCNVector3(0, -0.95, 0.06)
            pivot.addChildNode(shoe)
            rig.addChildNode(pivot)
        }
        let torso = SCNNode()
        torso.name = "torso"
        rig.addChildNode(torso)
        let chest = part(SCNCapsule(capRadius: 0.33, height: 1.05), top, rough: 0.7)
        chest.position.y = 1.5
        torso.addChildNode(chest)
        let stripe = SCNNode(geometry: SCNTube(innerRadius: 0.32, outerRadius: 0.345, height: 0.09))
        stripe.geometry?.firstMaterial = pbr(accent, rough: 0.4)
        stripe.position.y = 1.52
        torso.addChildNode(stripe)
        for (name, x) in [("armL", Float(-0.44)), ("armR", 0.44)] {
            let pivot = SCNNode()
            pivot.name = name
            pivot.position = SCNVector3(x, 1.88, 0)
            let arm = part(SCNCapsule(capRadius: 0.1, height: 0.85), top, rough: 0.7)
            arm.position.y = -0.38
            pivot.addChildNode(arm)
            let hand = part(SCNSphere(radius: 0.1), skin)
            hand.position.y = -0.82
            pivot.addChildNode(hand)
            torso.addChildNode(pivot)
        }
        let head = part(SCNSphere(radius: 0.36), skin, rough: 0.55)
        (head.geometry as? SCNSphere)?.segmentCount = 20
        head.position.y = 2.42
        torso.addChildNode(head)
        if look?.hair.style != "bald" {
            let h = part(SCNSphere(radius: 0.385), hair, rough: 0.8)
            (h.geometry as? SCNSphere)?.segmentCount = 16
            h.scale = SCNVector3(1, 0.72, 1.02)
            h.position = SCNVector3(0, 2.56, -0.04)
            torso.addChildNode(h)
        }
        let v = SCNNode(geometry: SCNBox(width: 0.5, height: 0.1, length: 0.12, chamferRadius: 0.05))
        v.geometry?.firstMaterial = CityScene.glow(visor, alpha: 0.95)
        v.position = SCNVector3(0, 2.45, 0.3)
        v.castsShadow = false
        torso.addChildNode(v)
        let shadow = SCNNode(geometry: SCNPlane(width: 1.5, height: 1.5))
        let sm = SCNMaterial()
        sm.lightingModel = .constant
        sm.diffuse.contents = shadowBlob
        sm.writesToDepthBuffer = false
        shadow.geometry?.firstMaterial = sm
        shadow.eulerAngles.x = -.pi / 2
        shadow.position.y = 0.04
        shadow.castsShadow = false
        let out = SCNNode()
        out.addChildNode(shadow)
        out.addChildNode(rig)
        return out
    }

    // MARK: V6.63 plaza

    /// The plaza's centrepiece: a stone base, a reflecting pool, and a slowly turning holographic globe ("globe").
    static func monument() -> SCNNode {
        let n = SCNNode()
        let pool = SCNNode(geometry: SCNCylinder(radius: 5.2, height: 0.06))
        let water = pbr(0x0B1A33, rough: 0.04, metal: 1)
        water.emission.contents = UIColor(hex: 0x0A2440)
        pool.geometry?.firstMaterial = water
        (pool.geometry as? SCNCylinder)?.radialSegmentCount = 48
        pool.position.y = 0.06
        n.addChildNode(pool)
        let rim = SCNNode(geometry: SCNTube(innerRadius: 5.2, outerRadius: 5.6, height: 0.35))
        rim.geometry?.firstMaterial = pbr(0x8E8AA6, rough: 0.6)
        (rim.geometry as? SCNTube)?.radialSegmentCount = 48
        rim.position.y = 0.17
        n.addChildNode(rim)
        let base = SCNNode(geometry: SCNCylinder(radius: 1.1, height: 2.4))
        base.geometry?.firstMaterial = pbr(0x6E6A86, rough: 0.5, metal: 0.3)
        base.position.y = 1.2
        n.addChildNode(base)
        let globe = SCNNode()
        globe.name = "globe"
        globe.position.y = 5
        let wire = SCNSphere(radius: 2.2)
        wire.segmentCount = 18
        let wm = CityScene.glow(0x5FE3FF, alpha: 0.55)
        wm.fillMode = .lines
        wire.firstMaterial = wm
        globe.addChildNode(SCNNode(geometry: wire))
        let core = SCNNode(geometry: SCNSphere(radius: 0.9))
        core.geometry?.firstMaterial = glass(0x9FEFFF, alpha: 0.7, glow: 0.8)
        globe.addChildNode(core)
        for (i, tilt) in [Float(0.4), -0.5, 1.2].enumerated() {
            let ring = SCNNode(geometry: SCNTorus(ringRadius: CGFloat(2.6 + Float(i) * 0.25), pipeRadius: 0.03))
            ring.geometry?.firstMaterial = CityScene.glow(i == 1 ? 0xC9A3FF : 0x5FE3FF, alpha: 0.8)
            ring.eulerAngles = SCNVector3(tilt, 0, tilt * 0.5)
            globe.addChildNode(ring)
        }
        globe.castsShadow = false
        n.addChildNode(globe)
        return n
    }

    // MARK: V6.64 water and V6.66 life

    static func mist(width: Float) -> SCNParticleSystem {
        let p = SCNParticleSystem()
        p.birthRate = 14
        p.particleLifeSpan = 2.2
        p.particleLifeSpanVariation = 0.6
        p.particleSize = CGFloat(width * 0.6)
        p.particleSizeVariation = 0.3
        p.particleImage = dot
        p.particleColor = UIColor(white: 1, alpha: 0.22)
        p.particleVelocity = 1.4
        p.particleVelocityVariation = 0.8
        p.spreadingAngle = 70
        p.emittingDirection = SCNVector3(0, 1, 0)
        p.blendMode = .additive
        p.isLightingEnabled = false
        p.emitterShape = SCNCylinder(radius: CGFloat(width * 0.6), height: 0.1)
        return p
    }

    /// Slow-drifting motes of light over the whole city.
    static func motes() -> SCNParticleSystem {
        let p = SCNParticleSystem()
        p.birthRate = 18
        p.particleLifeSpan = 9
        p.particleSize = 0.22
        p.particleSizeVariation = 0.12
        p.particleImage = dot
        p.particleColor = UIColor(red: 0.62, green: 0.92, blue: 1, alpha: 0.7)
        p.particleColorVariation = SCNVector4(0.15, 0.2, 0.1, 0.3)
        p.particleVelocity = 0.5
        p.particleVelocityVariation = 0.5
        p.spreadingAngle = 180
        p.blendMode = .additive
        p.isLightingEnabled = false
        p.emitterShape = SCNBox(width: 180, height: 40, length: 180, chamferRadius: 0)
        p.birthLocation = .volume
        let fade = CAKeyframeAnimation()
        fade.values = [0, 1, 1, 0]
        fade.keyTimes = [0, 0.2, 0.8, 1]
        p.propertyControllers = [.opacity: SCNParticlePropertyController(animation: fade)]
        return p
    }

    /// A small delivery drone: a body, four rotor discs and a blinking light ("blink").
    static func drone() -> SCNNode {
        let n = SCNNode()
        let body = SCNNode(geometry: SCNBox(width: 0.5, height: 0.18, length: 0.5, chamferRadius: 0.08))
        body.geometry?.firstMaterial = pbr(0xD9DEEA, rough: 0.3, metal: 0.6)
        n.addChildNode(body)
        for (x, z) in [(Float(-0.36), Float(-0.36)), (0.36, -0.36), (-0.36, 0.36), (0.36, 0.36)] {
            let r = SCNNode(geometry: SCNCylinder(radius: 0.2, height: 0.02))
            r.geometry?.firstMaterial = light(0x9FD8FF, image: dot, alpha: 0.6)
            r.position = SCNVector3(x, 0.1, z)
            n.addChildNode(r)
        }
        let b = SCNNode(geometry: SCNSphere(radius: 0.07))
        b.geometry?.firstMaterial = CityScene.glow(0x5BF2A5)
        b.position.y = -0.12
        b.name = "blink"
        n.addChildNode(b)
        n.castsShadow = false
        return n
    }

    /// A glass tube over a conveyor belt (`length` along +z).
    static func tube(length: Float) -> SCNNode {
        let cy = SCNCylinder(radius: 0.62, height: CGFloat(length))
        cy.radialSegmentCount = 16
        let m = glass(0x9FD8FF, alpha: 0.1, glow: 0.03)
        m.metalness.contents = NSNumber(value: 0.15)  // a faint pipe, not a mirror
        cy.firstMaterial = m
        let n = SCNNode(geometry: cy)
        n.eulerAngles.x = .pi / 2
        n.position.y = 0.35
        n.castsShadow = false
        return n
    }

    /// One layer of the cloud sea: soft, overlapping puffs, warm toward one side, fading out at the edges.
    static func cloudLayer(_ layer: Int) -> SCNMaterial {
        let size = 1024
        var r = WorldMap.Rng("cloudsea\(layer)")
        let img = UIGraphicsImageRenderer(size: CGSize(width: size, height: size)).image { ctx in
            let cg = ctx.cgContext
            let cs = CGColorSpaceCreateDeviceRGB()
            for _ in 0..<(layer == 0 ? 420 : 260) {
                let x = CGFloat(r.next()) * CGFloat(size), y = CGFloat(r.next()) * CGFloat(size)
                let dx = x / CGFloat(size) - 0.5, dy = y / CGFloat(size) - 0.5
                let edge = max(0, 1 - sqrt(dx * dx + dy * dy) * 2.1)   // thin out toward the rim
                if edge <= 0 { continue }
                let rad = CGFloat(18 + r.next() * 70)
                let warm = CGFloat(r.next()) * 0.5 + (1 - y / CGFloat(size)) * 0.5
                let col = UIColor(red: 0.62 + 0.33 * warm, green: 0.48 + 0.2 * warm, blue: 0.72 - 0.12 * warm, alpha: 0.32 * edge)
                guard let g = CGGradient(colorsSpace: cs, colors: [col.cgColor, col.withAlphaComponent(0).cgColor] as CFArray,
                                         locations: [0, 1]) else { continue }
                let c = CGPoint(x: x, y: y)
                cg.drawRadialGradient(g, startCenter: c, startRadius: 0, endCenter: c, endRadius: rad, options: [])
            }
        }
        let m = SCNMaterial()
        m.lightingModel = .constant
        m.diffuse.contents = img
        m.emission.contents = img
        m.emission.intensity = layer == 0 ? 0.55 : 0.75
        m.blendMode = .alpha
        m.transparencyMode = .aOne
        m.writesToDepthBuffer = false
        m.isDoubleSided = true
        return m
    }

    // MARK: V6.55 sky

    /// The dusk sky as a latitude/longitude image: deep navy overhead, violet, rose and gold at the horizon, a
    /// glowing low sun, soft cloud banks, and stars that fade toward the horizon. Also the scene's reflections.
    static func sky() -> UIImage {
        let w = 2048, h = 1024
        let horizon = CGFloat(h) / 2
        return UIGraphicsImageRenderer(size: CGSize(width: w, height: h), format: .pixel).image { ctx in
            let cg = ctx.cgContext
            let cs = CGColorSpaceCreateDeviceRGB()
            func c(_ hex: UInt32, _ a: CGFloat = 1) -> CGColor { UIColor(hex: hex).withAlphaComponent(a).cgColor }
            let colors = [c(0x070B22), c(0x121A44), c(0x2E1B55), c(0x6A2E6E), c(0xD9667A), c(0xF6A86B), c(0x3B2350), c(0x120E26)] as CFArray
            let locs: [CGFloat] = [0, 0.18, 0.33, 0.42, 0.475, 0.5, 0.53, 1]
            if let g = CGGradient(colorsSpace: cs, colors: colors, locations: locs) {
                cg.drawLinearGradient(g, start: .zero, end: CGPoint(x: 0, y: h), options: [])
            }
            // stars, thinning toward the horizon
            var r = WorldMap.Rng("stars")
            for _ in 0..<900 {
                let x = CGFloat(r.next()) * CGFloat(w), yy = CGFloat(pow(r.next(), 1.6)) * horizon * 0.82
                let a = CGFloat(0.25 + r.next() * 0.75) * (1 - yy / horizon)
                let s: CGFloat = r.next() > 0.93 ? 2 : 1
                cg.setFillColor(UIColor(white: 1, alpha: a).cgColor)
                cg.fill(CGRect(x: x, y: yy, width: s, height: s))
            }
            // the low sun, behind the city (seen past the far islands from the default view)
            for sunX in [CGFloat(w) * 0.75] {
                let sun = CGPoint(x: sunX, y: horizon - 18)
                if let g = CGGradient(colorsSpace: cs, colors: [c(0xFFF1C8), c(0xFFB46E, 0.85), c(0xFF7A6A, 0.25), c(0xFF7A6A, 0)] as CFArray,
                                      locations: [0, 0.06, 0.35, 1]) {
                    cg.drawRadialGradient(g, startCenter: sun, startRadius: 0, endCenter: sun, endRadius: 360, options: [])
                }
            }
            // soft cloud banks near the horizon, lit warm from below
            var cr = WorldMap.Rng("clouds")
            for _ in 0..<140 {
                let x = CGFloat(cr.next()) * CGFloat(w)
                let y = horizon - CGFloat(20 + cr.next() * 150)
                let rw = CGFloat(80 + cr.next() * 220), rh = CGFloat(10 + cr.next() * 26)
                let warm = 1 - (horizon - y) / 170
                let col = UIColor(red: 0.55 + 0.4 * warm, green: 0.35 + 0.25 * warm, blue: 0.55 + 0.05 * warm, alpha: 0.07 + 0.06 * warm)
                cg.setFillColor(col.cgColor)
                cg.fillEllipse(in: CGRect(x: x - rw / 2, y: y - rh / 2, width: rw, height: rh))
                cg.fillEllipse(in: CGRect(x: x - rw / 2 - CGFloat(w), y: y - rh / 2, width: rw, height: rh))  // wrap around
            }
        }
    }
}
