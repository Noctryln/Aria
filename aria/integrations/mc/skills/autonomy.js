const { state } = require('../bot')
const movement = require('./movement')
const interaction = require('./interaction')
const vec3 = require('vec3')

const activeTasks = new Set()

async function executeAct(action, data) {
  const bot = state.bot
  if (!bot) throw new Error('Bot not initialized')
  if (bot.health <= 0) return { ok: false, error: 'bot_is_dead' }

  // Initial Scan if bot just spawned/connected
  if (!state._initialScanDone) {
      state._initialScanDone = true
      const perception = require('./perception')
      await perception.observe(16)
      await perception.getInventory()
  }

  bot.physics.enabled = true

  const myTaskId = Number(state.activeTaskId || 0)
  
  const rawTarget = data.target || data.itemName
  const targetName = rawTarget ? rawTarget.toLowerCase().replace(/ /g, '_') : null
  
  const taskID = `${action}:${targetName || (data.x + ',' + data.y + ',' + data.z)}`
  if (activeTasks.has(taskID)) return { ok: false, error: 'task_already_running' }
  activeTasks.add(taskID)

  try {
      let result = { ok: false }
      switch (action) {
        case 'mine':
        case 'collect':
          // TREE CHOPPING LOGIC IMPROVEMENT (Point 13)
          if (targetName && targetName.includes('log')) {
              result = await performCompleteTreeChop(targetName, data.count || 1, myTaskId)
          } else {
              result = await performContinuousCollect(targetName || rawTarget, data.count || 1, myTaskId)
          }
          break
        case 'craft':
          result = await performCraft(targetName || rawTarget, data.count || 1, 0, new Set(), myTaskId)
          break
        case 'move':
          result = await movement.moveTo(data.x, data.y, data.z, data.range || 1)
          break
        case 'place':
          if (data.blocks) result = await performMultiPlace(data.blocks, myTaskId)
          else result = await performSmartPlace(targetName || rawTarget, data.x, data.y, data.z)
          break
        case 'attack':
          result = await performAttack(data.target, myTaskId)
          break
        case 'eat':
          result = await performEat()
          break
        case 'equip':
          result = await performEquip(targetName || rawTarget)
          break
        case 'interact':
          result = await performInteract(data.x, data.y, data.z)
          break
        default:
          return { ok: false, error: `unknown_action: ${action}` }
      }
      return { ...result, perception: getShortRangeSnapshot(6, targetName) }
  } catch (e) {
      return { ok: false, error: String(e.message || e) }
  } finally {
      activeTasks.delete(taskID)
      if (bot.entity) bot.physics.enabled = true // Always ensure physics are on after action
  }
}

async function performContinuousCollect(target, count = 1, taskId) {
    const bot = state.bot
    if (!bot || !bot.entity) return { ok: false, error: 'bot_not_connected' }
    
    const normTarget = target.toLowerCase().replace(/ /g, '_')
    const getOwned = () => bot.inventory.items().filter(it => {
        const itName = it.name.toLowerCase().replace(/ /g, '_')
        return itName === normTarget || itName.includes(normTarget)
    }).reduce((a, b) => a + b.count, 0)
    
    const initialOwned = getOwned()
    const goalCount = initialOwned + count
    let gathered = 0
    let lastErr = 'no_targets_found'
    
    const blockType = state.mcData.blocksByName[normTarget] || state.mcData.blocksByName[target]
    const matchIDs = blockType ? [blockType.id] : []
    
    for (let i = 0; i < count + 60; i++) {
        if (Number(state.activeTaskId || 0) !== taskId) return { ok: false, error: 'interrupted' }
        if (getOwned() >= goalCount) {
            await performManualPickup(bot.entity.position, 6)
            return { ok: true, note: `Collected ${count} ${target}` }
        }
        
        // Priority 1: Pick up nearby drops of the target
        const nearbyDrop = bot.nearestEntity(e => e.type === 'object' && e.name.toLowerCase().includes(normTarget) && e.position.distanceTo(bot.entity.position) < 12)
        if (nearbyDrop) {
            await movement.moveTo(nearbyDrop.position.x, nearbyDrop.position.y, nearbyDrop.position.z, 0.4, 3000).catch(() => {})
            continue
        }

        if (bot.inventory.emptySlotCount() === 0) {
            const hasStackable = bot.inventory.items().find(it => it.name.includes(normTarget) && it.count < 64)
            if (!hasStackable) return { ok: false, error: 'inventory_full_cannot_collect_more' }
        }
        
        const block = bot.findBlock({ 
            matching: (blk) => {
                if (!blk) return false
                const bName = blk.name.toLowerCase().replace(/ /g, '_')
                return (bName === normTarget || bName.includes(normTarget) || matchIDs.includes(blk.type)) && isExposed(blk)
            },
            maxDistance: 64
        })
        
        if (!block) {
            const drop = bot.nearestEntity(e => e.type === 'object' && e.name.toLowerCase().includes(normTarget))
            if (drop) { 
                await movement.moveTo(drop.position.x, drop.position.y, drop.position.z, 0.5)
                await new Promise(r => setTimeout(r, 400))
                continue 
            }
            lastErr = `no_more_${target}_found_nearby`; break
        }

        const res = await performCollect(block.name, goalCount - getOwned(), 0, new Set(), taskId)
        if (!res.ok) { lastErr = res.error; break }
        gathered++
        
        // Periodic pickup
        if (i % 2 === 0) await performManualPickup(block.position, 8)
        await new Promise(r => setTimeout(r, 100))
    }
    await performManualPickup(bot.entity.position, 8)
    return gathered > 0 ? { ok: true } : { ok: false, error: lastErr }
}

