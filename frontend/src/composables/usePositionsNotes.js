/**
 * Notes (DB-persisted comments) and tags for the Positions page.
 * Composable that manages comment/tag state and CRUD operations.
 */
import { ref, computed } from 'vue'

export function usePositionsNotes(Auth, { allItems }) {
  // --- Notes state ---
  const positionComments = ref({})
  const _noteSaveTimers = {}

  // --- Tag state ---
  const availableTags = ref([])
  const tagPopoverGroup = ref(null)
  const tagSearch = ref('')

  const filteredTagSuggestions = computed(() => {
    const search = (tagSearch.value || '').toLowerCase()
    const group = allItems.value.find(g => g.group_id === tagPopoverGroup.value)
    const appliedIds = (group?.tags || []).map(t => t.id)
    return availableTags.value
      .filter(t => !appliedIds.includes(t.id))
      .filter(t => !search || t.name.toLowerCase().includes(search))
  })

  // --- Notes ---
  async function loadComments() {
    try {
      const response = await Auth.authFetch('/api/position-notes')
      if (response.ok) {
        const data = await response.json()
        positionComments.value = data.notes || {}
      } else {
        positionComments.value = {}
      }
    } catch (err) {
      positionComments.value = {}
    }
    // One-time migration from localStorage
    try {
      const stored = localStorage.getItem('positionComments')
      if (stored) {
        const local = JSON.parse(stored)
        let migrated = false
        for (const [key, value] of Object.entries(local)) {
          if (value && !positionComments.value[key]) {
            positionComments.value[key] = value
            Auth.authFetch(`/api/position-notes/${encodeURIComponent(key)}`, {
              method: 'PUT',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({ note: value })
            }).catch(() => {})
            migrated = true
          }
        }
        localStorage.removeItem('positionComments')
      }
    } catch (e) { /* ignore migration errors */ }
  }

  function migrateCommentKeys() {
    // Legacy migration from chain_* to group_* comment keys.
    try {
      for (const item of allItems.value) {
        const groupId = item.group_id || item.chain_id
        if (!groupId) continue

        const newKey = `group_${groupId}`
        const oldChainKey = `chain_${groupId}`

        if (positionComments.value[oldChainKey] && !positionComments.value[newKey]) {
          positionComments.value[newKey] = positionComments.value[oldChainKey]
          Auth.authFetch(`/api/position-notes/${encodeURIComponent(newKey)}`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ note: positionComments.value[oldChainKey] })
          }).catch(() => {})
        }
        if (positionComments.value[oldChainKey]) {
          delete positionComments.value[oldChainKey]
          Auth.authFetch(`/api/position-notes/${encodeURIComponent(oldChainKey)}`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ note: '' })
          }).catch(() => {})
        }
      }
    } catch (e) { /* ignore migration errors */ }
  }

  function getCommentKey(group) {
    const groupId = group.group_id || group.chain_id || group.chainId
    if (groupId) return `group_${groupId}`
    return `pos_${group.underlying}_${group.accountNumber || 'default'}`
  }

  function getPositionComment(group) {
    const key = getCommentKey(group)
    if (!key) return ''
    return positionComments.value[key] || ''
  }

  function updatePositionComment(group, value) {
    const key = getCommentKey(group)
    if (!key) return
    positionComments.value[key] = value
    if (_noteSaveTimers[key]) {
      clearTimeout(_noteSaveTimers[key])
    }
    _noteSaveTimers[key] = setTimeout(() => {
      Auth.authFetch(`/api/position-notes/${encodeURIComponent(key)}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ note: value })
      }).catch(() => {})
      delete _noteSaveTimers[key]
    }, 500)
  }

  function cleanupNoteTimers() {
    Object.values(_noteSaveTimers).forEach(t => clearTimeout(t))
  }

  // --- Tags ---
  async function loadAvailableTags() {
    try {
      const resp = await Auth.authFetch('/api/tags')
      availableTags.value = await resp.json()
    } catch (e) { }
  }

  function openTagPopover(groupId, event) {
    if (event) event.stopPropagation()
    tagPopoverGroup.value = tagPopoverGroup.value === groupId ? null : groupId
    tagSearch.value = ''
    if (tagPopoverGroup.value) {
      setTimeout(() => {
        const input = document.getElementById('tag-input-' + groupId)
        if (input) input.focus()
      }, 0)
    }
  }

  function closeTagPopover() {
    tagPopoverGroup.value = null
    tagSearch.value = ''
  }

  async function addTagToGroup(group, nameOrTag) {
    const payload = typeof nameOrTag === 'string'
      ? { name: nameOrTag.trim() }
      : { tag_id: nameOrTag.id }
    if (payload.name === '' && !payload.tag_id) return
    try {
      const resp = await Auth.authFetch(`/api/ledger/groups/${group.group_id}/tags`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      })
      const tag = await resp.json()
      if (!group.tags) group.tags = []
      if (!group.tags.find(t => t.id === tag.id)) {
        group.tags.push(tag)
      }
      await loadAvailableTags()
      tagSearch.value = ''
    } catch (e) { }
  }

  async function removeTagFromGroup(group, tagId, event) {
    if (event) event.stopPropagation()
    try {
      await Auth.authFetch(`/api/ledger/groups/${group.group_id}/tags/${tagId}`, {
        method: 'DELETE',
      })
      group.tags = (group.tags || []).filter(t => t.id !== tagId)
    } catch (e) { }
  }

  function handleTagInput(event, group) {
    if (event.key === 'Enter') {
      event.preventDefault()
      const search = tagSearch.value.trim()
      if (!search) return
      const exactMatch = filteredTagSuggestions.value.find(
        t => t.name.toLowerCase() === search.toLowerCase()
      )
      addTagToGroup(group, exactMatch || search)
    } else if (event.key === 'Escape') {
      closeTagPopover()
    }
  }

  function onDocumentClick(event) {
    if (tagPopoverGroup.value && !event.target.closest('[data-tag-popover]')) {
      closeTagPopover()
    }
  }

  return {
    // Notes state
    positionComments,
    // Tag state
    availableTags, tagPopoverGroup, tagSearch,
    // Computed
    filteredTagSuggestions,
    // Notes methods
    loadComments, migrateCommentKeys, getPositionComment, updatePositionComment,
    cleanupNoteTimers,
    // Tag methods
    loadAvailableTags, openTagPopover, closeTagPopover,
    addTagToGroup, removeTagFromGroup, handleTagInput,
    // Lifecycle helper
    onDocumentClick,
  }
}
