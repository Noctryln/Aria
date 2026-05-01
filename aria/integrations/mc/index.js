const readline = require('readline')
const { connect, state } = require('./bot')
const { bindEvents, getEvents, setEmitter } = require('./events')

// Load Skills
const perception = require('./skills/perception')
const movement = require('./skills/movement')
const interaction = require('./skills/interaction')
const crafting = require('./skills/crafting')
const autonomy = require('./skills/autonomy')

const send = (obj) => process.stdout.write(JSON.stringify(obj) + '\n')
setEmitter(send)

process.on('uncaughtException', (err) => {
  console.error('Uncaught Exception:', err)
  send({ type: 'event', event: 'error', data: { message: String(err.message || err), stack: err.stack } })
})

process.on('unhandledRejection', (reason, promise) => {
  console.error('Unhandled Rejection at:', promise, 'reason:', reason)
})

let autopilotTimer = null

// Physics recovery is now handled in bot.js via 'physicsTick' for near-instant response.

function startAutopilot() {
  stopAutopilot()
  if (!state.autopilot.enabled) return
  autopilotTimer = setInterval(async () => {
    if (!state.bot?.entity || state.isBusy) return
    state.isBusy = true
    try { await runAutonomyTick() } catch (_) {}
    state.isBusy = false
  }, Math.max(200, state.autopilot.intervalMs))
}

function stopAutopilot() {
  if (autopilotTimer) {
    clearInterval(autopilotTimer)
    autopilotTimer = null
  }
}

async function runAutonomyTick() {
  const bot = state.bot
  if (!bot?.entity) return { ok: false, error: 'no_entity' }
  const actions = []

  // Auto-Eat logic
  if (state.policy.autoEat && bot.food <= 14) {
    const food = bot.inventory.items().find(i => state.mcData?.foodsByName[i.name])
    if (food) {
        try { 
            await bot.equip(food, 'hand')
            await bot.consume()
            actions.push('eat') 
        } catch (_) {}
    }
  }

  // Reactive combat
  if (state.policy.autoCombat) {
    const hostile = new Set(['zombie','skeleton','creeper','spider','witch','drowned','husk','stray','phantom','enderman'])
    const threat = bot.nearestEntity((e) => e.type === 'mob' && hostile.has(e.name) && bot.entity.position.distanceTo(e.position) <= 12)
    
    if (threat) {
      const dist = bot.entity.position.distanceTo(threat.position)
      if (dist > 3) {
          await autonomy.executeAct('move', { x: threat.position.x, y: threat.position.y, z: threat.position.z, range: 2 })
          actions.push('chase_hostile')
      } else {
          await autonomy.executeAct('attack', { target: threat.name })
          actions.push(`attack:${threat.name}`)
      }
    }
  }

  return { ok: true, actions }
}

async function handle(action, data) {
  try {
    if (action === 'connect') {
      await connect(data)
      bindEvents()
      if (state.autopilot.enabled) startAutopilot()
      return { ok: true, connected: true }
    }
    
    if (!state.bot) return { ok: false, error: 'not_connected' }

    // INTERRUPT MECHANISM (Point 11)
    if (['act', 'stop'].includes(action)) {
        if (state.isBusy) {
            state.isBusy = false
            state.activeTaskId = (state.activeTaskId || 0) + 1
            if (state.bot) {
                state.bot.pathfinder.setGoal(null)
                state.bot.clearControlStates()
                try { state.bot.stopDigging() } catch(_) {}
            }
            await new Promise(r => setTimeout(r, 150))
        }
    }

    if (action === 'chat') { state.bot.chat(data.message || ''); return { ok: true } }
    if (action === 'events') return { ok: true, events: getEvents(Number(data.limit || 100), Number(data.since || 0)) }
    if (action === 'observe') return perception.observe(Number(data.radius || 8))
    if (action === 'inventory') return perception.getInventory()

    if (state.isBusy && action === 'autonomy_tick') return { ok: false, error: 'bot_is_busy' }

    if (action === 'act') {
        const myId = (state.activeTaskId || 0)
        state.isBusy = true
        try {
            const wasAutopilot = state.autopilot.enabled
            if (wasAutopilot) stopAutopilot()
            const kind = data.kind || data.action
            const res = await autonomy.executeAct(kind, data)
            if (wasAutopilot) startAutopilot()
            if (state.activeTaskId === myId) state.isBusy = false
            return res
        } catch (e) {
            if (state.activeTaskId === myId) state.isBusy = false
            throw e
        }
    }

    if (action === 'stop') { movement.stop(); return { ok: true } }
    if (action === 'look') return await movement.look(data.yaw, data.pitch, data.force)
    if (action === 'control') return movement.control(data)

    if (action === 'set_policy') {
      state.policy = { ...state.policy, ...(data || {}) }
      return { ok: true, policy: state.policy }
    }
    if (action === 'set_autopilot') {
      state.autopilot = { ...state.autopilot, ...(data || {}) }
      if (state.autopilot.enabled) startAutopilot()
      else stopAutopilot()
      return { ok: true, autopilot: state.autopilot }
    }
    if (action === 'autonomy_tick') {
        const myId = (state.activeTaskId || 0)
        state.isBusy = true
        try {
            const res = await runAutonomyTick()
            if (state.activeTaskId === myId) state.isBusy = false
            return res
        } catch (e) {
            if (state.activeTaskId === myId) state.isBusy = false
            throw e
        }
    }

    return { ok: false, error: `unknown_action:${action}` }
  } catch (err) {
    return { ok: false, error: String(err?.message || err) }
  }
}

const rl = readline.createInterface({ input: process.stdin, crlfDelay: Infinity })

// Sequential execution for specific actions to prevent state conflicts
let currentActionPromise = Promise.resolve()

rl.on('line', async (line) => {
  try {
    const req = JSON.parse(line)
    
    // Connect remains sequential to avoid multiple bot instances
    const isSequential = ['connect'].includes(req.action)
    
    const execute = async () => {
        try {
          const resp = await handle(req.action, req.data || {})
          send({ type: 'response', id: req.id, data: resp })
        } catch (e) {
          send({ type: 'response', id: req.id, data: { ok: false, error: String(e?.message || e) } })
        }
    }

    if (isSequential) {
        currentActionPromise = currentActionPromise.then(execute).catch(() => {})
    } else {
        // Run concurrently. handle() will manage isBusy and activeTaskId.
        execute()
    }
  } catch (_) {}
})
