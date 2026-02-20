/**
 * Shared utility functions for OptionLedger.
 * Loaded globally — Alpine.js templates resolve these via window scope
 * when not found on the component.
 */

function formatNumber(value, decimals = 2) {
    if (value === null || value === undefined || isNaN(value)) return decimals === 0 ? '0' : '0.00';
    return new Intl.NumberFormat('en-US', {
        minimumFractionDigits: decimals,
        maximumFractionDigits: decimals
    }).format(value);
}

function formatDate(dateStr) {
    if (!dateStr) return '';
    const parts = dateStr.split('-');
    if (parts.length === 3) {
        const date = new Date(parseInt(parts[0]), parseInt(parts[1]) - 1, parseInt(parts[2]));
        return date.toLocaleDateString('en-US', { year: 'numeric', month: 'short', day: 'numeric' });
    }
    return dateStr;
}

function formatOrderDate(isoString) {
    if (!isoString) return '';
    const d = new Date(isoString);
    const month = d.getMonth() + 1;
    const day = d.getDate();
    let hours = d.getHours();
    const minutes = d.getMinutes().toString().padStart(2, '0');
    const ampm = hours >= 12 ? 'p' : 'a';
    hours = hours % 12 || 12;
    return `${month}/${day} ${hours}:${minutes}${ampm}`;
}

function formatExpirationShort(expiration) {
    if (!expiration) return '';
    const date = new Date(expiration + 'T00:00:00');
    const months = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
    return `${months[date.getMonth()]} ${date.getDate()}`;
}

function calculateDTE(expiration) {
    if (!expiration) return 0;
    const expDate = new Date(expiration + 'T00:00:00');
    const today = new Date();
    today.setHours(0, 0, 0, 0);
    const diffTime = expDate - today;
    const diffDays = Math.ceil(diffTime / (1000 * 60 * 60 * 24));
    return Math.max(0, diffDays);
}