async function performCompleteTreeChop(logType, treeCount = 1, taskId) {
    const bot = state.bot
    const normLog = logType.toLowerCase().replace(/ /g, '_')
    let treesDone = 0

    for (let t = 0; t < treeCount; t++) {
        if (Number(state.activeTaskId || 0) !== taskId) return { ok: false, error: 'interrupted' }
        
        const baseBlock = bot.findBlock({
            matching: blk => blk && blk.name.toLowerCase().includes(normLog) && isExposed(blk),
            maxDistance: 48
        })
        if (!baseBlock || !baseBlock.position) break

        // Collect all connected logs vertically
        let currentPos = baseBlock.position.clone()
        let logsInTree = []
        
        // Find bottom-most log of this tree
        while (currentPos) {
            const below = bot.blockAt(currentPos.offset(0, -1, 0))
            if (below && below.name.toLowerCase().includes(normLog)) currentPos = below.position.clone()
            else break
        }

        // Gather all logs in the vertical column
        let tempPos = currentPos ? currentPos.clone() : null
        while (tempPos && logsInTree.length < 32) {
            const b = bot.blockAt(tempPos)
            if (b && b.name.toLowerCase().includes(normLog)) {
                logsInTree.push(b)
                tempPos = tempPos.offset(0, 1, 0)
            } else break
        }

        // Chop from bottom to top
        for (const log of logsInTree) {
            if (Number(state.activeTaskId || 0) !== taskId) return { ok: false, error: 'interrupted' }
            if (!log || !log.name) continue
            
            const targetPos = log.position.clone()
            
            // Check if log is too high
            const dist = bot.entity.position.distanceTo(targetPos)
            if (targetPos.y > bot.entity.position.y + 3.5 || dist > 5) {
                await movement.moveTo(targetPos.x, bot.entity.position.y, targetPos.z, 2).catch(() => {})
                if (targetPos.y > bot.entity.position.y + 2.5) {
                    await movement.pillarUp().catch(() => {})
                }
            }

            // Target the SPECIFIC position
            const res = await performCollect(log.name, 1, 0, new Set(), taskId, targetPos)
            if (!res.ok) break
            
            await performManualPickup(targetPos, 5)
        }
        treesDone++
        // Final sweep for items
        if (bot.entity) await performManualPickup(bot.entity.position, 10)
    }
    return treesDone > 0 ? { ok: true } : { ok: false, error: 'no_trees_found' }
}

function isExposed(block) {
    if (!block || !block.position) return true
    const bot = state.bot
    const neighbors = [
        block.position.offset(1, 0, 0),
        block.position.offset(-1, 0, 0),
        block.position.offset(0, 1, 0),
        block.position.offset(0, -1, 0),
        block.position.offset(0, 0, 1),
        block.position.offset(0, 0, -1)
    ]
    for (const p of neighbors) {
        const b = bot.blockAt(p)
        if (!b || b.name === 'air' || b.name === 'cave_air' || b.name.includes('leaves') || b.name.includes('grass')) return true
    }
    return false
}

