import React from 'react';
import ReactDOM from 'react-dom/client';
import { ConvexProvider, ConvexReactClient } from 'convex/react';
import App from './App';
import './index.css';
import { ConvexAvailableContext } from './hooks/useConvex';

// Initialize Convex client
// In production, this URL comes from environment variables
const convexUrl = import.meta.env.VITE_CONVEX_URL || '';

// Only create client if URL is provided
const convex = convexUrl ? new ConvexReactClient(convexUrl) : null;

function Root() {
  if (!convex) {
    // Fallback when Convex is not configured - app still works with local storage
    return (
      <React.StrictMode>
        <ConvexAvailableContext.Provider value={false}>
          <App />
        </ConvexAvailableContext.Provider>
      </React.StrictMode>
    );
  }

  return (
    <React.StrictMode>
      <ConvexProvider client={convex}>
        <ConvexAvailableContext.Provider value={true}>
          <App />
        </ConvexAvailableContext.Provider>
      </ConvexProvider>
    </React.StrictMode>
  );
}

ReactDOM.createRoot(document.getElementById('root')!).render(<Root />);
