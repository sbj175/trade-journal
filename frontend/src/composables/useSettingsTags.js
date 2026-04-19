/**
 * Tag management: load, edit, save, delete.
 */
import { ref } from 'vue'
import { useConfirm } from '@/composables/useConfirm'

export function useSettingsTags(Auth, { showNotification }) {
  const { confirm } = useConfirm()
  const tags = ref([])
  const editingTag = ref(null)
  const editName = ref('')
  const editColor = ref('')
  const deletingTagId = ref(null)

  async function loadTags() {
    try {
      const resp = await Auth.authFetch('/api/tags')
      if (resp.ok) tags.value = await resp.json()
    } catch (e) {
      showNotification('Failed to load tags', 'error')
    }
  }

  function startEditTag(tag) {
    editingTag.value = tag.id
    editName.value = tag.name
    editColor.value = tag.color
  }

  function cancelEditTag() {
    editingTag.value = null
    editName.value = ''
    editColor.value = ''
  }

  async function saveTag() {
    if (!editName.value.trim()) {
      showNotification('Tag name cannot be empty', 'error')
      return
    }
    try {
      const resp = await Auth.authFetch(`/api/tags/${editingTag.value}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name: editName.value.trim(), color: editColor.value }),
      })
      if (resp.ok) {
        showNotification('Tag updated', 'success')
        cancelEditTag()
        await loadTags()
      } else {
        const data = await resp.json().catch(() => ({}))
        showNotification(data.detail || 'Failed to update tag', 'error')
      }
    } catch (e) {
      showNotification('Failed to update tag', 'error')
    }
  }

  async function deleteTag(tag) {
    const msg = tag.group_count > 0
      ? `Delete "${tag.name}"? It is used by ${tag.group_count} position group${tag.group_count === 1 ? '' : 's'} and will be removed from all of them.`
      : `Delete "${tag.name}"?`
    const ok = await confirm({ title: 'Delete Tag', message: msg, confirmText: 'Delete', variant: 'danger' })
    if (!ok) return
    deletingTagId.value = tag.id
    try {
      const resp = await Auth.authFetch(`/api/tags/${tag.id}`, { method: 'DELETE' })
      if (resp.ok) {
        showNotification('Tag deleted', 'success')
        await loadTags()
      } else {
        const data = await resp.json().catch(() => ({}))
        showNotification(data.detail || 'Failed to delete tag', 'error')
      }
    } catch (e) {
      showNotification('Failed to delete tag', 'error')
    }
    deletingTagId.value = null
  }

  return {
    tags,
    editingTag,
    editName,
    editColor,
    deletingTagId,
    loadTags,
    startEditTag,
    cancelEditTag,
    saveTag,
    deleteTag,
  }
}