async function performSmartPlace(target, x, y, z) {
    const bot = state.bot
    const tPos = new vec3(Number(x), Number(y), Number(z))
    if (bot.entity.position.distanceTo(tPos) < 1.3) {
        const away = bot.entity.position.minus(tPos).normalize().scaled(1.8)
        await movement.moveTo(bot.entity.position.x + away.x, bot.entity.position.y, bot.entity.position.z + away.z, 0.5, 3000).catch(() => {})
    }
    return await interaction.placeBlock(target, x, y, z)
}

async function performMultiPlace(blocks, taskId) {
    const sorted = [...blocks].sort((a, b) => (a.y || 0) - (b.y || 0))
    for (const b of sorted) {
        if (Number(state.activeTaskId || 0) !== taskId) return { ok: false, error: 'interrupted' }
        const res = await performSmartPlace(b.target || b.itemName || b.name, b.x, b.y, b.z)
        if (!res.ok) {
            await new Promise(r => setTimeout(r, 300))
            await performSmartPlace(b.target || b.itemName || b.name, b.x, b.y, b.z)
        }
        await new Promise(r => setTimeout(r, 100))
    }
    return { ok: true }
}

async function performCollect(itemName, count = 1, depth = 0, recursionStack = new Set(), taskId, specificPos = null) {
  const bot = state.bot
  if (!bot || !bot.entity) return { ok: false, error: 'bot_not_connected' }
  if (depth > 12) return { ok: false, error: 'recursion_depth_exceeded' }
  if (recursionStack.has(itemName)) return { ok: false, error: `dependency_loop_detected: ${itemName}` }
  if (Number(state.activeTaskId || 0) !== taskId) return { ok: false, error: 'interrupted' }
  
  if (bot.inventory.emptySlotCount() === 0) {
      const existing = bot.inventory.items().find(i => i.name === itemName)
      if (!existing || existing.count >= 64) return { ok: false, error: 'inventory_full' }
  }

  recursionStack.add(itemName)
  try {
      const blockData = state.mcData.blocksByName[itemName]
      if (blockData) {
          let block = null
          if (specificPos) {
              block = bot.blockAt(new vec3(specificPos.x, specificPos.y, specificPos.z))
              // Ensure the block at specificPos matches what we expect
              if (!block || !block.name.toLowerCase().includes(itemName.toLowerCase().replace(/ /g, '_'))) {
                  block = null // Fallback to search if specific block is gone or wrong type
              }
          }

          if (!block) {
              block = bot.findBlock({ 
                  matching: blockData.id, 
                  maxDistance: 48,
                  useExtraInfo: (blk) => isExposed(blk) 
              })
          }
          
          if (block && block.position) {
              const dist = bot.entity.position.distanceTo(block.position)
              
              const handleObstructedBreak = async (targetBlock) => {
                  await bot.lookAt(targetBlock.position.offset(0.5, 0.5, 0.5), true)
                  const cursor = bot.blockAtCursor(5)
                  if (cursor && !cursor.position.equals(targetBlock.position)) {
                      if (cursor.name !== 'air' && cursor.name !== 'cave_air' && !cursor.name.includes('leaves')) {
                          const tool = bot.pathfinder.bestHarvestTool(cursor)
                          if (tool) await bot.equip(tool, 'hand')
                          try { await bot.dig(cursor) } catch (_) {}
                          await new Promise(r => setTimeout(r, 200))
                          return false 
                      }
                  }
                  const tool = bot.pathfinder.bestHarvestTool(targetBlock)
                  if (tool) await bot.equip(tool, 'hand')
                  bot.clearControlStates()
                  try { await bot.dig(targetBlock) } catch (_) {}
                  return true
              }

              if (dist < 4.8) {
                  if (Number(state.activeTaskId || 0) !== taskId) return { ok: false, error: 'interrupted' }
                  const done = await handleObstructedBreak(block)
                  if (done) return { ok: true }
                  else return await performCollect(itemName, count, depth + 1, recursionStack, taskId, specificPos)
              }

              try {
                  const tool = bot.pathfinder.bestHarvestTool(block)
                  if (tool) await bot.equip(tool, 'hand')
                  if (block.position.y > bot.entity.position.y + 2.2) await movement.pillarUp().catch(() => {})
                  if (Number(state.activeTaskId || 0) !== taskId) return { ok: false, error: 'interrupted' }
                  
                  await bot.collectBlock.collect(block)
                  return { ok: true }
              } catch (e) {
                  await movement.moveTo(block.position.x, block.position.y, block.position.z, 3.8)
                  if (Number(state.activeTaskId || 0) !== taskId) return { ok: false, error: 'interrupted' }
                  bot.clearControlStates()
                  if (block && block.position) {
                    const done = await handleObstructedBreak(block)
                    if (done) {
                        await new Promise(r => setTimeout(r, 400))
                        await performManualPickup(block.position, 5)
                        return { ok: true }
                    } else {
                        return await performCollect(itemName, count, depth + 1, recursionStack, taskId, specificPos)
                    }
                  }
              }
          }
      }

      const itemData = state.mcData.itemsByName[itemName]
      const recipes = bot.recipesFor(itemData?.id, null, 1, null)
      if (recipes.length > 0) return await performCraft(itemName, count, depth + 1, recursionStack, taskId)

      const drop = bot.nearestEntity(e => e.type === 'object' && e.name === itemName)
      if (drop) {
          await movement.moveTo(drop.position.x, drop.position.y, drop.position.z, 0.5)
          return { ok: true }
      }
      return { ok: false, error: `not_found: ${itemName}` }
  } finally {
      recursionStack.delete(itemName)
  }
}

