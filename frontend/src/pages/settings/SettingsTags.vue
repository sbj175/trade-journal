<script setup>
defineProps({ state: Object })
</script>

<template>
  <div>
    <div class="mb-6">
      <h2 class="text-xl font-semibold text-tv-text mb-1">
        <i class="fas fa-tags mr-2 text-tv-blue"></i>Tags
      </h2>
      <p class="text-tv-muted text-sm">Manage tags used to organize your position groups</p>
    </div>

    <div class="bg-tv-bg border border-tv-border rounded p-3 text-sm text-tv-muted mb-5">
      <i class="fas fa-info-circle mr-1 text-tv-blue"></i>
      Tags are created from the Ledger or Positions page. Use this section to rename, recolor, or delete existing tags.
    </div>

    <div v-if="state.tags.value.length > 0" class="bg-tv-panel border border-tv-border rounded">
      <div v-for="tag in state.tags.value" :key="tag.id"
           class="flex items-center gap-3 px-4 py-3 border-b border-tv-border/50 last:border-b-0">
        <template v-if="state.editingTag.value !== tag.id">
          <span class="w-5 h-5 rounded-full flex-shrink-0 border border-tv-border"
                :style="{ backgroundColor: tag.color }"></span>
          <span class="text-tv-text text-sm font-medium flex-1">{{ tag.name }}</span>
          <span class="text-tv-muted text-xs bg-tv-bg border border-tv-border rounded px-2 py-0.5">
            {{ tag.group_count }} {{ tag.group_count === 1 ? 'position' : 'positions' }}
          </span>
          <button @click="state.startEditTag(tag)"
                  class="text-tv-muted hover:text-tv-blue text-sm p-1" title="Edit tag">
            <i class="fas fa-pen"></i>
          </button>
          <button @click="state.deleteTag(tag)" :disabled="state.deletingTagId.value === tag.id"
                  class="text-tv-muted hover:text-tv-red text-sm p-1 disabled:opacity-50" title="Delete tag">
            <i :class="state.deletingTagId.value === tag.id ? 'fas fa-spinner fa-spin' : 'fas fa-trash-alt'"></i>
          </button>
        </template>
        <template v-else>
          <input type="color" v-model="state.editColor.value"
                 class="w-7 h-7 rounded cursor-pointer border border-tv-border bg-transparent flex-shrink-0"
                 title="Pick color">
          <input type="text" v-model="state.editName.value"
                 class="flex-1 bg-tv-bg border border-tv-border text-tv-text px-3 py-1.5 rounded text-sm focus:outline-none focus:border-tv-blue"
                 @keyup.enter="state.saveTag()" @keyup.escape="state.cancelEditTag()">
          <button @click="state.saveTag()"
                  class="bg-tv-blue hover:bg-tv-blue/80 text-white px-3 py-1.5 rounded text-sm">
            <i class="fas fa-check mr-1"></i>Save
          </button>
          <button @click="state.cancelEditTag()"
                  class="text-tv-muted hover:text-tv-text border border-tv-border px-3 py-1.5 rounded text-sm">
            Cancel
          </button>
        </template>
      </div>
    </div>

    <div v-else class="bg-tv-panel border border-tv-border rounded p-8 text-center">
      <i class="fas fa-tags text-tv-muted text-3xl mb-3"></i>
      <p class="text-tv-muted text-sm">No tags yet. Create tags from the Ledger or Positions page.</p>
    </div>
  </div>
</template>
