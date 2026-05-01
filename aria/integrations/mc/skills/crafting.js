const { state } = require('../bot')

async function craftItem(itemName, count = 1) {
  const bot = state.bot
  if (!bot || !bot.entity) return { ok: false, error: 'bot_not_connected' }
  if (!itemName) return { ok: false, error: 'item_name_missing' }

  const item = state.mcData.itemsByName[itemName] || 
               Object.values(state.mcData.items).find(i => i.name.toLowerCase().includes(itemName.toLowerCase()))
  
  if (!item) return { ok: false, error: `unknown_item:${itemName}` }
  
  // Find a crafting table nearby FIRST to support 3x3 recipes
  const craftingTable = bot.findBlock({ 
    matching: state.mcData.blocksByName.crafting_table.id, 
    maxDistance: 4 
  })

  // Check for recipes, providing the table if we found one
  const recipe = bot.recipesFor(item.id, null, count, craftingTable)[0]
  
  if (!recipe) {
    let errorMsg = 'no_recipe_or_missing_ingredients'
    if (!craftingTable) {
        // Double check: maybe it's a 3x3 recipe and we just don't have a table?
        const anyRecipe = bot.recipesAll(item.id, null, true)[0]
        if (anyRecipe && anyRecipe.requiresTable) {
            errorMsg = 'crafting_table_required_but_not_found_nearby'
        }
    }
    return { 
        ok: false, 
        error: errorMsg,
        hint: errorMsg.includes('table') ? 'You must mc_place a crafting_table and mc_move close to it before crafting this item.' : undefined
    }
  }
  
  try {
    if (craftingTable) {
       await bot.lookAt(craftingTable.position)
    }
    await bot.craft(recipe, count, craftingTable)
    return { ok: true, crafted: itemName, count: count }
  } catch(e) { 
    return { ok: false, error: String(e?.message || e) } 
  }
}

module.exports = {
  craftItem
}
