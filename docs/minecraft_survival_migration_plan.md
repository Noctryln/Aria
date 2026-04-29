# Aria Minecraft Survival Migration Plan (TUI → In-World Embodiment)

## Tujuan
Mentransformasi Aria dari antarmuka TUI menjadi agen embodied di Minecraft Java (localhost:25565, v1.21.11), dengan prioritas **responsif, cepat, akurat**, serta tetap kompatibel dengan pola tool-calling Aria saat ini.

## Hasil audit struktur kode saat ini
- Aria saat ini punya loop utama: LLM stream → deteksi tool tag → eksekusi tool sinkron di `ToolExecutorMixin`. Ini fondasi bagus untuk menambah tool `minecraft_*`. 
- Registrasi tool tag masih hardcoded regex (`TOOL_NAME_PATTERN`) sehingga penambahan tool Minecraft harus eksplisit di sana.
- UI Textual terikat kuat di `aria/ui/*` dan bootstrap di `aria/app/main.py`; migrasi penuh berarti menambahkan runtime mode non-TUI atau mode headless khusus Minecraft.
- Arsitektur cukup modular (`agent`, `tools`, `integrations`) sehingga integrasi bridge service Minecraft paling aman via `integrations/minecraft_bridge.py` + tool baru di executor.

## Keputusan desain utama
1. **Aksi tetap lewat tool tags** agar konsisten dengan arsitektur Aria, tapi dieksekusi secara **asinkron/event-driven** pada sisi Minecraft bridge.
2. **Bridge eksternal Node.js + Mineflayer** (bukan Python native) untuk kompatibilitas API terlengkap dan update ekosistem tercepat.
3. Python Aria ↔ Node Mineflayer via **local RPC/WebSocket** dengan dua kanal:
   - `command` (aksi eksplisit dari Aria)
   - `event stream` (chat, entity update, block update, damage, inventory, dsb)
4. Menjaga “parallel instinct”: scheduler tindakan berbasis priority queue + interrupt policy (contoh: sambil berjalan tetap bisa chat, combat micro, shield timing).

## Kebutuhan khusus pengguna (diterjemahkan ke requirement teknis)
- Join server `localhost:25565` versi `1.21.11` dengan username `Aria`.
- Pada first join/spawn, auto jalankan:
  - `/skin set web slim https://t.novaskin.me/21ca7e5f2c43f4c290db64d25cdaec05156405d30ad757bffb57b24222387d30 Aria`
- Aria hanya berbicara via chat Minecraft, bisa baca chat player, tahu lokasi player, dan merespons kondisional.
- Persepsi dunia mencakup block, mob, terrain, liquid, dan object/decoration.
- Dukungan aksi survival lengkap + concurrency aksi.

## Daftar kemampuan survival Minecraft yang harus dicakup (pre-implementasi)

### 1) Persepsi & world-state
- Posisi/orientasi diri, velocity, onGround, fallDistance.
- Deteksi block sekitar (voxel scan + raycast), termasuk liquid, light, passability, hazard.
- Tracking entity: player, mob hostile/passive, projectile, item drop, vehicle.
- Memori peta lokal: chunk cache, POI (chest, furnace, farm, portal, village, spawner, bed).
- Deteksi event: chat, hurt, death, explosion, block update, weather, time-of-day.

### 2) Lokomosi
- Jalan, sprint, sneak, lompat, parkour sederhana, swim, climb ladder/vine.
- Navigasi pathfinding ke koordinat, entity, block target, dan follow player.
- Boat/minecart/basic mount usage (survival-available).
- Recovery movement: unstuck, anti-fall, retreat vector, obstacle bypass.

### 3) Manipulasi block
- Digging (single/multi target), pilih tool optimal.
- Place block presisi (normal, scaffold, clutch-style block-under-jump).
- Interaksi block: door, trapdoor, lever, button, pressure plate, gate.
- Build pattern sederhana sampai blueprint terstruktur.

### 4) Inventory & item economy
- Hotbar selection cepat berbasis konteks.
- Auto-stack, garbage policy, item priority.
- Pickup/drop item, equip armor/offhand.
- Chest/barrel/shulker organization.

