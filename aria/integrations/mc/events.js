const { state } = require('./bot')

let eventBuffer = []
const MAX_EVENTS = 1000
let eventEmitter = null

function setEmitter(fn) {
  eventEmitter = fn
}

function pushEvent(event, data = {}) {
  const payload = { event, data, time: Date.now() }
  eventBuffer.push(payload)
  if (eventEmitter) eventEmitter({ type: 'event', ...payload })
  if (eventBuffer.length > MAX_EVENTS) eventBuffer = eventBuffer.slice(-500)
}

function bindEvents() {
  const bot = state.bot
  if (!bot) return

  bot.on('messagestr', (m, pos, json, sender) => {
    if (pos === 'chat' || pos === 'system') {
        // Critical: Real-time chat emission
        pushEvent('chat', { username: sender || 'Server', message: m })
    }
  })
  
  bot.on('health', () => {
      pushEvent('health', { health: bot.health, food: bot.food })
      // Critical Fix 7: If bot is "stuck" due to damage, ensure physics/pathfinder is still active
      if (bot.pathfinder && bot.pathfinder.isMoving() === false && state.isBusy) {
          // Force tick if busy but not moving? No, just ensure physics is on
          bot.physics.enabled = true
      }
  })
  
  bot.on('death', () => {
      pushEvent('death', {})
      state.isBusy = false // Reset busy state on death to prevent lock
  })

  bot.on('kicked', (reason) => pushEvent('kicked', { reason: String(reason) }))
  
  bot.on('spawn', () => {
    pushEvent('spawn', {})
    bot.physics.enabled = true
    // Fix issue 8: Ensure bot doesn't act like a "solid wall" by adjusting physics if needed
    // In mineflayer, bot is an entity. Knockback usually works.
  })

  // Critical Fix 7 & 8: Damage handling
  bot.on('entityHurt', (entity) => {
      if (entity === bot.entity) {
          pushEvent('hurt', { health: bot.health })
          // If we take damage, don't stop! Just log it.
      }
  })
}

function getEvents(limit = 100, since = 0) {
  let filtered = since > 0 ? eventBuffer.filter(e => e.time > since) : eventBuffer
  return filtered.slice(-limit)
}

module.exports = { bindEvents, getEvents, pushEvent, setEmitter }
