"use strict";

// Load the current renderer on each page visit, even after a cached older build.
import(`./app.js?v=figures-4-${Date.now()}`).catch(() => {
  document.getElementById("status").textContent = "The updated chat interface could not load. Refresh this page and try again.";
});
