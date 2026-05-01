const mineflayer = require('mineflayer')
const { pathfinder, Movements } = require('mineflayer-pathfinder')
const collectBlock = require('mineflayer-collectblock').plugin
const pvp = require('mineflayer-pvp').plugin
const armorManager = require('mineflayer-armor-manager')
const toolPlugin = require('mineflayer-tool').plugin
const minecraftData = require('minecraft-data')

const state = {
  bot: null,
  mcData: null,
  defaultMoves: null,
  isBusy: false,
  activeTaskId: 0,
  policy: {
    autoCombat: true,
    autoEat: true
  },
  autopilot: {
    enabled: false,
    intervalMs: 2000
  },
  lastDamageTime: 0
}

async function connect(options) {
  return new Promise((resolve, reject) => {
    const bot = mineflayer.createBot({
      host: options.host || 'localhost',
      port: options.port || 25565,
      username: options.username || 'Aria',
      version: options.version || '1.21.1',
      physicsEnabled: true // Explicitly enable physics
    })

    const timer = setTimeout(() => reject(new Error('Connection timeout')), 30000)

    bot.once('spawn', () => {
      clearTimeout(timer)
      state.bot = bot
      state.mcData = minecraftData(bot.version)
      
      bot.loadPlugin(pathfinder)
      bot.loadPlugin(collectBlock)
      bot.loadPlugin(pvp)
      bot.loadPlugin(armorManager)
      bot.loadPlugin(toolPlugin)
      
      state.defaultMoves = new Movements(bot)
      state.defaultMoves.allow1by1tunnelling = false
      state.defaultMoves.canDig = true
      state.defaultMoves.allowSprinting = true
      state.defaultMoves.maxDropDown = 4
      state.defaultMoves.entityCost = 1.5
      
      state.scaffoldingBlocks = ['dirt', 'cobblestone', 'netherrack', 'stone', 'andesite', 'diorite', 'granite', 'sand', 'gravel']
      
      bot.pathfinder.setMovements(state.defaultMoves)
      
      bot.physics.enabled = true
      bot.physics.yieldInterval = 10 

      // INSTANT PHYSICS RESYNC (Point 15 - Tick Based)
      bot.on('physicsTick', () => {
          const p = bot.entity.position
          if (isNaN(p.x) || isNaN(p.y) || isNaN(p.z) || p.x === null) {
              if (lastValidPos) {
                  bot.entity.position.set(lastValidPos.x, lastValidPos.y, lastValidPos.z)
              } else {
                  bot.entity.position.set(p.x || 0, 64, p.z || 0)
              }
              bot.entity.velocity.set(0, 0, 0)
          } else if (p.y > -64 && p.y < 320) {
              lastValidPos = p.clone()
          }
          
          if (!bot.physics.enabled) bot.physics.enabled = true
          
          // Anti-Ghosting Nudge (Every 20 ticks / 1 second approx)
          if (bot.entity.time % 20 === 0 && !bot.entity.onGround && bot.entity.velocity.y === 0 && !bot.entity.isInWater) {
              bot.entity.position.y -= 0.01
              bot.entity.velocity.y = -0.1
          }
      })

      // Initial Environment Scan
      const send = (obj) => process.stdout.write(JSON.stringify(obj) + '\n')
      send({ type: 'event', event: 'spawn', data: { username: bot.username } })
      
      resolve({ ok: true, username: bot.username })
    })

    bot.on('entityHurt', (entity) => {
        if (!bot.entity) return
        if (entity === bot.entity) {
            state.lastDamageTime = Date.now()
            // Reset pathfinder if we get hit to allow reactive combat
            if (state.isBusy) {
                bot.pathfinder.setGoal(null)
            }
            bot.physics.enabled = true // Force physics on
            
            // Push immediate notification to UI
            const send = (obj) => process.stdout.write(JSON.stringify(obj) + '\n')
            send({ 
                type: 'event', 
                event: 'error', 
                data: { message: `Aria diserang! Health: ${Math.round(bot.health)}`, severity: 'warn' } 
            })
        }
    })

    bot.on('death', () => {
        const { pushEvent } = require('./events')
        pushEvent('death')
        const send = (obj) => process.stdout.write(JSON.stringify(obj) + '\n')
        send({ type: 'event', event: 'death', data: {} })
        state.isBusy = false
        bot.physics.enabled = true
    })

    bot.on('kicked', (reason) => {
        const send = (obj) => process.stdout.write(JSON.stringify(obj) + '\n')
        send({ type: 'event', event: 'kicked', data: { reason: String(reason) } })
        state.bot = null
        state.isBusy = false
    })

    bot.on('kick', (reason) => {
      clearTimeout(timer)
      state.bot = null
      state.isBusy = false
      reject(new Error(`Kicked: ${reason}`))
    })

    bot.on('end', () => {
        state.bot = null
        state.isBusy = false
    })
    
    bot.once('error', (err) => {
      clearTimeout(timer)
      reject(new Error(`Error: ${err.message || err}`))
    })
  })
}

module.exports = {
  state,
  connect
}