### 5) Crafting & processing
- Crafting 2x2 + crafting table.
- Smelting/blasting/smoking.
- Fuel management.
- Recipe planning berbasis goal.

### 6) Combat survival
- Target selection policy (threat + distance + line-of-sight).
- Melee timing (cooldown-aware), crit jump logic, knockback control.
- Ranged weapon handling (bow/crossbow/trident basic).
- Shield raise/lower timing dan swap attack-shield.
- Kiting (mundur sambil serang), strafe, disengage.

### 7) Resource gathering
- Mining by tier progression.
- Farming crop + replant.
- Woodcutting, mob loot farming dasar, fishing.
- Structure loot routing (village, mineshaft, trial-ish sesuai risk policy).

### 8) Survival maintenance
- HP/hunger monitoring + auto-eat.
- Sleep logic (bed usage).
- Fire/water/lava hazard mitigation.
- Respawn recovery: ambil item, kembali ke base/death point.

### 9) Social/chat intelligence
- Read all nearby/public chat events.
- Intent classifier: command, question, mention, noise.
- Response policy: kapan harus jawab, kapan diam.
- Koordinat player yang diminta/terdeteksi dapat dilaporkan.

### 10) Meta-control & safety
- Goal manager (short-term tactical + long-term strategic).
- Interrupt system (contoh: sedang mining lalu diserang creeper -> evade dulu).
- Rate-limited action loop agar anti-spam dan stabil.
- Audit log aksi + reason trace (untuk debug kualitas keputusan).

## Rekomendasi tool contract baru (XML tags)
- `<mc_connect host="localhost" port="25565" version="1.21.11" username="Aria" />`
- `<mc_chat>...</mc_chat>`
- `<mc_observe radius="32" include="blocks,entities,players,fluids" />`
- `<mc_move goal="x,y,z|follow:player|goto:block" />`
- `<mc_act action="dig|place|attack|use|equip|craft|smelt|sleep" ...>`
- `<mc_inventory action="list|sort|transfer|equip|drop" ...>`
- `<mc_combat mode="auto|defend|retreat|pvp" target="..." />`
- `<mc_stop />`

## Arsitektur implementasi bertahap (roadmap)
1. **Phase 0 - Bridge foundation**
   - Node service Mineflayer connect + heartbeat + event relay.
   - Python integration client + basic tools (`mc_connect`, `mc_chat`, `mc_observe`).
2. **Phase 1 - Full perception baseline**
   - Snapshot world model periodik (tick window), entity/block index.
3. **Phase 2 - Action core survival**
   - Move/dig/place/use/inventory/craft/smelt/sleep.
4. **Phase 3 - Combat & concurrency**
   - Parallel task scheduler (chat+move+combat micro).
5. **Phase 4 - Strategic autonomy**
   - Goal planning loops, long-horizon survival tasks.
6. **Phase 5 - TUI deprecation**
   - Mode default ke Minecraft runtime; TUI jadi optional debug console.

## State machine perilaku (ringkas)
- `IDLE` → `OBSERVE` → `DECIDE` → `ACT` → `REVIEW`
- Interrupt global:
  - `THREAT_HIGH` (evade/combat)
  - `LOW_HEALTH` (retreat/eat)
  - `CHAT_MENTION` (respond opportunistic)

## Catatan performa
- Gunakan tick-driven loop ringan (mis. 5–10 Hz untuk high-level planning, 20 Hz untuk micro-actions dari bot engine).
- Observasi dibatasi radius dinamis (close-range detail tinggi, far-range ringkas).
- Caching + diff update agar payload Python↔Node kecil.

## Referensi eksternal yang wajib dijadikan sumber implementasi
- Mineflayer repo/docs/api (fitur, event, API stabil/unstable, contoh).
- Mineflayer-pathfinder untuk navigasi.
- Mineflayer-pvp untuk baseline combat.
- Prismarine-data untuk naming block/entity lintas versi (normalisasi 1.21.11).
- Minecraft Wiki untuk daftar block/mob survival dan verifikasi istilah.

## Deliverable sesi ini
Dokumen ini adalah baseline analisis + blueprint kemampuan penuh survival sebelum coding implementasi bridge Minecraft dimulai.
