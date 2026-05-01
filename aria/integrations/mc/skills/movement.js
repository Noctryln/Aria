const { state } = require('../bot')
const { goals } = require('mineflayer-pathfinder')
const vec3 = require('vec3')

async function moveTo(x, y, z, range = 1, timeoutMs = 3600000) { // 1 hour timeout (practically infinite)
  const bot = state.bot
  if (!bot || !bot.entity) throw new Error('Bot not initialized or disconnected')

  bot.clearControlStates()
  const targetPos = new vec3(Number(x), Number(y), Number(z))
  const goalRange = Math.max(Number(range), 1.5)
  const goal = new goals.GoalNear(targetPos.x, targetPos.y, targetPos.z, goalRange)

  return new Promise((resolve) => {
    let resolved = false
    const finish = (result) => {
      if (resolved) return
      resolved = true
      if (bot.pathfinder) bot.pathfinder.setGoal(null)
      bot.removeListener('goal_reached', onReach)
      bot.removeListener('path_update', onPathUpdate)
      clearInterval(checkInterval)
      clearTimeout(timer)
      resolve(result)
    }

    const onReach = () => finish({ ok: true, note: 'Goal reached' })

    let lastPos = bot.entity.position.clone()
    let stuckCount = 0

    const checkInterval = setInterval(async () => {
      if (resolved || !bot.entity) return
      
      const curPos = bot.entity.position
      const movedDist = curPos.distanceTo(lastPos)
      
      if (movedDist > 0.2) {
          stuckCount = 0
      } else {
          stuckCount++
          if (stuckCount > 6) {
              bot.setControlState('jump', true)
              setTimeout(() => { if (!resolved && bot.entity) bot.setControlState('jump', false) }, 400)
              
              if (stuckCount > 15 && curPos.y < targetPos.y - 1) {
                  await pillarUp().catch(() => {})
              }
              // Don't timeout here, let the main timer handle it
          }
      }

      const isInWater = bot.entity.isInWater || bot.entity.isInLava
      if (isInWater) {
          if (targetPos.y > curPos.y + 0.5) bot.setControlState('jump', true)
          else if (targetPos.y < curPos.y - 0.5) bot.setControlState('jump', false)
          else bot.setControlState('jump', (curPos.y % 1) < 0.6) 
          bot.setControlState('forward', true)
      }

      lastPos = curPos.clone()
    }, 500)

    const onPathUpdate = (r) => {
      // Logic for path updates if needed
    }

    const timer = setTimeout(() => finish({ ok: false, error: 'timeout_limit_reached', pos: bot.entity?.position }), timeoutMs)

    bot.on('goal_reached', onReach)
    bot.on('path_update', onPathUpdate)

    bot.pathfinder.goto(goal).catch(err => {
      if (err.name === 'GoalChanged' || err.message?.includes('GoalChanged')) {
          finish({ ok: false, error: 'interrupted' })
          return
      }
      finish({ ok: false, error: err.message })
    })
  })
}

async function pillarUp() {
  const bot = state.bot
  if (!bot?.entity) return { ok: false, error: 'no_entity' }
  
  const items = bot.inventory.items()
  const preferred = items.filter(it => state.scaffoldingBlocks.includes(it.name))
  const otherBlocks = items.filter(it => {
      const bData = state.mcData.blocksByName[it.name]
      return bData && bData.boundingBox === 'block' && !it.name.includes('log') && !it.name.includes('plank')
  })

  const item = preferred[0] || otherBlocks[0]
  if (!item) return { ok: false, error: 'no_blocks_for_pillar' }
  
  try {
    bot.clearControlStates()
    if (bot.pathfinder) bot.pathfinder.setGoal(null)
    
    await bot.equip(item, 'hand')
    await bot.look(bot.entity.yaw, -Math.PI / 2, true)
    
    // Get the block Aria is currently standing on (using floor to be precise)
    const p = bot.entity.position.floored()
    const blockBelow = bot.blockAt(p.offset(0, -1, 0))
    
    if (!blockBelow || ['air', 'cave_air', 'water', 'lava'].includes(blockBelow.name)) {
        // If standing on air, try to place against any solid neighbor at feet level
        const neighbors = [
            p.offset(1, -1, 0), p.offset(-1, -1, 0), 
            p.offset(0, -1, 1), p.offset(0, -1, -1)
        ]
        let found = null
        for (const n of neighbors) {
            const b = bot.blockAt(n)
            if (b && b.name !== 'air') { found = b; break }
        }
        if (!found) return { ok: false, error: 'no_base_to_pillar_from' }
    }

    bot.setControlState('jump', true)
    await new Promise(r => setTimeout(r, 260)) 
    
    bot.setControlState('jump', false)
    // Place block at the exact floored position Aria just jumped from
    const ref = bot.blockAt(p.offset(0, -1, 0))
    await bot.placeBlock(ref, new vec3(0, 1, 0))
    
    await new Promise(r => setTimeout(r, 150))
    return { ok: true }
  } catch (e) {
    bot.setControlState('jump', false)
    return { ok: false, error: `pillar_failed: ${e.message}` }
  }
}

function stop() {
  const bot = state.bot
  if (bot) {
    bot.pathfinder.stop()
    bot.clearControlStates()
  }
  return { ok: true }
}

module.exports = { moveTo, pillarUp, stop }
