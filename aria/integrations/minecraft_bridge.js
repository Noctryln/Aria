const readline = require('readline')
const mineflayer = require('mineflayer')
const { pathfinder, goals, Movements } = require('mineflayer-pathfinder')
const minecraftData = require('minecraft-data')

let bot = null
let mcData = null
let defaultMoves = null
let firstSpawnDone = false
let eventBuffer = []
let policy = { autoCombat: true, autoEat: true, followPlayer: null }
let strategicGoal = 'survive'
let strategicState = { lastAction: null, lastTick: 0 }

function pushEvent(event, data = {}) {
  eventBuffer.push({ event, data, time: Date.now() })
  if (eventBuffer.length > 2000) eventBuffer = eventBuffer.slice(-2000)
}
const send = (obj) => process.stdout.write(JSON.stringify(obj) + '\n')

function bindBotEvents() {
  bot.on('chat', (username, message) => pushEvent('chat', { username, message }))
  bot.on('whisper', (username, message) => pushEvent('whisper', { username, message }))
  bot.on('playerJoined', (player) => pushEvent('playerJoined', { username: player.username }))
  bot.on('entitySpawn', (entity) => pushEvent('entitySpawn', { id: entity.id, name: entity.name, type: entity.type }))
  bot.on('health', () => pushEvent('health', { health: bot.health, food: bot.food }))
  bot.on('death', () => pushEvent('death', {}))
  bot.on('kicked', (reason) => pushEvent('kicked', { reason: String(reason) }))
  bot.on('error', (err) => pushEvent('error', { message: String(err?.message || err) }))
  bot.once('spawn', () => {
    pushEvent('spawn', {})
    if (!firstSpawnDone) {
      firstSpawnDone = true
      bot.chat('/skin set web slim https://t.novaskin.me/21ca7e5f2c43f4c290db64d25cdaec05156405d30ad757bffb57b24222387d30 Aria')
    }
  })
}

function nearestHostile(maxDist = 16) {
  const hostile = new Set(['zombie','skeleton','creeper','spider','witch','drowned','husk','stray','phantom','enderman'])
  return bot.nearestEntity((e) => e.type === 'mob' && hostile.has(e.name) && bot.entity.position.distanceTo(e.position) <= maxDist)
}

async function runAutonomyTick() {
  if (!bot?.entity) return { ok: false, error: 'no_entity' }
  const actions = []

  if (policy.autoEat && bot.food !== undefined && bot.food <= 14) {
    try { await bot.consume(); actions.push('eat') } catch (_) {}
  }

  const threat = nearestHostile(12)
  if (policy.autoCombat && threat) {
    try {
      const dist = bot.entity.position.distanceTo(threat.position)
      if (dist > 3) {
        bot.pathfinder.setGoal(new goals.GoalNear(threat.position.x, threat.position.y, threat.position.z, 2))
        actions.push('chase_hostile')
      } else {
        bot.attack(threat)
        actions.push(`attack:${threat.name}`)
      }
    } catch (_) {}
  }

  if (policy.followPlayer) {
    const pl = bot.players[policy.followPlayer]
    if (pl?.entity) {
      bot.pathfinder.setGoal(new goals.GoalFollow(pl.entity, 2), true)
      actions.push(`follow:${policy.followPlayer}`)
    }
  }

  return { ok: true, actions }
}

function observe(radius = 8) {
  const p = bot.entity?.position
  const blocks = []
  if (p) {
    for (let x=-radius;x<=radius;x++) for (let y=-2;y<=2;y++) for (let z=-radius;z<=radius;z++) {
      const b = bot.blockAt(p.offset(x,y,z), false)
      if (b && b.name !== 'air' && b.name !== 'cave_air' && b.name !== 'void_air') blocks.push({ name:b.name, position:b.position, diggable:b.diggable })
    }
  }
  const players = Object.values(bot.players || {}).map((pl) => ({ username: pl.username, position: pl.entity?.position || null }))
  const entities = Object.values(bot.entities || {}).slice(0, 1000).map((e) => ({ id:e.id, name:e.name, type:e.type, kind:e.kind, position:e.position, velocity:e.velocity }))
  return { ok:true, self:{ username:bot.username, position:p||null, health:bot.health, food:bot.food, oxygen:bot.oxygenLevel }, players, entities, blocks, time:bot.time?.timeOfDay || null, isRaining:!!bot.isRaining }
}



