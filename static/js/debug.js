// Debug helper to monitor what's happening
console.log('Trade Journal Debug Mode');

// Monitor all fetch requests
const originalFetch = window.fetch;
window.fetch = function(...args) {
    console.log('Fetch request:', args[0]);
    return originalFetch.apply(this, args)
        .then(response => {
            console.log('Fetch response:', args[0], response.status);
            return response;
        })
        .catch(error => {
            console.error('Fetch error:', args[0], error);
            throw error;
        });
};

// Monitor DOM changes
const observer = new MutationObserver((mutations) => {
    mutations.forEach((mutation) => {
        if (mutation.type === 'childList' && mutation.addedNodes.length > 0) {
            mutation.addedNodes.forEach(node => {
                if (node.nodeType === 1) { // Element node
                    console.log('DOM added:', node.className || node.tagName);
                }
            });
        }
    });
});

// Start observing
observer.observe(document.body, {
    childList: true,
    subtree: true
});

console.log('Debug mode active - check console for activity');