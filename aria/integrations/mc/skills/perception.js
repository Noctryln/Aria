const { state } = require('../bot')

function observe(radius = 16, targets = []) {
  const bot = state.bot
  if (!bot || !bot.entity) return { ok: false, error: 'bot_not_connected' }
  
  const p = bot.entity.position
  if (isNaN(p.x) || isNaN(p.y) || isNaN(p.z)) {
      bot.physics.enabled = true // Emergency reset
      return { ok: false, error: 'bot_position_is_nan' }
  }
  
  const candidates = []
  
  const normTargets = (Array.isArray(targets) ? targets : [targets])
    .filter(t => t)
    .map(t => t.toLowerCase().replace(/ /g, '_'))

  const BASE_SCORES = {
    'ore': 1200,
    'log': 1000,
    'table': 800,
    'chest': 900,
    'furnace': 850,
    'bed': 700,
    'door': 400,
    'torch': 300,
    'crops': 200,
    'leaves': -300,
    'grass': -400,
    'dirt': -350,
    'stone': -200
  }

  // Expanded Scan for better environment mapping
  for (let x = -radius; x <= radius; x++) {
      for (let y = -8; y <= 24; y++) { // Significantly wider vertical scan
          for (let z = -radius; z <= radius; z++) {
              const b = bot.blockAt(p.offset(x, y, z), false)
              if (b && b.name !== 'air' && b.name !== 'cave_air' && b.name !== 'void_air') {
                  let score = 0
                  const bName = b.name.toLowerCase().replace(/ /g, '_')
                  
                  // Target boost (highest priority)
                  for (const t of normTargets) {
                      if (bName === t || bName.includes(t)) {
                          score += 6000 / (p.distanceTo(b.position) + 1)
                      }
                  }

                  // Category boost
                  for (const [cat, val] of Object.entries(BASE_SCORES)) {
                      if (bName.includes(cat)) {
                          score += val
                          break
                      }
                  }
                  
                  const dist = p.distanceTo(b.position)
                  candidates.push({ name: b.name, pos: b.position, score, dist })
              }
          }
      }
  }
  
  // Sort by score (importance) then proximity
  candidates.sort((a, b) => b.score - a.score || a.dist - b.dist)

  const players = Object.values(bot.players)
    .filter(pl => pl.entity && pl.entity.position.distanceTo(p) < 64)
    .map(pl => ({ 
      u: pl.username, 
      p: pl.entity.position.floored(),
      d: Math.round(pl.entity.position.distanceTo(p))
    }))
  
  const mobs = Object.values(bot.entities)
    .filter(e => e.type === 'mob' && e.position.distanceTo(p) < 32)
    .map(e => ({ 
      n: e.name, 
      p: e.position.floored(),
      d: Math.round(e.position.distanceTo(p)),
      h: isHostile(e.name)
    }))

  return { 
    ok: true, 
    self: { p: p.floored(), h: bot.health, f: bot.food }, 
    players, 
    mobs,
    nearby: candidates.slice(0, 60).map(c => ({ name: c.name, pos: c.pos })), 
    time: bot.time.timeOfDay < 13000 ? 'Day' : 'Night'
  }
}

function isHostile(name) {
  const hostile = ['zombie', 'skeleton', 'creeper', 'spider', 'enderman', 'witch', 'slime', 'ghast', 'blaze', 'drowned', 'husk', 'stray']
  return hostile.includes(name.toLowerCase())
}

function findBlocks(names, maxDistance = 64, count = 5) {
  const bot = state.bot
  if (!bot) throw new Error('Bot not initialized')

  const targetNames = Array.isArray(names) ? names : [names]
  const matching = targetNames.map(n => state.mcData.blocksByName[n]?.id).filter(id => id !== undefined)
  
  if (matching.length === 0) return { ok: false, error: 'unknown_block_names' }
  
  const blocks = bot.findBlocks({ 
    matching, 
    maxDistance: Number(maxDistance), 
    count: Number(count) 
  })
  
  const p = bot.entity.position
  blocks.sort((a, b) => a.distanceTo(p) - b.distanceTo(p))
  
  return { ok: true, positions: blocks.map(b => ({ x: b.x, y: b.y, z: b.z })) }
}

function getInventory() {
  const bot = state.bot
  if (!bot) throw new Error('Bot not initialized')

  return { 
    ok: true, 
    heldItem: bot.heldItem ? { name: bot.heldItem.name, count: bot.heldItem.count } : null, 
    items: bot.inventory.items().map(it => ({ name: it.name, count: it.count })) 
  }
}

module.exports = {
  observe,
  findBlocks,
  getInventory
}