async function performCraft(itemName, count = 1, depth = 0, recursionStack = new Set(), taskId) {
  const bot = state.bot
  const item = state.mcData.itemsByName[itemName]
  if (depth > 12) return { ok: false, error: 'craft_depth_exceeded' }
  if (recursionStack.has(itemName)) return { ok: false, error: `dependency_loop_detected_craft: ${itemName}` }
  if (Number(state.activeTaskId || 0) !== taskId) return { ok: false, error: 'interrupted' }

  const recipe = bot.recipesFor(item.id, null, 1, true)[0]
  if (!recipe) return { ok: false, error: `no_recipe: ${itemName}` }

  recursionStack.add(itemName)
  try {
      for (const [id, req] of Object.entries(getRequiredIngredients(recipe))) {
          const name = state.mcData.items[id].name
          const owned = bot.inventory.items().filter(i => i.type === Number(id)).reduce((a, b) => a + b.count, 0)
          if (owned < req * count) {
              const res = await performCollect(name, (req * count) - owned, depth + 1, recursionStack, taskId)
              if (!res.ok) return res
          }
      }

      if (recipe.requiresTable) {
          let table = bot.findBlock({ matching: state.mcData.blocksByName.crafting_table.id, maxDistance: 12 })
          if (!table) {
              const has = bot.inventory.items().find(i => i.name === 'crafting_table')
              if (!has) {
                  const res = await performCraft('crafting_table', 1, depth + 1, recursionStack, taskId)
                  if (!res.ok) return res
              }
              const p = bot.entity.position.floored().offset(1, 0, 0)
              await interaction.placeBlock('crafting_table', p.x, p.y, p.z)
              table = bot.findBlock({ matching: state.mcData.blocksByName.crafting_table.id, maxDistance: 4 })
          }
          if (table && table.position) {
              await movement.moveTo(table.position.x, table.position.y, table.position.z, 2.5)
              if (Number(state.activeTaskId || 0) !== taskId) return { ok: false, error: 'interrupted' }
              await bot.craft(recipe, count, table)
              if (bot.inventory.emptySlotCount() > 0) {
                  await bot.dig(table).catch(() => {})
                  await new Promise(r => setTimeout(r, 500))
                  await performManualPickup(table.position, 3)
              }
          }
      } else {
          await bot.craft(recipe, count, null)
      }
      return { ok: true, crafted: itemName }
  } finally {
      recursionStack.delete(itemName)
  }
}

function getRequiredIngredients(recipe) {
    const counts = {}
    const items = recipe.delta || (recipe.ingredients ? recipe.ingredients.map(id => ({id, count: -1})) : [])
    items.forEach(d => { if (d.count < 0) counts[d.id] = (counts[d.id] || 0) + Math.abs(d.count) })
    return counts
}

