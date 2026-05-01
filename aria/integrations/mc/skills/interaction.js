const { state } = require('../bot')
const vec3 = require('vec3')

async function placeBlock(itemName, x, y, z) {
  const bot = state.bot
  if (!bot || !bot.entity) return { ok: false, error: 'bot_not_connected' }
  
  // Robust itemName detection
  let name = itemName
  if (typeof itemName === 'object') {
      name = itemName.itemName || itemName.target || itemName.name
  }
  if (!name) return { ok: false, error: 'item_name_missing' }

  bot.physics.enabled = true
  const pos = new vec3(Math.floor(x), Math.floor(y), Math.floor(z))
  
  const item = bot.inventory.items().find(i => 
    i.name === name || 
    i.name.toLowerCase().includes(name.toLowerCase())
  )
  if (!item) return { ok: false, error: `item_not_in_inventory: ${name}` }

  try {
    // 1. CLEAR OBSTACLES
    const currentBlock = bot.blockAt(pos)
    const softBlocks = ['grass', 'tall_grass', 'fern', 'large_fern', 'poppy', 'dandelion', 'snow', 'water', 'lava', 'cave_air', 'air', 'void_air']
    
    if (currentBlock && !softBlocks.includes(currentBlock.name)) {
        await bot.lookAt(pos.offset(0.5, 0.5, 0.5), true)
        const tool = bot.pathfinder.bestHarvestTool(currentBlock)
        if (tool) await bot.equip(tool, 'hand')
        try { await bot.dig(currentBlock) } catch(_) {}
        await new Promise(r => setTimeout(r, 400))
    }

    // 2. SELF-OBSTRUCTION CHECK
    const botPos = bot.entity.position
    const dx = Math.abs(botPos.x - (pos.x + 0.5))
    const dz = Math.abs(botPos.z - (pos.z + 0.5))
    const dy = botPos.y - pos.y
    
    if (dx < 0.7 && dz < 0.7 && dy > -1.2 && dy < 1.0) {
        const diff = botPos.minus(pos.offset(0.5, 0, 0.5))
        let moveDir = (dx < 0.1 && dz < 0.1) ? new vec3(1.3, 0, 0.9) : diff.normalize().scaled(1.6)
        const safeSpot = botPos.plus(moveDir)
        const movement = require('./movement')
        await movement.moveTo(safeSpot.x, safeSpot.y, safeSpot.z, 0.2, 1000).catch(() => {})
        await new Promise(r => setTimeout(r, 150))
    }

    // 3. FIND REFERENCE BLOCK (Exhaustive search)
    const faces = [
        { dir: new vec3(0, -1, 0), face: new vec3(0, 1, 0) }, // Base below
        { dir: new vec3(0, 1, 0), face: new vec3(0, -1, 0) }, // Ceiling above
        { dir: new vec3(1, 0, 0), face: new vec3(-1, 0, 0) },
        { dir: new vec3(-1, 0, 0), face: new vec3(1, 0, 0) },
        { dir: new vec3(0, 0, 1), face: new vec3(0, 0, -1) },
        { dir: new vec3(0, 0, -1), face: new vec3(0, 0, 1) }
    ]

    const isSolid = (b) => b && !softBlocks.includes(b.name)

    let referenceBlock = null
    let placedFace = null

    for (const f of faces) {
        const neighbor = bot.blockAt(pos.plus(f.dir))
        if (isSolid(neighbor)) {
            referenceBlock = neighbor
            placedFace = f.face
            break
        }
    }

    // If still no base, try checking diagonal neighbors or just failing with better info
    if (!referenceBlock) {
        // One last check: maybe we can place it on the block we're currently standing on if it's near enough
        const standingOn = bot.blockAt(bot.entity.position.offset(0, -1, 0))
        if (isSolid(standingOn) && standingOn.position.distanceTo(pos) < 5) {
            // Find which face of standingOn is closest to pos?
            // Usually if we can't find a direct neighbor, we can't place it in vanilla without a base.
        }
        return { ok: false, error: `no_solid_base_to_place_on_at_${pos.x}_${pos.y}_${pos.z}` }
    }

    await bot.equip(item, 'hand')
    const lookPoint = referenceBlock.position.offset(0.5, 0.5, 0.5).plus(placedFace.scaled(0.4))
    await bot.lookAt(lookPoint, true)

    await bot.placeBlock(referenceBlock, placedFace)
    return { ok: true, placed: name, pos: { x: pos.x, y: pos.y, z: pos.z } }
  } catch (e) {
    return { ok: false, error: `place_failed: ${String(e.message || e)}` }
  }
}

async function act(action, data) {
  const bot = state.bot
  if (!bot) throw new Error('Bot not initialized')
  if (action === 'use') { await bot.activateItem(); return { ok: true } }
  return { ok: false, error: 'unknown_interaction_action' }
}

module.exports = { act, placeBlock }