async function runStrategicTick() {
  if (!bot?.entity) return { ok: false, error: 'no_entity' }
  const actions = []
  const now = Date.now()
  strategicState.lastTick = now

  if (strategicGoal === 'survive') {
    if (bot.health <= 8) {
      try { bot.setControlState('back', true); setTimeout(() => bot.setControlState('back', false), 450); actions.push('retreat_short') } catch (_) {}
    }
    const r = await runAutonomyTick()
    actions.push(...(r.actions || []))
  }

  if (strategicGoal === 'gather_wood') {
    const logs = bot.findBlocks({
      matching: (b) => b && (b.name.includes('log') || b.name.includes('stem')),
      maxDistance: 24,
      count: 1
    })
    if (logs.length) {
      const t = bot.blockAt(logs[0])
      if (t) {
        try {
          bot.pathfinder.setGoal(new goals.GoalNear(t.position.x, t.position.y, t.position.z, 1))
          actions.push('goto_log')
          const dist = bot.entity.position.distanceTo(t.position)
          if (dist <= 3) { await bot.dig(t); actions.push('dig_log') }
        } catch (_) {}
      }
    } else {
      actions.push('no_log_found')
    }
  }

  if (strategicGoal === 'stabilize') {
    if (bot.food <= 12) {
      try { await bot.consume(); actions.push('consume_food') } catch (_) {}
    }
    if (bot.time?.isNight) {
      actions.push('night_detected')
    }
  }

  strategicState.lastAction = actions[actions.length - 1] || null
  return { ok: true, strategicGoal, actions, strategicState }
}

async function handle(action, data) {
  if (action === 'connect') {
    if (bot) { try { bot.quit() } catch(_) {} }
    bot = mineflayer.createBot({ host:data.host||'localhost', port:Number(data.port||25565), username:data.username||'Aria', version:data.version||'1.21.11' })
    bot.loadPlugin(pathfinder)
    mcData = minecraftData(bot.version)
    defaultMoves = new Movements(bot, mcData)
    bot.pathfinder.setMovements(defaultMoves)
    bindBotEvents()
    return { ok:true }
  }
  if (!bot) return { ok:false, error:'not_connected' }

  if (action === 'chat') { bot.chat(data.message || ''); return { ok:true } }
  if (action === 'observe') return observe(Number(data.radius || 8))
  if (action === 'events') return { ok:true, events:eventBuffer.slice(-Number(data.limit||100)) }
  if (action === 'inventory') return { ok:true, heldItem: bot.heldItem ? { name: bot.heldItem.name, count: bot.heldItem.count } : null, items: bot.inventory.items().map(it=>({name:it.name,count:it.count,slot:it.slot})) }

  if (action === 'set_policy') {
    policy = { ...policy, ...(data || {}) }
    return { ok:true, policy }
  }
  if (action === 'set_goal') {
    strategicGoal = String(data.goal || 'survive')
    return { ok: true, strategicGoal }
  }
  if (action === 'autonomy_tick') return await runAutonomyTick()
  if (action === 'strategic_tick') return await runStrategicTick()

  if (action === 'move_to') {
    bot.pathfinder.setGoal(new goals.GoalNear(Number(data.x), Number(data.y), Number(data.z), Number(data.range || 1)))
    return { ok:true }
  }
  if (action === 'follow') {
    const pl = bot.players[data.username]
    if (!pl?.entity) return { ok:false, error:'player_not_found' }
    bot.pathfinder.setGoal(new goals.GoalFollow(pl.entity, Number(data.range || 2)), true)
    return { ok:true }
  }

  if (action === 'control') { for (const k of ['forward','back','left','right','jump','sprint','sneak']) if (typeof data[k]==='boolean') bot.setControlState(k,data[k]); return { ok:true } }
  if (action === 'look') { await bot.look(Number(data.yaw||0), Number(data.pitch||0), !!data.force); return { ok:true } }
  if (action === 'stop') { bot.pathfinder.setGoal(null); for (const k of ['forward','back','left','right','jump','sprint','sneak']) bot.setControlState(k,false); return { ok:true } }

  if (action === 'act') {
    const kind = data.kind
    if (kind === 'attack_nearest') { const e = bot.nearestEntity(en => en.type === 'mob' || en.type === 'player'); if (!e) return { ok:false,error:'no_target' }; bot.attack(e); return {ok:true,target:{id:e.id,name:e.name,type:e.type}} }
    if (kind === 'dig_look') { const t = bot.blockAtCursor(Number(data.maxDistance||5)); if (!t) return {ok:false,error:'no_block_at_cursor'}; await bot.dig(t); return {ok:true,block:t.name} }
    if (kind === 'equip') { const item = bot.inventory.items().find(it => it.name === (data.itemName || '')); if (!item) return {ok:false,error:'item_not_found'}; await bot.equip(item, data.destination || 'hand'); return {ok:true} }
    if (kind === 'use') { await bot.activateItem(); return {ok:true} }
    if (kind === 'eat') { await bot.consume(); return {ok:true} }
    return { ok:false,error:`unknown_act:${kind}` }
  }

  return { ok:false,error:`unknown_action:${action}` }
}

readline.createInterface({ input: process.stdin, crlfDelay: Infinity }).on('line', async (line) => {
  try {
    const req = JSON.parse(line)
    try { send({ type:'response', id:req.id, data: await handle(req.action, req.data || {}) }) }
    catch (e) { send({ type:'response', id:req.id, data:{ ok:false,error:String(e?.message||e) } }) }
  } catch (_) {}
})