async function performAttack(target, taskId) {
    const bot = state.bot
    const e = bot.nearestEntity(ent => 
        (ent.name && ent.name.toLowerCase() === target.toLowerCase()) || 
        (ent.username && ent.username === target)
    )
    if (!e) return { ok: false, error: 'target_not_found' }
    
    while (e.isValid && bot.health > 0) {
        if (Number(state.activeTaskId || 0) !== taskId) return { ok: false, error: 'interrupted' }
        if (!e.position) break
        const dist = bot.entity.position.distanceTo(e.position)
        if (dist > 3.0) await movement.moveTo(e.position.x, e.position.y, e.position.z, 1.8, 3000).catch(() => {})
        if (e.position) await bot.lookAt(e.position.offset(0, 0.5, 0), true)
        bot.attack(e)
        await new Promise(r => setTimeout(r, 600))
        if (e.metadata && e.metadata[9] <= 0) break
        if (bot.entity.position.distanceTo(e.position) > 15) break
    }
    return { ok: true }
}

async function performEat() {
    const bot = state.bot
    const food = bot.inventory.items().find(i => state.mcData.foodsByName[i.name])
    if (!food) return { ok: false, error: 'no_food' }
    await bot.equip(food, 'hand')
    await bot.consume()
    return { ok: true }
}

async function performEquip(name) {
    const bot = state.bot
    const it = bot.inventory.items().find(i => i.name === name)
    if (!it) return { ok: false, error: 'not_in_inv' }
    await bot.equip(it, 'hand')
    return { ok: true }
}

async function performInteract(x, y, z) {
    const bot = state.bot
    const b = bot.blockAt(new vec3(x, y, z))
    if (!b) return { ok: false, error: 'no_block' }
    await movement.moveTo(x, y, z, 3)
    await bot.activateBlock(b)
    return { ok: true }
}

async function performManualPickup(pos, rad) {
    if (!pos) return
    const bot = state.bot
    if (!bot || !bot.entity) return
    const drops = Object.values(bot.entities).filter(e => e.type === 'object' && e.position && e.position.distanceTo(pos) < rad)
    for (const d of drops) {
        if (!d.isValid || !d.position) continue
        await movement.moveTo(d.position.x, d.position.y, d.position.z, 0.4, 2000).catch(() => {})
        await new Promise(r => setTimeout(r, 100))
    }
}

function getShortRangeSnapshot(radius, targetName = null) {
    const bot = state.bot
    if (!bot || !bot.entity || !bot.entity.position) return { blocks: [] }
    const p = bot.entity.position
    
    // Safety check for NaN
    if (isNaN(p.x) || isNaN(p.y) || isNaN(p.z)) return { blocks: [], error: 'bot_position_nan' }

    const candidates = []
    
    const normTarget = targetName ? targetName.toLowerCase().replace(/ /g, '_') : null
    
    const BASE_SCORES = {
        'ore': 1200,
        'log': 1000,
        'table': 800,
        'chest': 900,
        'furnace': 850,
        'bed': 700,
        'door': 400,
        'torch': 300,
        'leaves': -300,
        'grass': -400,
        'dirt': -350
    }

    for (let x = -radius; x <= radius; x++) {
        for (let y = -5; y <= 20; y++) {
            for (let z = -radius; z <= radius; z++) {
                const targetPos = p.offset(x, y, z)
                if (!targetPos) continue
                const block = bot.blockAt(targetPos)
                if (block && block.name !== 'air' && block.name !== 'cave_air') {
                    let score = 0
                    const bName = block.name.toLowerCase().replace(/ /g, '_')
                    
                    if (normTarget && (bName === normTarget || bName.includes(normTarget))) {
                        score += 4000 / (p.distanceTo(block.position) + 1)
                    }

                    for (const [cat, val] of Object.entries(BASE_SCORES)) {
                        if (bName.includes(cat)) {
                            score += val
                            if (cat === 'log' && block.position) {
                                const above = bot.blockAt(block.position.offset(0,1,0))
                                if (above && above.name.includes('log')) score += 300
                            }
                            break
                        }
                    }
                    const dist = p.distanceTo(block.position)
                    candidates.push({ name: block.name, pos: block.position, score, dist })
                }
            }
        }
    }
    candidates.sort((a, b) => b.score - a.score || a.dist - b.dist)
    return { blocks: candidates.slice(0, 45).map(c => ({ name: c.name, pos: c.pos })) }
}

module.exports = { executeAct }
